import requests
import logging
import json
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MeinvoiceConfig(models.Model):
    """
    Cấu hình kết nối MISA MeInvoice.
    1 company = 1 config record.
    Token cache tự động refresh qua cron.

    Design:
    - base_url + endpoint_* nhập tay → linh hoạt test/prod
    - Không hardcode URL → chỉ đổi config khi chuyển môi trường
    - app_id optional → sandbox không cần, production cần
    """
    _name = 'meinvoice.config'
    _description = 'MISA MeInvoice Config'
    _rec_name = 'name'

    name = fields.Char('Tên cấu hình',required=True, default='[sandbox] Cấu hình MeInvoice')
    company_id = fields.Many2one('res.company','Công ty',required=True, default=lambda self: self.env.company)

    #--credentials ---
    app_id = fields.Char('App ID', help='App ID do MISA cấp. Production cần, sandbox không cần.')
    tax_code = fields.Char('MST', required=True)
    username = fields.Char('Tài khoản MeInvoice', required=True)
    password = fields.Char('Mật khẩu MeInvoice', required=True)

    #-- base url + endpoints ---
    base_url = fields.Char(
        'Base URL', required=True,
        default='https://testapi.meinvoice.vn/api/integration',
        help='Sandbox: https://testapi.meinvoice.vn/api/integration\n'
             'Production: https://api.meinvoice.vn/api/integration',
    )
    endpoint_token = fields.Char(
        'Endpoint: Lấy token', required=True,
        default='/webapp/token',
    )
    endpoint_templates = fields.Char(
        'Endpoint: Lấy mẫu HĐ', required=True,
        default='/webapp/templates',
    )
    endpoint_preview = fields.Char(
        'Endpoint: Xem trước HĐ', required=True,
        default='/webapp/preview',
    )
    endpoint_insert = fields.Char(
        'Endpoint: Tạo HĐ nháp', required=True,
        default='/webapp/insert',
    )
    endpoint_getlist = fields.Char(
        'Endpoint: Lấy trạng thái theo RefID', required=True,
        default='/webapp/getlist',
    )
    endpoint_paging = fields.Char(
        'Endpoint: Danh sách HĐ phân trang', required=True,
        default='/webapp/paging',
    )
    endpoint_viewrefid = fields.Char(
        'Endpoint: Xem HĐ theo RefID', required=True,
        default='/webapp/viewrefid',
    )
    endpoint_delete = fields.Char(
        'Endpoint: Xóa HĐ nháp', required=True,
        default='/webapp/delete',
    )
    endpoint_publish = fields.Char(
        'Endpoint: Phát hành HĐ', required=True,
        default='/invoice',
        help='Production V1: /invoice với SignType=2 (HSM)',
    )
    endpoint_publishview = fields.Char(
        'Endpoint: Xem HĐ đã phát hành', required=True,
        default='/invoice/publishview',
    )
    endpoint_sendemail = fields.Char(
        'Endpoint: Gửi email HĐ', required=True,
        default='/invoice/sendemail',
    )

    #  Invoice config
    inv_series = fields.Char(
        'Ký hiệu HĐ (InvSeries)', required=True,
        help='VD: 1C26TAS. MISA tự xử lý theo năm.',
    )
    invoice_template_id = fields.Char(
        'Invoice Template ID',
        help='IPTemplateID từ API templates. Bấm [Lấy Templates] để tự điền.',
    )

    # Sign type
    sign_type = fields.Selection([
        ('0', 'Chưa cấu hình'),
        ('2', 'HSM - Có hiển thị CKS (khuyến nghị)'),
        ('1', 'USB Token / File mềm'),
        ('5', 'HSM - Không hiển thị CKS'),
    ], string='Kiểu ký số', required=True, default='0',
        help='SignType=2: HSM ký server-side, phát hành luôn.\n'
             'SignType=1: Cần tool ký riêng (3 bước).',
    )

    # HSM config
    hsm_host = fields.Char(
        'HSM Host', help='Chỉ dùng khi SignType=1. VD: http://localhost:12019',
    )
    hsm_pin = fields.Char(
        'HSM PIN Code', help='Mật khẩu chứng thư số. Chỉ dùng khi SignType=1.',
    )

    #  Token cache
    access_token = fields.Char(
        'Access Token', readonly=True, copy=False,
        help='Tự động cập nhật. Không nhập tay.',
    )
    token_expiry = fields.Datetime(
        'Token hết hạn lúc', readonly=True, copy=False,
    )

    active = fields.Boolean(default=True)

    #url builder
    def _build_url(self, endpoint_field):
        """
        Ghép base_url + endpoint từ field config.

        Args:
           endpoint_field (str): tên field endpoint VD: 'endpoint_token'

        Returns:
           str: full URL

        VD: config._build_url('endpoint_token')
           → 'https://testapi.meinvoice.vn/api/integration/webapp/token'
        """
        self.ensure_one()
        return f"{self.base_url.rstrip('/')}{getattr(self, endpoint_field)}"

    # token manag
    def _is_token_valid(self):
        """
        Kiểm tra token cache còn hạn không.
        Buffer 1 ngày để tránh hết hạn giữa chừng.
        """
        if not self.access_token or not self.token_expiry:
            return False
        safe_expiry = self.token_expiry - timedelta(days=1)
        return datetime.now() < safe_expiry

    def _fetch_new_token(self):
        """
        Lấy token mới qua meinvoice_api để có logging đầy đủ.
        QUAN TRỌNG: Không gọi hàm này mỗi lần phát hành HĐ.
        MISA giới hạn số lần gọi — gọi liên tục sẽ bị block IP.
        """
        token = self.env['meinvoice.api'].fetch_token(self)
        expiry = datetime.now() + timedelta(days=13)
        self.sudo().write({
            'access_token': token,
            'token_expiry': expiry,
        })

    def get_valid_token(self):
        """
        Entry point lấy token hợp lệ.
        Cache -> dùng lại nếu còn hạn, fetch mới nếu hết.
        """
        if self._is_token_valid():
            _logger.debug('[MeInvoice]: Using cached token')
            return self.access_token
        return self._fetch_new_token()

    #-- actions ---

    def action_refresh_token(self):
        """Button refresh token thu cong"""
        self._fetch_new_token()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Thành Công'),
                'message': _('Token đã refresh. Hết hạn: %s') % self.token_expiry,
                'type': 'success',
            }
        }

    def action_test_connection(self):
        """
        Test kết nối: POST /webapp/templates + body credentials.
        V2: không cần token để lấy templates.
        """
        url = self._build_url('endpoint_templates')
        payload = {
            'taxcode': self.tax_code,
            'username': self.username,
            'password': self.password,
        }
        if self.app_id:
            payload['appid'] = self.app_id
        try:
            res = requests.post(
                url=url,
                json=payload,
                params={'invoiceWithCode':'true'},
                headers={'Content-Type': 'application/json'},
                timeout=30,
            )
            data = res.json()
        except Exception as e:
            raise UserError(_('Test Kết nối thất bại: %s') % str(e))
        if data.get('success'):
            templates = data.get('data',[])
            if isinstance(templates, str):
                templates = json.loads(templates)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title':_('Kết nối thành công'),
                        'message': _('Tìm thấy %s mẫu hóa đơn.') % len(templates),
                        'type': 'success',
                    }
                }
            raise UserError(_('Kết nối thất bại: %s') % data.get('error','UNKNOWN'))

    def action_fetch_templates(self):
        """
        Tự động lấy IPTemplateID đầu tiên từ API
        và điền vào field invoice_template_id.
        """
        url = self._build_url('endpoint_templates')
        payload = {
            'taxcode': self.tax_code,
            'username': self.username,
            'password': self.password,
        }
        if self.app_id:
            payload['appid'] = self.app_id
        try:
            res = requests.post(
                url=url,
                json=payload,
                params={'invoiceWithCode':'true'},
                headers={'Content-Type': 'application/json'},
                timeout=30,
            )
            data = res.json()
        except Exception as e:
            raise UserError(_('Lấy template thất bại: %s ') % str(e))
        if not data.get('success'):
            raise UserError(_('Lỗi %s') % data.get('error','UNKNOWN'))
        templates = data.get('data',[])
        if isinstance(templates, str):
            templates = json.loads(templates)
        if not templates:
            raise UserError(_('Không tìm thấy mẫu hóa đơn nào.'))
        first = templates[0]
        self.write({'invoice_template_id': first.get('IPTemplateID')})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Thành công'),
                'message': _('Đã lấy %d mẫu. Template ID: %s — Ký hiệu: %s') % (
                    len(templates),
                    first.get('IPTemplateID'),
                    first.get('InvSeries'),
                ),
                'type': 'success',
            }
        }

    #-- helpers --
    @api.model
    def get_active_config(self):
        """
        Lấy config active của company hiện tại.
        Dùng từ các model khác.
        """
        config = self.search([
            ('company_id','=', self.env.company.id),
            ('active','=', True),
        ], limit=1)
        if not config:
            raise (_('Chưa có cấu hình MeInvoice. '
                'Vào menu MeInvoice → Cấu hình để thiết lập.'))
        return config

    @api.model
    def cron_refresh_token(self):
        """Cron tu dong refresh token moi 7day"""
        configs = self.search(['active','=',True])
        for config in configs:
            try:
                if not config._is_token_valid():
                    config._fetch_new_token()
                    _logger.info('[MeInvoice cron]: Refreshed token for config %s', config.name,)
            except Exception as e:
                _logger.error('[MeInvoice cron]: Failed for config %s: %s', config.name, str(e))
                