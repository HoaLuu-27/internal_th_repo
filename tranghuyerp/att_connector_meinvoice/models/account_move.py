from odoo import models, fields, api, _
import uuid
import logging
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    meinvoice_state = fields.Selection(
        selection=[
            ('not_sent','Chưa gửi'),
            ('pending','Đang xử lý'),
            ('issued','Đã phát hành'),
            ('error','Lỗi'),
            ('cancelled','Đã hủy')
        ],string='Trạng thái MeInvoice',default='not_sent',copy=False,index=True,tracking=True
    )

    #-- MeInvoice fields  ---
    meinvoice_ref_id = fields.Char('RefID (MeInvoice)',copy=False, readonly=True, help='GUID dùng để check trùng với MeInvoice. Tự sinh khi gửi.',index=True)
    meinvoice_transaction_id = fields.Char('Mã tra cứu',copy=False, readonly=True, help='Mã tra cứu MeInvoice trả về sau khi phát hành thành công.',index=True)
    meinvoice_inv_no = fields.Char('Số hóa đơn điện tử', copy=False, readonly=True, help='Số hóa đơn chính thức do MeInvoice cấp.')
    meinvoice_inv_date = fields.Date('Ngày phát hành HĐ điện tử',copy=False, readonly=True)
    meinvoice_error_msg = fields.Text('Lỗi MeInvoice', copy=False, readonly=True)

    #computed: ---
    meinvoice_can_send = fields.Boolean('Có thể gửi MeInvoice',compute='_compute_meinvoice_can_send',help='True khi invoice đã posted và chưa được gửi/phát hành',)

    @api.depends('state','meinvoice_state','move_type')
    def _compute_meinvoice_can_send(self):
        for move in self:
            move.meinvoice_can_send = (
                move.state == 'posted' and move.move_type == 'out_invoice' and move.meinvoice_state in ('not_sent','error')
            )

    #-- data builder ---

    def _build_meinvoice_invoice_data(self, config):
        """
        map fields odoo - MeInvoice/

        Args:
            config: meinvoice.config record
        Returns:
            dict: InvoiceData object send to API
        Notes:

        """
        self.ensure_one()
        # create refID if not exist for first send.
        #retry - used old RefID to MeInvoice check dup
        if not self.meinvoice_ref_id:
            ref_id = str(uuid.uuid4())
            self.write({
                'meinvoice_ref_id': ref_id,
            })
        else:
            ref_id = self.meinvoice_ref_id
        partner = self.partner_id

        #-- build invoice lines ---
        invoice_lines = []
        line_number = 1
        for line in self.invoice_line_ids.filtered(lambda l: not l.display_type):
            #get vat rate name from tax
            vat_rate_name = self._get_vat_rate_name(line)
            #cal vat amount for this line
            vat_amount = line.price_total - line.price_subtotal

            invoice_lines.append({
                'ItemType': 1,                      # 1 = hàng hóa/dịch vụ thông thường
                'LineNumber': line_number,
                'SortOrder': line_number,
                'ItemCode': line.product_id.default_code or '',
                'ItemName': line.name or line.product_id.name or '',
                'UnitName': line.product_uom_id.name if line.product_uom_id else 'Cái',
                'Quantity': line.quantity,
                'UnitPrice': line.price_unit,
                'DiscountRate': line.discount or 0,
                'DiscountAmountOC': line.price_unit * line.quantity * (line.discount or 0) / 100,
                'AmountOC': line.price_subtotal,            # Sau discount, trước thuế
                'Amount': line.price_subtotal,
                'AmountWithoutVATOC': line.price_subtotal,
                'AmountWithoutVAT': line.price_subtotal,
                'VATRateName': vat_rate_name,
                'VATAmountOC': vat_amount,
                'VATAmount': vat_amount,
            })
            line_number += 1

            #-- build tax rate summary ---
            # Group by VAT rate to create TaxRateInfo
            tax_rate_info = self._build_tax_rate_info()

            # -- cal total ---
            total_without_vat = self.amount_untaxed
            total_vat = self.amount_tax
            total = self.amount_total

            #-- assemble InvoiceData ---
            invoice_data = {
                # Header
                'RefID': ref_id,
                'InvSeries': config.inv_series,
                'InvDate': self.invoice_date.strftime(
                    '%Y-%m-%d') if self.invoice_date else fields.Date.today().strftime('%Y-%m-%d'),
                'CurrencyCode': self.currency_id.name or 'VND',
                'ExchangeRate': 1.0 if self.currency_id.name == 'VND' else self.currency_id.rate,
                'PaymentMethodName': self._get_payment_method_name(),
                'IsInvoiceSummary': False,

                # Buyer info
                'BuyerCode': partner.ref or '',
                'BuyerLegalName': partner.name or '',
                'BuyerTaxCode': partner.vat or '',
                'BuyerAddress': self._get_partner_address(partner),
                'BuyerFullName': partner.name or '',
                'BuyerPhoneNumber': partner.phone or partner.mobile or '',
                'BuyerEmail': partner.email or '',
                'BuyerBankAccount': '',  # Nếu cần: thêm field vào partner
                'BuyerBankName': '',

                # Totals (OC = nguyên tệ, non-OC = quy đổi; nếu VND thì bằng nhau)
                'TotalSaleAmountOC': total_without_vat,
                'TotalSaleAmount': total_without_vat,
                'TotalDiscountAmountOC': 0,  # TODO: tính từ lines nếu có discount
                'TotalDiscountAmount': 0,
                'TotalAmountWithoutVATOC': total_without_vat,
                'TotalAmountWithoutVAT': total_without_vat,
                'TotalVATAmountOC': total_vat,
                'TotalVATAmount': total_vat,
                'TotalAmountOC': total,
                'TotalAmount': total,
                'TotalAmountInWords': self._amount_to_words(total),

                # Lines
                'OriginalInvoiceDetail': invoice_lines,
                'TaxRateInfo': tax_rate_info,
            }
            return invoice_data

    def _get_vat_rate_name(self, line):
        """
        Get vat rate name based MeInvoice standard from invoice_line/
        MeInvoice received: '0%', '5%', '8%', '10%', 'KCT', 'KKKNT'
        Args:
            line: account.move.line record
        Returns:
        str: VATRateName
        """
        taxes = line.tax_ids.filterd(lambda t: t.tax_group_id.name in ('VAT','Thuế GTGT'))
        if not taxes:
            return 'KCT' #khong chiu thue
        tax = taxes[0]
        amount = tax.amount
        if amount == 0:
            return '0%'
        elif amount == 5:
            return '5%'
        elif amount == 10:
            return '10%'
        elif amount == 8:
            return '8%'
        else:
            #fallback: dung thang amount
            return f'{int(amount)}%'

    def _build_tax_rate_info(self):
        """
        Tạo TaxRateInfo: tổng hợp tiền theo từng mức thuế suất.
        MeInvoice yêu cầu field này để hiển thị bảng tổng hợp thuế trên hóa đơn.

        Returns:
            list: [{'VATRateName': '10%', 'AmountWithoutVATOC': ..., 'VATAmountOC': ...}]
        """
        tax_groups = {}
        for line in self.invoice_line_ids.filtered(lambda l: not l.display_type):
            rate_name = self._get_vat_rate_name(line)
            vat_amount = line.price_total - line.price_subtotal
            if rate_name not in tax_groups:
                tax_groups[rate_name] = {'amount_without_vat':0, 'vat_amount':0}
            tax_groups[rate_name]['amount_without_vat'] += line.price_subtotal
            tax_groups[rate_name]['vat_amount'] += vat_amount

            return [
                {
                    'VATRateName': rate_name,
                    'AmountWithoutVATOC': vals['amount_without_vat'],
                    'VATAmountOC': vals['vat_amount'],
                }
                for rate_name, vals in tax_groups.items()
            ]

    def _get_payment_method_name(self):
        """
        Map payment term → tên hình thức thanh toán theo chuẩn MeInvoice.
        MeInvoice chấp nhận free text nhưng thường dùng: 'TM', 'CK', 'TM/CK'

        Returns:
            str: Tên hình thức thanh toán
        """
        # Mặc định TM/CK (tiền mặt hoặc chuyển khoản)
        return 'TM/CK'

    def _get_partner_address(self, partner):
        """
        Ghép địa chỉ đầy đủ của partner thành string.

        Args:
           partner: res.partner record

        Returns:
           str: Địa chỉ đầy đủ
        """
        parts = filter(None, [
            partner.street,
            partner.street2,
            partner.city,
            partner.state_id.name if partner.state_id else '',
            partner.country_id.name if partner.country_id else '',
        ])
        return ', '.join(parts)
    def _amount_to_words(self, amount):
        """
        Convert số tiền → chữ tiếng Việt.
        Odoo có sẵn hàm currency.amount_to_text() nhưng tiếng Anh.
        Tạm thời dùng placeholder, sau tích hợp thư viện num2words hoặc viết riêng.

        Args:
            amount (float): Số tiền

        Returns:
            str: Số tiền bằng chữ
        """
        # TODO: Implement đầy đủ với num2words hoặc custom VN function
        # Hiện tại trả placeholder để không block flow
        try:
            return self.currency_id.amount_to_text(amount)
        except Exception:
            return f'{amount:,.0f} đồng'

    #-- button handlers ----
    def action_meinvoice_send(self):
        """
        Button [Phát hành MeInvoice]: gửi và phát hành hóa đơn lên MeInvoice.
        Chỉ hoạt động khi meinvoice_can_send = True.

        Flow:
            1. Validate
            2. Lấy config + token
            3. Build invoice data
            4. Gọi API issue
            5. Lưu kết quả + cập nhật state
        """
        self.ensure_one()
        if not self.meinvoice_can_send:
            raise UserError(_(
                'Không thể gửi MeInvoice. Hóa đơn phải ở trạng thái Đã xác nhận '
                'và chưa được phát hành.'
            ))
        config = self.env['meinvoice.config'].get_active_config()
        api = self.env['meinvoice.api']

        #update state-> pending to avoid double-click
        self.write({
            'meinvoice_state': 'pending',
            'meinvoice_error_msg': False,
        })
        try:
            invoice_data = self._build_meinvoice_invoice_data(config)
            result = api.issue_invoice(config, invoice_data, move_id=self.id)
            self.write({
                'meinvoice_state': 'issued',
                'meinvoice_transaction_id':result.get('TransactionID'),
                'meinvoice_inv_no':result.get('InvNo') or result.get('InvoiceNo'),
                'meinvoice_inv_date': result.get('InDate'),
            })
            self.message_post(
                body=_(
                    'Hóa đơn điện tử đã phát hành thành công.<br/>'
                    'Số HĐ: <b>%s</b><br/>'
                    'Transaction ID: <b>%s</b>'
                ) % (self.meinvoice_inv_no, self.meinvoice_transaction_id)
            )
        except Exception as e:
            #store error, allow retry.
            self.write({
                'meinvoice_state': 'error',
                'meinvoice_error_msg': str(e),
            })
            self.message_post(
                body=_('Phát hành MeInvoice thất bại: %s') % str(e)
            )
            raise

    def action_meinvoice_preview(self):
        """
                Button [Xem trước HĐ]: lấy link preview từ MeInvoice, mở trong tab mới.
                Link chỉ tồn tại 5 phút.
                """
        self.ensure_one()
        config = self.env['meinvoice.config'].get_active_config()
        api = self.env['meinvoice.api']

        invoice_data = self._build_meinvoice_invoice_data(config)
        preview_url = api.preview_invoice(config, invoice_data)
        return {
            'type': 'ir.actions.act_url',
            'url': preview_url,
            'target': 'new'
        }

    def action_meinvoice_refresh_status(self):
        """
        Button [Cập nhật trạng thái]: query MeInvoice lấy status mới nhất.
        Dùng khi cần verify hóa đơn đã được CQT chấp nhận chưa.
        """
        self.ensure_one()
        if not self.meinvoice_transaction_id:
            raise UserError(_('Hóa đơn chưa có mã tra cứu. Chưa phát hành thành công.'))
        config = self.env['meinvoice.config'].get_active_config()
        api = self.env['meinovice.api']
        statuses = api.get_invoice_status(config,[self.meinvoice_transaction_id])
        if statuses:
            status = statuses[0]
            self.message_post(
                body=_('Trạng thái MeInvoice: %s') % str(status)
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Đã cập nhật'),
                'message': _('Trạng thái đã được cập nhật từ MeInvoice.'),
                'type':'success',
            }
        }

    def action_meinvoice_send_email(self):
        """
                Button [Gửi email HĐ]: gửi email hóa đơn cho khách hàng qua MeInvoice.
                Chỉ hoạt động trên Production.
                """
        self.ensure_one()
        if self.meinvoice_state != 'issued':
            raise UserError(_('Hóa đơn chưa được phát hành trên MeInvoice.'))
        if not self.partner_id.email:
            raise UserError(_('Khách hàng chưa có email.'))

        config = self.env['meinvoice.config'].get_active_config()
        api = self.env['meinvoice.api']

        api.send_email(
            config,
            transaction_id=self.meinvoice_transaction_id,
            receiver_email=self.partner_id.email,
            receiver_name=self.partner_id.name,
        )

        self.message_post(
            body=_('Đã gửi email hóa đơn đến: %s') % self.partner_id.email
        )
