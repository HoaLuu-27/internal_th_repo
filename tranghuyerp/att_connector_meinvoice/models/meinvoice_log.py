from odoo import models, fields, api, _
import logging
import json

_logger = logging.getLogger(__name__)



class MeInvoiceLog(models.Model):
    _name = 'meinvoice.log'
    _description = 'MISA MeInvoice Log'
    _order = 'create_date desc'
    _rec_name = 'action'

    #-- related with hoa don ---
    move_id = fields.Many2one('account.move','Hóa đơn', ondelete='set null', index=True)
    ref_id = fields.Char('Mã tra cứu',help='Transaction ID MeInvoice trả về sau khi phát hành', index=True)
    transaction_id = fields.Char(  # ← THÊM
        string='Transaction ID',
        help='Mã tra cứu MeInvoice trả về sau khi phát hành',
        index=True,
    )
    #-- Request info ---
    action = fields.Selection(
        selection = [
            ('get_token', 'Lấy Token'),
            ('get_templates', 'Lấy mẫu HĐ'),
            ('preview', 'Xem trước HĐ'),
            ('issue', 'Phát hành HĐ'),
            ('get_status', 'Lấy trạng thái'),
            ('download', 'Tải HĐ'),
            ('send_email', 'Gửi email'),
            ('adjust', 'Điều chỉnh/Thay thế'),
            ('sign_usb', 'Ký số USB (HSM local)'),
        ],string='Thao tác', required=True,index=True,
    )
    endpoint = fields.Char('Endpoint')
    http_method = fields.Char('HTTP method', default='POST')

    #-- request detail ---
    request_body = fields.Text('Request Body',help='JSON gửi đi (sensitive data được mask)')
    response_body = fields.Text('Response Body', help='JSON nhận về từ MeInvoice')
    http_status_code = fields.Integer('HTTP status Code')

    #-- Result ---
    success = fields.Boolean(string='Thành công', default=False, index=True)
    error_code = fields.Char(string='Error Code')
    error_message = fields.Text(string='Mô tả lỗi')
    duration_ms = fields.Integer(
        string='Thời gian xử lý (ms)',
        help='Thời gian từ lúc gửi request đến khi nhận response',
    )
    #-- action by ---
    user_id = fields.Many2one('res.users', 'Người thực hiện',default= lambda self:self.env.user)
    create_date = fields.Datetime('Thời gian', readonly=True)

    @api.model
    def log_api_call(
            self,
            action,
            endpoint,
            request_body=None,
            response_body=None,
            http_status_code=None,
            success=False,
            error_code=None,
            error_message=None,
            duration_ms=None,
            move_id=None,
            ref_id=None,
            transaction_id=None,
    ):
        if isinstance(request_body, dict):
            #data = {'name': 'Nguyễn Xuân Hoàng', 'city': 'Hà Nội'}
            # ensure_ascii=True (default) → escape tất cả ký tự non-ASCII
            #json.dumps(data)
            # '{"name": "Nguy\\u1ec5n Xu\\u00e2n Ho\\u00e0ng", "city": "H\\u00e0 N\\u1ed9i"}'
            # ensure_ascii=False → giữ nguyên Unicode, đọc được
            #json.dumps(data, ensure_ascii=False)
            # '{"name": "Nguyễn Xuân Hoàng", "city": "Hà Nội"}'
            request_body = json.dumps(request_body, ensure_ascii=False, indent=2)
        if isinstance(response_body, dict):
            response_body = json.dumps(response_body, ensure_ascii=False, indent=2)

        vals = {
            'action': action,
            'endpoint': endpoint,
            'request_body': request_body,
            'response_body': response_body,
            'http_status_code': http_status_code or 0,
            'success': success,
            'error_code': error_code,
            'error_message': error_message,
            'duration_ms': duration_ms or 0,
            'user_id': self.env.user.id,
        }
        if move_id:
            vals['move_id'] = move_id
        if ref_id:
            vals['ref_id']= ref_id
        if transaction_id:
            vals['transaction_id'] = transaction_id

        return self.sudo().create(vals)
