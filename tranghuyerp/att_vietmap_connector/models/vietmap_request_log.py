import json
from odoo import fields, models


class VietmapRequestLog(models.Model):
    """Log raw request/response gọi VietMap — debug nhanh, và để đếm được
    thực tế có bao nhiêu lượt gọi/ngày (theo dõi tải hệ thống)."""
    _name = 'att.vietmap.request.log'
    _description = 'VietMap Raw Request Log'
    _order = 'id desc'

    name = fields.Char('Tên Log', required=True, default='VietMap Request')
    config_id = fields.Many2one('att.vietmap.config', 'Cấu hình', ondelete='set null')
    endpoint = fields.Char('Endpoint')
    full_url = fields.Char(
        'Full URL', help='URL đầy đủ ĐÃ gửi thật (kèm query string, apikey đã '
        'che ***) — dán thẳng lại vào Postman/browser (tự điền lại apikey) '
        'để tái hiện đúng y hệt request lỗi khi cần debug.')
    http_method = fields.Char('HTTP Method')
    query_text = fields.Char('Từ khoá tìm', index=True, help='Text user gõ (nếu là search_address).')
    ref_id = fields.Char('Ref ID', index=True, help='Ref ID VietMap (nếu là get_place_detail).')
    state = fields.Selection([
        ('new', 'New'),
        ('done', 'Done'),
        ('error', 'Error'),
    ], string='Trạng thái', default='new', index=True)
    request_body = fields.Text('Request Body')
    response_code = fields.Integer('Response Code')
    response_body = fields.Text('Response Body')
    error_message = fields.Text('Error Message')
    duration_ms = fields.Integer('Thời gian xử lý (ms)')
    user_id = fields.Many2one('res.users', 'Người thực hiện', default=lambda self: self.env.user)
    create_date = fields.Datetime('Thời gian tạo', readonly=True)

    def action_mark_done(self, response_code=False, response_body=False):
        vals = {'state': 'done'}
        if response_code:
            vals['response_code'] = response_code
        if response_body:
            vals['response_body'] = self._json_dumps(response_body)
        self.write(vals)

    def action_mark_error(self, error):
        self.write({'state': 'error', 'error_message': str(error)})

    @staticmethod
    def _json_dumps(value):
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            return str(value)