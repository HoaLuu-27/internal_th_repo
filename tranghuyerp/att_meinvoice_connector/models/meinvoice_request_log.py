from odoo import models, fields, api
import json
import logging

_logger = logging.getLogger(__name__)


class MeinvoiceRequestLog(models.Model):
    """
    Log TẤT CẢ raw HTTP request/response với MeInvoice.
    1 record = 1 HTTP call.
    Mọi request đều được log — kể cả lỗi.
    """
    _name = 'meinvoice.request.log'
    _description = 'MeInvoice Request Log'
    _order = 'create_date desc'
    _rec_name = 'endpoint'
    create_date = fields.Datetime('Thời gian', readonly=True)
    duration_ms = fields.Integer('Duration (ms)')
    http_method = fields.Char('Method', default='POST')
    endpoint = fields.Char('Endpoint', index=True)
    request_headers = fields.Text('Request Headers')
    request_body = fields.Text('Request Body')
    response_status = fields.Integer('HTTP Status')
    response_body = fields.Text('Response Body')
    success = fields.Boolean('Thành công', default=False, index=True)
    error_msg = fields.Text('Lỗi')

    @api.model
    def log(
        self,
        endpoint,
        method='POST',
        request_headers=None,
        request_body=None,
        response_status=None,
        response_body=None,
        success=False,
        duration_ms=None,
        error_msg=None,
    ):
        """
        Helper ghi log. Tự động mask password + token.
        Gọi từ meinvoice_api._call() sau mỗi HTTP request.

        Args:
            endpoint: URL endpoint
            method: HTTP method
            request_headers: dict headers gửi đi
            request_body: dict/list/str body gửi đi
            response_status: HTTP status code
            response_body: dict/list/str response nhận về
            success: True/False
            duration_ms: thời gian xử lý
            error_msg: mô tả lỗi nếu có
        """
        return self.sudo().create({
            'endpoint': endpoint,
            'http_method': method,
            'request_headers': self._serialize_headers(request_headers),
            'request_body': self._serialize_body(request_body, mask_keys=['password', 'Password']),
            'response_status': response_status or 0,
            'response_body': self._serialize_body(response_body),
            'success': success,
            'duration_ms': duration_ms or 0,
            'error_msg': error_msg,
        })

    def _serialize_headers(self, headers):
        """
        Serialize headers dict → string JSON.
        Mask Authorization — chỉ giữ prefix 'Bearer xxx...(masked)'.
        """
        if not headers:
            return None
        if not isinstance(headers, dict):
            return str(headers)
        h = {**headers}
        if 'Authorization' in h:
            val = h['Authorization']
            # Giữ 'Bearer ' + 10 ký tự đầu của token
            parts = val.split(' ', 1)
            if len(parts) == 2:
                h['Authorization'] = f'{parts[0]} {parts[1][:10]}...(masked)'
        return json.dumps(h, ensure_ascii=False, indent=2)

    def _serialize_body(self, body, mask_keys=None):
        """
        Serialize body → string JSON.
        Mask các key nhạy cảm (password...).
        Không log base64 data (quá lớn).
        """
        if body is None:
            return None

        if isinstance(body, (dict, list)):
            # Deep copy để không mutate original
            b = json.loads(json.dumps(body, default=str))
            if isinstance(b, dict) and mask_keys:
                for key in mask_keys:
                    if key in b:
                        b[key] = '***'
            return json.dumps(b, ensure_ascii=False, indent=2)

        return str(body)