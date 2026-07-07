import time
import requests
import logging
import json
from odoo import models, fields, api, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)

class MeInvoiceAPI(models.AbstractModel):
    """
    Service class — toàn bộ HTTP call đến MeInvoice đi qua đây.
    AbstractModel: không tạo table DB.
    Mọi request đều được log vào meinvoice.request.log.

    Gọi từ nơi khác:
        api = self.env['meinvoice.api']
        api.fetch_token(config)
        api.insert_invoice(config, data)
    """
    _name = 'meinvoice.api'
    _description = 'Meinvoice API Service'

    # -- core HTTP ---
    def _get_headers(self, token, tax_code):
        """headers chuan cho API can auth"""
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
            'taxcode': tax_code,
        }

    def _call(self, method, url, token=None, tax_code=None, json_body=None, params=None, timeout=30):
        """
        Core HTTP caller — mọi API call đi qua đây.
        Tự động log vào meinvoice.request.log sau mỗi call.

        Returns:
            tuple: (response_dict, duration_ms)
        Raises:
            UserError: nếu network error hoặc HTTP error
        """
        headers = self._get_headers(token, tax_code) if token else {
            'Content-Type': 'application/json',
        }

        start = time.time()
        res = None
        http_status =None
        error_msg = None
        success = False
        duration_ms = 0

        try:
            res = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=timeout,
            )
            duration_ms = int((time.time() - start) * 1000)
            http_status = res.status_code
            res.raise_for_status()
            try:
                res_data = res.json()
            except Exception:
                res_data = {'raw': res.text[:1000]}
            success = res_data.get('success', False)
            return res_data, duration_ms
        except requests.exceptions.Timeout:
            duration_ms = int((time.time() - start)*1000)
            error_msg = f'Timeout sau {timeout}s'
            raise UserError(_('[MeInvoiceAPI]: Timeout sau %s giây') % timeout)
        except requests.exceptions.ConnectionError as e:
            duration_ms = int((time.time() - start)*1000)
            error_msg = str(e)
            raise UserError(_('[MeInvoiceAPI]: Không kết nối được với server.') )
        except requests.exceptions.HTTPError as e:
            duration_ms = int((time.time() - start)*1000)
            error_msg = str(e)
            try:
                res_data = res.json()
            except Exception:
                res_data = {'raw:': res.text[:1000]}
            _logger.error('[MeInvoiceAPI] HTTP error: %s', e)
            raise UserError(_('[MeInvoiceAPI] HTTP error: %s') % e)
        finally:
            try:
                self.env['meinvoice.request.log'].log(
                    endpoint=url,
                    method=method,
                    request_headers=headers,
                    request_body=json_body,
                    response_status=http_status,
                    response_body=res_data,
                    success=success,
                    duration_ms=duration_ms,
                    error_msg=error_msg,
                )
            except Exception as log_err:
                _logger.error('[MeInvoiceAPI]: log failed: %s', log_err)


    def _handle_response(self, data, context=''):
        """
        Kiểm tra response success theo chuẩn MeInvoice V2.
        Raise UserError nếu fail.
        Returns data['data'] nếu success.
        """
        # print(f'start handle response')
        if not data.get('success'):
            error = data.get('error') or data.get('errorCode', 'UNKNOWN')
            # print(f'error: {error}')
            _logger.error('[MeInvoiceAPI]: [%s] error: %s', context, error)
            raise UserError(_('[MeInvoiceAPI]: [%s] error: %s') % (context, error))
        # print(f'data: {data}')
        return data.get('data')

    #-- Auth ----
    @api.model
    def fetch_token(self, config):
        """
        Lấy Access Token từ MeInvoice.
        Sandbox V2: data là string JSON {"access_token":"..."}
        Production V1: data là string token trực tiếp

        Returns:
            str: access_token
        """
        url = config._build_url('endpoint_token')
        payload = {
            'taxcode': config.tax_code,
            'username': config.username,
            'password': config.password,
        }
        if config.app_id:
            payload['app_id'] = config.app_id
        data, duration_ms = self._call('POST', url, json_body=payload)
        if not data.get('success'):
            raise UserError(_('[MeInvoiceAPI]: Lấy token thất bại %s') % data.get('error', 'UNKNOWN'))
        #parse token - handle v1 string / v2 string JSON / v2 dict
        token_data = data.get('data') or data.get('Data')
        if isinstance(token_data, str):
            try:
                token_data = json.loads(token_data)
            except Exception:
                #String truc tiep tu V1
                return token_data if token_data else None
        if isinstance(token_data, dict):
            return token_data.get('access_token')
        raise UserError(_('[MeInvoiceAPI]: Token trả về {}. Response: %s') % str(data))

    #--templates ---
    @api.model
    def get_templates(self, config, invoice_with_code=True):
        """
        Lấy danh sách mẫu hóa đơn.
        V2: POST + body credentials, không cần token.

        Returns:
            list: danh sách template objects
        """
        url = config._build_url('endpoint_templates')
        payload = {
            'taxcode': config.tax_code,
            'username': config.username,
            'password': config.password,
        }
        if config.app_id:
            payload['app_id'] = config.app_id
        data, _ = self._call('POST', url, json_body=payload, params={'invoice_with_code': str(invoice_with_code).lower()})
        result = self._handle_response(data, 'get_templates')
        if isinstance(result, str):
            result = json.loads(result)
        return result or []

    # -- Invoice CRUD ---

    @api.model
    def insert_invoice(self, config, invoice_data, move_id=None):
        """
        Tạo hóa đơn nháp trên MeInvoice (chưa phát hành).
        V2: POST /webapp/insert — body là ARRAY.

        Args:
           config: meinvoice.config record
           invoice_data: dict InvoiceData V2 format
           move_id: int account.move ID để gắn log

        Returns:
           dict: response data
        """
        token = config.get_valid_token()
        url = config._build_url('endpoint_insert')
        data, duration_ms = self._call('POST', url, token=token,tax_code=config.tax_code, json_body=[invoice_data], params={'invoiceWithCode':'true'})
        # V2: check lỗi ở cả top-level và error list
        if not data.get('success'):
            raise UserError(_('[MeInvoiceAPI]: Tạo hóa đơn thất bại %s') % data.get('error', 'UNKNOWN'))
        error_list = data.get('error')
        if error_list and error_list != '[]' and error_list != '':
            try:
                errors = json.loads(error_list) if isinstance(error_list, str) else error_list
                if errors:
                    raise UserError(_('[MeInvoiceAPI]: Lỗi hóa đơn %s') % errors[0].get('ErrorMessage','UNKNOWN'))
            except UserError:
                raise
            except Exception:
                pass
        return data

    @api.model
    def preview_invoice(self, config, invoice_data, move_id=None):
        """
        Xem trước hóa đơn bằng JSON data.
        V2: POST /webapp/preview → base64 PDF.

        Returns:
            str: base64 encoded PDF
        """
        token = config.get_valid_token()
        url = config._build_url('endpoint_preview')
        data, _ = self._call('POST', token=token, tax_code=config.tax_code, json_body=invoice_data, params={'invoiceWithCode':'true'})
        return self._handle_response(data, 'preview')

    @api.model
    def view_by_refid(self, config, ref_id, move_id=None):
        """
        Xem hóa đơn đã tạo theo RefID.
        V2: GET /webapp/viewrefid → base64 PDF.

        Returns:
            str: base64 encoded PDF
        """
        token = config.get_valid_token()
        url = config._build_url('endpoint_viewrefid')

        data, _ = self._call('GET', url, token=token, tax_code=config.tax_code, params={'invoiceWithCode':'true', 'refid':ref_id})
        return self._handle_response(data, 'view_by_refid')

    @api.model
    def get_invoice_list(self, config, ref_ids, invoice_with_code=True):
        """
        Lấy trạng thái hóa đơn theo danh sách RefID.
        V2: POST /webapp/getlist — body là array RefID.
        Tối đa 50 RefID/call.

        Returns:
            list: danh sách InvoiceData với trạng thái
        """
        token = config.get_valid_token()
        url = config._build_url('endpoint_getlist')
        data, _ = self._call('POST', url, token=token, tax_code=config.tax_code, json_body=ref_ids, params={'invoiceWithCode': str(invoice_with_code).lower()})
        result = self._handle_response(data, 'get_invoice_list')
        if isinstance(result, str):
            result = json.loads(result)
        return result or []

    #get list invoice
    @api.model
    def get_invoice_paging(self, config, from_date, to_date,
                           start=0, length=100, invoice_with_code=True):
        """
        Lấy danh sách HĐ theo khoảng thời gian — phân trang.
        V2: POST /webapp/paging.
        Dùng cho cron fetch về, không cần biết RefID trước.
        """
        token = config.get_valid_token()
        url = config._build_url('endpoint_paging')

        data, _ = self._call(
            'POST', url,
            token=token,
            tax_code=config.tax_code,
            json_body={
                'Start': start,
                'Length': length,
                'Sort': 'InvDate',
                'FromDate': from_date,
                'ToDate': to_date,
            },
            params={'invoiceWithCode': str(invoice_with_code).lower()},
        )

        result = self._handle_response(data, 'get_invoice_paging')
        if isinstance(result, str):
            result = json.loads(result)
        return result or []


    @api.model
    def delete_invoice(self, config, ref_id, move_id=None):
        """
        Xóa hóa đơn nháp chưa phát hành.
        V2: DELETE /webapp/delete?refid=xxx.
        """
        token = config.get_valid_token()
        url = config._build_url('endpoint_delete')
        data, _ = self._call('DELETE', url, token=token, tax_code=config.tax_code, params={'invoiceWithCode': 'true','refid':ref_id})
        return self._handle_response(data, 'delete_invoice')

    #-- V1 HSM ---

    @api.model
    def publish_invoice(self, config, invoice_data, move_id=None):
        """
        Phát hành hóa đơn — SignType=2 HSM SoftDream.
        Production V1: POST /invoice → ký số + phát hành luôn.

        Returns:
            dict: publishInvoiceResult[0] chứa InvNo, TransactionID
        """
        token = config.get_valid_token()
        url = config._build_url('endpoint_publish')
        payload = {
            'SignType': 2,
            'InvoiceData': [invoice_data],
            'PublishInvoiceData': None
        }
        data, _ = self._call('POST', url, token=token, tax_code=config.tax_code, json_body=payload)
        if not data.get('success'):
            error = data.get('errorCode') or data.get('descriptionErrorCode', 'UNKNOWN')
            raise UserError(_('MeInvoice phát hành thất bại: %s') % error)

        results = data.get('publishInvoiceResult') or []
        result = results[0] if results else {}

        if result.get('ErrorCode'):
            raise UserError(
                _('MeInvoice lỗi phát hành: %s') % result.get('ErrorCode')
            )

        return result

    @api.model
    def view_published_invoice(self, config, transaction_id, move_id=None):
        """
        Xem hóa đơn đã phát hành (có chữ ký số).
        Production V1: GET /invoice/publishview.

        Returns:
            str: base64 PDF
        """
        token = config.get_valid_token()
        url = config._build_url('endpoint_publishview')

        data, _ = self._call(
            'GET', url,
            token=token,
            tax_code=config.tax_code,
            params={'transactionID': transaction_id},
        )

        return self._handle_response(data, 'view_published')

    @api.model
    def send_email(self, config, transaction_id,
                   receiver_email, receiver_name='', move_id=None):
        """
        Gửi email hóa đơn đã phát hành cho khách hàng.
        Production V1: POST /invoice/sendemail.
        Chỉ hoạt động trên Production.
        """
        token = config.get_valid_token()
        url = config._build_url('endpoint_sendemail')

        payload = {
            'SendEmailDatas': [{
                'TransactionID': transaction_id,
                'ReceiverName': receiver_name,
                'ReceiverEmail': receiver_email,
                'CCEmail': '',
                'ReplyEmail': '',
            }],
            'IsInvoiceCode': True,
            'IsInvoiceCalculatingMachine': False,
        }

        data, _ = self._call(
            'POST', url,
            token=token,
            tax_code=config.tax_code,
            json_body=payload,
        )

        return self._handle_response(data, 'send_email')

    # ── USB Token placeholder ─────────────────────────────────

    @api.model
    def create_invoice_xml(self, config, invoice_data, move_id=None):
        """[SignType=1] Placeholder — chưa kích hoạt."""
        raise UserError(_(
            'Ký số USB Token chưa được kích hoạt. '
            'Liên hệ ATT Systems để cấu hình.'
        ))

    @api.model
    def publish_signed_xml(self, config, publish_data, move_id=None):
        """[SignType=1] Placeholder — chưa kích hoạt."""
        raise UserError(_(
            'Phát hành XML đã ký chưa được kích hoạt. '
            'Liên hệ ATT Systems để cấu hình.'
        ))