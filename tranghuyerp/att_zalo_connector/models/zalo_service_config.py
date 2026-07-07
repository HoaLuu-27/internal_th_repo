import secrets
import logging
from urllib.parse import urlencode
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ZaloServiceConfig(models.Model):
    """
    Model cấu hình trung tâm cho ZaLo Services.
    Ý tưởng:
    - Không tách quá nhiều model auth/config/request như module cũ.
    - Một config có thể đại diện cho OA / ZNS / Mini App.
    - Hiện tại tập trung service_type = 'oa'.
    - Sau này thêm ZNS và Mini App không phải đập lại kiến trúc.
    """
    _name = 'att.zalo.service.config'
    _description = 'Zalo Service Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char('Tên cấu hình', required=True, default='[ZALO] Trang huy OA', tracking=True, help='Tên cấu hình để phân biệt các services zalo.')
    active = fields.Boolean('Hoạt động', default=True, tracking=True)
    service_type = fields.Selection([
        ('oa', 'Official Account'),
        ('zns', 'Zalo Notification Service (ZNS)'),
        ('mini_app', 'Mini App'),
    ], string='Loại dịch vụ',default='', required=True, tracking=True, help='Chọn loại dịch vụ Zalo mà cấu hình này đại diện.')
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('verified','Đã xác thực url'),
        ('connected','Đã kết nối'),
        ('error','Lỗi kết nối'),
    ], string='Trạng thái', default='draft', required=True, tracking=True, help='Trạng thái kết nối của cấu hình Zalo Service.',
    )

    #App / OA credentials
    app_id = fields.Char('App ID', tracking=True, help="ID ứng dụng trên Zalo Developer Console.")
    app_secret = fields.Char('App Secret', groups="base.group_system", help='App secret dùng cho OAuth và appsecret_proof, khi gọi cho outbound')
    oa_id = fields.Char('OA ID', tracking=True, help='Zalo Official Account ID, dùng cho OA message.')
    oa_secret_key = fields.Char('OA secret key',groups='base.group_system', help='OA secret key dùng để verify chữ ký webhook X-Zalo-Signature .')

    #webhook
    webhook_url = fields.Char('Webhook URL', compute='_compute_webhook_url', store=False, readonly=True, help='URL đăng ký trên zalo developer console để nhận webhook .')
    verify_url_prefix = fields.Char('Verify URL Prefix', compute='_compute_verify_url_prefix', store=False, readonly=True, help='URL prefix dùng để verify ownership với Zalo.')
    meta_tag = fields.Text('Meta Tag Verification', readonly=True, help='Meta tag Zalo yêu cầu khi verify URL/domain . Hệ thống tự sinh khi Zalo gọi verifier file.')
    register_mode = fields.Boolean('Đang verify URL/Domain', default=True, help='Bật khi cần zalo gọi verifier file. Sau khi verify thành công có thể tắt.')

    #Oauth token
    oauth_state = fields.Char('Oauth State', readonly=True, copy=False, help='Chuỗi random chống callback giả trong Oauth.')
    authorization_code = fields.Char('Authorization Code', readonly=True, copy=False, help='Code tạm thời Zalo redirect về. Chỉ dùng một lần để đổi token.')
    access_token = fields.Char('Access Token', readonly=True, copy=False, groups='base.group_system', help='Access token dùng để gọi API outbound. Hệ thống tự refresh khi hết hạn.')
    refresh_token = fields.Char('Refresh Token',groups='base.group_system', copy=False, help='Token dùng để làm mới access token')
    token_expire_at = fields.Datetime('Access Token hết hạn lúc', copy=False, help='Thời điểm access token hết hạn.')
    is_connected = fields.Boolean('Đã kết nối',compute='_compute_is_connected', store=True, help='True khi đã có access token và refresh token.')

    #Debug
    debug_log = fields.Boolean('Bật debug log', default=True, help='Nếu bật hệ thống sẽ lưu raw requests/responses để deubg')
    last_error = fields.Text('Lỗi gần nhất', readonly=True, copy=False, help='Lưu lỗi gần nhất để check nhanh.')

    #computes

    @api.depends()
    def _compute_webhook_url(self):
        """
        Tự sinh webhook URL theo web.base.url.

        URL này dùng để đăng ký trong Zalo Developer Console / Webhook.
        """
        base_url = self.env['ir.config_parameter'].sudo().get_param("web.base.url", "")
        base_url = base_url.rstrip("/")

        for rec in self:
            rec.webhook_url = f"{base_url}/zalo_services/wh/"

    @api.depends()
    def _compute_verify_url_prefix(self):
        """
        Tự sinh URL Prefix để verify ownership với Zalo.

        Zalo sẽ gọi:
        /zalo_services/oa/verify/zalo_verifierxxxx.html đỏio chỉ dùng 1 url cho cả verify và webhook
        """
        base_url = self.env['ir.config_parameter'].sudo().get_param("web.base.url", "")
        base_url = base_url.rstrip("/")

        for rec in self:
            rec.verify_url_prefix = f"{base_url}/zalo_services/wh"

    @api.depends('access_token', 'refresh_token')
    def _compute_is_connected(self):
        """
        Xác định config đã kết nối OAuth hay chưa.
        """
        for rec in self:
            rec.is_connected = bool(rec.access_token and rec.refresh_token)

    def _get_oauth_callback_url(self):
        """
        Trả về URL callback để Zalo redirect về sau khi authorize OA.
        """
        base_url = self.env['ir.config_parameter'].sudo().get_param("web.base.url", "")
        base_url = base_url.rstrip("/")
        return f"{base_url}/zalo_services/oa/oauth/callback"

    # @api.model
    # def _get_active_oa_config(self):
    #     """
    #     Lấy cấu hình OA active để controller xử lý verify/webhook/oauth.
    #     """
    #     return self.sudo().search([
    #         ('active', '=', True),
    #         ('service_type', '=', 'oa')
    #     ], limit=1)


    #button
    def action_enable_register_mode(self):
        """
        Bat che do verify URL/Domain.
        Khi bat mode nay:
        - Controller se tra ve meta tag cho verifier file.
        - Dung trong buoc dang ky URL prefix tren Zalo Developer Console.
        """
        self.ensure_one()
        self.register_mode = True
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Zalo Verify"),
                "message": _(
                    "Đã bật chế độ verify URL/Domain. Hãy đăng ký Webhook URL Prefix trên Zalo Developer Console."),                "type": "success",
                "sticky": False,
            }
        }


    def action_authorize_oa(self):
        """
        Mo link zalo OAuth de admin OA cap quyen cho app.

        Flow:
        1. User bấm nút trên Odoo.
        2. Odoo sinh state.
        3. Redirect sang Zalo OAuth.
        4. Zalo redirect về callback với ?code=...&state=...
        5. Controller tự đổi code lấy token.
        Lưu ý:
        - Endpoint OAuth có thể thay đổi theo Zalo version.
        - Vì vậy URL để thành constant trong service/api để dễ chỉnh.
        """
        self.ensure_one()
        if not self.app_id:
            raise UserError(_("Bạn cần nhập App ID trước."))
        state = secrets.token_urlsafe(32)
        self.oauth_state = state
        callback_url = self._get_oauth_callback_url()
        params = {
            "app_id": self.app_id,
            "redirect_uri": callback_url,
            "state": state,
        }
        autorize_url = "https://oauth.zaloapp.com/v4/oa/permission?" + urlencode(params)
        return {
            "type": "ir.actions.act_url",
            "url": autorize_url,
            "target": "self",
        }


    def action_refresh_token(self):
        """
        Lam moi access_token.
        """
        self.ensure_one()
        self.env["att.zalo.oa.api"].sudo().refresh_access_token(self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _('Zalo Token'),
                "message": _("Đã refresh access token"),
                "type": "success",
                "sticky":False,
            }
        }


    def action_test_connection(self):
        """
        Test ket noi co ban.

        batch dau chua bat buoc goi get OA profile that.
        Sau khi chot endpoint, ham nay se goi API get OA info.
        """
        self.ensure_one()
        if not self.access_token:
            raise UserError(_("Chua co access token. Hay ket noi OA truoc."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _('Zalo'),
                "message": _("Cau hinh co access token. Co the tiep tuc test gui/nhan tin."),
                "type": "success",
                "sticky": False,
            }
        }

    #helpers
    def _get_active_oa_config(self):
        """
        Lay config OA active
        Controller dung ham nay de tim config xu ly webhook.
        """
        return self.sudo().search([
            ('active','=',True),
            ('service_type','=','oa')
        ], limit=1)


    def _set_error(self, error):
        """
        Ghi loi gan nhat len config de check nhanh
        """
        self.sudo().write({
            "state": "error",
            "last_error": str(error),
        })
        _logger.error("[ZALO CONFIG] %s", error)
