import json
from odoo import fields, models


class ZaloRequestLog(models.Model):
    """
    Model lưu raw request/response của ZaLo Services.
    Mục tiêu:
    - Debug nhanh.
    - Biết request là inbound hay outbound.
    - Biết request có phải webhook hay không.
    - Xem body/header/status/error ngay trong Odoo.
    """
    _name = 'att.zalo.request.log'
    _description = "Zalo Raw Request Log"
    _order = "id desc"

    name = fields.Char('Tên Log', required=True, default="Zalo Request")
    config_id = fields.Many2one('att.zalo.service.config', 'Cấu hình', ondelete='set null',help='COnfig Zalo liên quan tới request này.')
    service_type = fields.Selection(
        selection=[
            ("oa", "Official Account"),
            ("zns","ZNS"),
            ("mini_app","Mini App"),
        ], string="Loại dịch vụ", default="oa", index=True, help='Dùng để lọc Log OA/ZNS/Mini App.'
    )
    direction = fields.Selection(
        selection=[
            ("inbound","Nhận về"),
            ("outbound","Gửi đi"),
        ],string="Chiều request", required=True, index=True, help='Inbound: Zalo gọi vào odoo. Outbound: Odoo gọi ra Zalo.'
    )
    is_webhook = fields.Boolean('Là Webhook', default=False, index=True, help='Đánh dấu request inbound từ webhook Zalo.')
    endpoint = fields.Char("Endpoint", help='URL hoặc path API.')
    http_method = fields.Char("HTTP Method", help="GET/POST/PUT/DELETE")
    state = fields.Selection(
        selection=[
            ("new","New"),
            ("done","Done"),
            ("error","Error"),
            ("ignored","Ignored")
        ],string="Trạng thái", default="new", index=True, help="Trạng thái xử lý request."
    )
    request_headers = fields.Text("Request Headers", help="Raw headers dạng JSON/text.")
    request_body = fields.Text('Request Body', help='Raw body gửi đi hoặc nhận về.')
    response_code = fields.Integer('Response Code', help='HTTP status code.')
    response_headers = fields.Text('Response Headers', help="Raw headers JSON/text.")
    response_body = fields.Text('Response Body', help='Raw body nhận về từ Zalo.')
    error_message = fields.Text('Error Message', help='Mô tả lỗi nếu có.')
    duration_ms = fields.Integer('Thời gian xử lý (ms)', help='Thời gian từ lúc gửi request đến khi nhận response.')
    user_id = fields.Many2one('res.users', 'Người thực hiện', default=lambda self: self.env.user, help='Người thực hiện request.')
    create_date = fields.Datetime('Thời gian tạo', readonly=True, help='Thời gian log được tạo.')
    zalo_event_name = fields.Char('Zalo Event Name', index=True, help="tên event webhook. VD: user_send_text, user_received_message...")
    zalo_user_id = fields.Char('Zalo User ID', index=True, help='User ID của khách trên Zalo OA.')
    message_id = fields.Char('Zalo Message ID', index=True, help='Message ID từ Zalo nếu có.')


    def action_mark_done(self, response_code=False, response_body=False):
        """
        helper đánh dấu Log lỗi
        """
        vals = {"state":"done"}
        if response_code:
            vals["response_code"] = response_code
        if response_body:
            vals["response_body"] = self._json_dumps(response_body)
        self.write(vals)


    def action_mark_error(self, error):
        """
        Helper danh dau Log loi.
        """
        self.write({
            "state":"error",
            "error_message": str(error)
        })


    @staticmethod
    def _json_dumps(value):
        """
        Chuyen dict/list thanh JSON dep de doc trong Odoo.
        """
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            return str(value)

