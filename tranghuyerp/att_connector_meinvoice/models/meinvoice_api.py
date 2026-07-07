import uuid
import time
import requests
import logging
from odoo import models, api, _
from odoo.exceptions import ValidationError, UserError


_logger = logging.getLogger(__name__)


class MeInvoiceAPI(models.Model):
    _name = 'meinvoice.api'
    _description = 'MISA MeInvoice API Service'

    #-- internal helpers ---
    def _get_headers(self, token):
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        }
    def _call(self, method, url, token=None, json_body=None, params=None,timeout=30):
        headers = self._get_headers(token) if token else {'Content-Type': 'application/json'}
        start = time.time()
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
            res.raise_for_status()
            return res.json(), duration_ms
        except requests.exceptions.Timeout:
            raise UserError(_('MeInvoice: Request timed out after %s seconds.') % timeout)
        except requests.exceptions.ConnectionError:
            raise UserError(_('MeInvoice: Connection refused after %s seconds.') % timeout)
        except requests.exceptions.HTTPError as e:
            duration_ms = int((time.time() - start) * 1000)
            _logger.error('MeInvoice: HTTP error: %s', e)
            raise UserError(_('MeInvoice: HTTP error: %s') % e)

    def _handle_response(self, data, context_msg=''):
        success = data.get('success') or data.get('Success')
        if not success:
            error_code = data.get('errorCode') or data.get('ErrorCode','UNKNOWN')
            desc = data.get('descriptionErrorCode') or data.get('ErrorCode', '')
            _logger.error('MeInvoice API error [%s]: %s - %s', context_msg, error_code, desc)
            raise UserError(
                _('MeInvoice lỗi [%s]: %s - %s') % (context_msg, error_code, desc)
            )
        return data.get('data') or data.get('Data')

    #-- public API methods ---

    @api.model
    def get_invoice_template(self, config, invoice_with_code=True):
        token = config.get_valid_token()
        url = f'{config.base_url}/invoice/templates'
        params = {
            'invoiceWithCode': str(invoice_with_code).lower(),
            'ticket':'false',
        }
        data, duration = self._call('GET',url, token=token, params=params)
        self.env['meinvoice.log'].log_api_call(
            action='get_templates',
            endpoint=url,
            response_body=data,
            http_status=200,
            success=data.get('Success', False),
            duration_ms=duration,
        )
        return self._handle_response(data, 'get_templates')

    @api.model
    def preview_invoice(self, config, invoice_data):
        token = config.get_valid_token()
        url = f'{config.base_url}/invoice/unpublishview'
        data, duration = self._call('POST', url, token=token, json_body=invoice_data)
        self.env['meinvoice.log'].log_api_call(
            action='preview',
            endpoint=url,
            response_boddy=data,
            http_status=200,
            success=data.get('Success', False),
            ref_id=invoice_data.get('refId').get('RefID'),
            duration_ms=duration,
        )
        return self._handle_response(data, 'preview')

    def issue_invoice(self, config, invoice_data, move_id=None):
        token = config.get_valid_token()
        url = f'{config.base_url}/invoice'
        payload = {
            'SignType': int(config.sign_type),
            'InvoiceData': [invoice_data], #API take list
            'PublishInvoiceData': None,   #used only for sign_type=1 USB Token
        }
        data, duration = self._call('POST', url, token=token, json_body=payload)
        ref_id = invoice_data.get('RefID')
        success = data.get('success', False)

        #with HSM(signType=2). the result in publishInvoiceResult
        publish_results = data.get('PublishInvoiceResult') or []
        result = publish_results[0] if publish_results else {}

        #check error in result level
        result_error = result.get('ErrorCode') if result else None
        if result_error:
            success = False

        self.env['meinvoice.log'].log_api_call(
            action='issue',
            endpoint=url,
            request_body=payload,
            response_body=data,
            http_status=200,
            success=success,
            error_code=result_error,
            ref_id=ref_id,
            transaction_id=result.get('TransactionID') if result else None,
            move_id=move_id,
            duration_ms=duration,
        )
        self._handle_response(data, 'issue_invoice')

        if result_error:
            raise UserError(
                _('MeInvoice phát hành thất bại: %s') % result_error
            )
        return result
    @api.model
    def get_invoice_status(self, config, transaction_ids, invoice_with_code=True):
        token = config.get_valid_token()
        url = f'{config.base_url}/invoice/status'
        params = {
            'invoiceWithCode': str(invoice_with_code).lower(),
            'invoiceCalcu': 'false',
            'inputType': '1', # 1 = theo transactionID
        }
        data, duration = self._call('POST', url, token=token, json_body=transaction_ids, params=params)
        self.env['meinvoice.log'].log_api_call(
            action='get_status',
            endpoint=url,
            request_body=transaction_ids,
            response_body=data,
            http_status=200,
            success=data.get('success', False),
            duration_ms=duration,
        )
        return self._handle_response(data, 'get_status')

    @api.model
    def download_invoice(self, config, transaction_ids, download_type='pdf', invoice_with_code=True):
        token = config.get_valid_token()
        url = f'{config.base_url}/invoice/download'
        params = {
            'invoiceWithCode': str(invoice_with_code).lower(),
            'invoiceCalcu': 'false',
            'downloadDataType': download_type,
        }
        data, duration = self._call('POST', url, token=token,json_body=transaction_ids, params=params)

        self.env['meinvoice.log'].log_api_call(
            action='download',
            endpoint=url,
            request_body=transaction_ids,
            response_body={'success': data.get('success')},  # Không log base64 vào DB
            http_status=200,
            success=data.get('success', False),
            duration_ms=duration,
        )
        return self._handle_response(data, 'download')


    @api.model
    def send_email(self, config, transaction_id, receiver_email, receiver_name='', invoice_with_code=True):
        token = config.get_valid_token()
        url = f'{config.base_url}/invoice/sendemail'
        payload = {
            'SendEmailDatas': [{
                'TransactionID': transaction_id,
                'ReceiverName': receiver_name,
                'ReceiverEmail': receiver_email,
                'CCEmail':'',
                'ReplyEmail':'',
            }],
            'IsInvoiceCode': invoice_with_code,
            'IsInvoiceCalculatingMachine': False,
        }
        data, duration = self._call('POST', url, token=token, json_body=payload)
        self.env['meinvoice.log'].log_api_call(
            action='send_email',
            endpoint=url,
            request_body=payload,
            response_body=data,
            http_status=200,
            success=data.get('success', False),
            transaction_id=transaction_id,
            duration_ms=duration,
        )
        return self._handle_response(data, 'send_email')

    @api.model
    def create_invoice_xml(self, config, invoice_data, move_id=None):
        raise UserError(_(
            'Chức năng ký số USB Token chưa được kích hoạt. '
            'Liên hệ ATT Systems để cấu hình.'
        ))
    @api.model
    def publish_signed_xml(self,config, publish_invoice_data, move_id=None):
        raise UserError(_(
            'Chức năng phát hành XML đã ký chưa được kích hoạt. '
            'Liên hệ ATT Systems để cấu hình.'
        ))