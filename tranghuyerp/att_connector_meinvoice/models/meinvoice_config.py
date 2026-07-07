import requests
import logging
from datetime import datetime, timedelta
from odoo import models, fields, api, exceptions,_
from odoo.exceptions import ValidationError, UserError



_logger = logging.getLogger(__name__)


class MeInvoiceConfig(models.Model):
    """
        Lưu thông tin kết nối đến MISA MeInvoice.
        1 company chỉ cần 1 config record.
        Token được cache ở đây, refresh tự động qua cron.
        """
    _name = 'meinvoice.config'
    _description = 'MISA MeInvoice Configuration'
    _rec_name = 'name'

    name = fields.Char('Tên cấu hình', required=True, default='Cấu hình MeInvoice')
    company_id = fields.Many2one('res.company', required=True,string='Công ty', default=lambda self: self.env.company)

    #-- credentials ----
    app_id = fields.Char('App ID', required=True, help='App ID do MISA cấp khi đăng ký tích hợp API')
    tax_code = fields.Char('MST', required=True, help='MST của công ty trên hệ thống MeInvoice')
    username = fields.Char('Tài khoản MeInvoice', required=True)
    password = fields.Char('Mật khẩu MeInvoice', required=True)

    #-- ENV---
    environment = fields.Selection(
        selection=[
            ('sand_box','Môi trường test'),
            ('production','Môi trường chính thức')
    ],string='Môi trường',required=True, default='sand_box'
    )

    #-- token cache ---
    access_token = fields.Char('Access Token', readonly=True, copy=False, help='Token tự đông update, không cần nhập tay.')
    token_expiry = fields.Datetime('Token hết hạn lúc',readonly=True, copy=False)

    #-- InvSeries default ---
    inv_series = fields.Char('Ký hiệu hóa đơn (InSeries)',required=True, help='VD: 126TAS. MISA xử lý')

    #-- sign type ---
    #extend after.
    sign_type = fields.Selection(
        selection=[
            ('0', 'Chưa có'),
            ('2', 'HSM - Có hiển thị CKS (khuyến nghị)'),
            ('1', 'USB Token / File mềm (cần tool ký riêng)'),
            ('5', 'HSM - Không hiển thị CKS'),
        ],string='Kiểu ký số',required=True, default='2',help=('SignType=2: HSM ký server-side, phát hành luôn.\n'
                                                                'SignType=1: Cần tool ký riêng cài trên máy client (3 bước).'),
    )

    #-- HSM config ---
    hsm_host = fields.Char('HSM Host ( cho USB Token', help='chỉ dùng khi SignType=1')
    hsm_pin = fields.Char('HSM PIN Code', help='Mật khẩu chứng thư số — chỉ dùng khi SignType=1')

    active = fields.Boolean(default=True)

    #-- compute base URL env ---
    # @property
    def _get_base_url(self):
        """
        Return base_url based on env is selected.
        """
        if self.environment == 'production':
            return 'https://api.meinvoice.vn/api/integration'
        return 'https://testapi.meinvoice.vn/api/integration'

    #-- token management ---
    def _is_token_valid(self):
        if not self.access_token or not self.token_expiry:
            return False
        safe_expiry = self.token_expiry - timedelta(days=1)
        return datetime.now() < safe_expiry

    def _fetch_new_token(self):
        """
        call API /auth/token.
        store token + expiry to db.
        returns: str: new_token
        raises: UserError : If API returned error or network error.
        """
        url = f'{self._get_base_url()}/webapp/token'
        payload = {
            'appid' : self.app_id,
            'taxcode': self.tax_code,
            'username' : self.username,
            'password' : self.password,
        }
        _logger.info('MeInvoice: Fetching new token for tax_code=%s',self.tax_code)

        try:
            response = requests.post(
                url=url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.Timeout:
            raise UserError(_('MeInvoice: Timeout when get token. Try later.'))
        except requests.exceptions.ConnectionError:
            raise UserError(_('MeInvoice: Cannot connect to server. Check your network'))
        except Exception as e:
            raise UserError(_('MeInvoice: Error undefined: %s') % str(e))
        #check res success
        if not data.get('Success'):
            error_code = data.get('ErrorCode', 'UNKNOWN')
            _logger.error('MeInvoice: get token failed: %s', data)
            raise UserError(_('MeInvoice: Get token failed. ErrorCode:%s') % error_code)

        token = data.get('Data')
        if not token:
            raise UserError(_('MeInvoice: Token return emtpy.'))
        expiry = datetime.now() + timedelta(days=13)

        self.sudo().write({
            'access_token': token,
            'token_expiry': expiry,
        })
        _logger.info('MeInvoice: Token refreshed, expires at %s', expiry)
        return token

    def get_valid_token(self):
        """
        Entry point to get valid token.
        Logic: check cache -> if still valid use -> if expiry fetch_new
        returns: str: token_valid
        Usage: config = self.env['meinvoice.config'].get_active_config()
               token = self.get_valid_token()
        """
        if self._is_token_valid():
            _logger.debug('MeInvoice: Using cached token')
            return self.access_token
        return self._fetch_new_token()

    def action_refresh_token(self):
        self._fetch_new_token()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'Message': _('Token đã được refresh. Hết hạn: %s') % self.token_expiry,
                'type': 'success',
            },
        }

    def action_test_connection(self):
        token = self.get_valid_token()
        url = f'{self._get_base_url()}/invoice/templates'
        try:
            response = requests.get(
                url,
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                },
                params={'invoiceWithCode': 'true', 'ticket': 'false'},
                timeout=30,
            )
            data = response.json()
        except Exception as e:
            raise UserError(_('MeInvoice: Test connection failed: %s') % str(e))
        if data.get('Success'):
            templates = data.get('Data',[])
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Tìm thấy %d mẫu hóa đn.') % len(templates),
                    'type': 'success',
                },
            }
        raise UserError(_('MeInvoice: Kết nối thất bại: %s') % data.get('ErrorCode'))

    @api.model
    def get_active_config(self):
        config = self.search([
            ('company_id','=', self.env.company.id),
            ('active','=', True)
        ],limit=1)
        if not config:
            raise UsserError(_('Chưa có cấu hình MeInovice.'))
        return config

    @api.model
    def cron_refresh_token(self):
        configs = self.search([('active','=', True)])
        for config in configs:
            try:
                if not config._is_token_valid():
                    config._fetch_new_token()
                    _logger.info('MeInvoice cron: Reffreshed token for config %s', config.name)
            except Exception as e:
                _logger.error('MeInvoice cron: Failed to refresh token for config %s:', config.name, str(e))
