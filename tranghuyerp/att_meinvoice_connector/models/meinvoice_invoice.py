import json
import uuid
import logging
from operator import index

from odoo import models, fields, api,  _
from odoo.exceptions import UserError
from datetime import date, timedelta


_logger = logging.getLogger(__name__)


class MeinvoiceInvoice(models.Model):
    """
    Lưu trữ hóa đơn theo format MeInvoice thuần túy.
    Đây là trung gian giữa MeInvoice API và Odoo account.move.

    2 chiều:
    - Chiều A (Odoo → MeInvoice): build_from_move() → gửi API
    - Chiều B (MeInvoice → Odoo): fetch về → create_move()

    Luôn lưu raw data trước → sau đó mới mapping.
    Dễ debug: xem đúng data MeInvoice trông như nào.
    """
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _name = 'meinvoice.invoice'
    _description = 'MeInvoice Invoice'
    _order = 'create_date desc'
    _rec_name = 'ref_id'

    # -- odoo ---
    account_move_id = fields.Many2one('account.move', 'Hóa đơn Odoo', ondelete='set null', index=True, help='account.move tương ứng')
    config_id = fields.Many2one('meinvoice.config', 'Cấu hình', ondelete='restrict')
    #--state --
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('published', 'Đã phát hành'),
        ('cancelled', 'Đã hủy'),
        ('error', 'Lỗi'),
    ], 'Trạng thái', default='draft',index=True, tracking=True)
    #header MeInvoice V2
    ref_id = fields.Char('RefID', index=True, copy=False, help='GUID tự sinh - MeInvoice dùng để check trùng')
    inv_no = fields.Char('Số HĐ', index=True, help='Số hóa đơn chính thức do MeInvoice cấp sau khi tạo hóa đơn .')
    transactionID = fields.Char('Mã tra cứu', index=True,help='Số hóa đơn chính thức do MeInvoice cấp sau khi phát hành( Mã tra cứu) .')
    inv_series = fields.Char('Ký hiệu Hóa đơn')
    inv_date = fields.Date('Ngày Hóa Đơn')
    invoice_template_id = fields.Char('Template ID')
    e_invoice_status = fields.Integer('EInvoiceStatus', default=1, help='1=HĐ gốc, 3=Thay thế, 4=Điều chỉnh')
    #bên mua (v2 fields names)
    account_object_code = fields.Char('Mã KH')
    account_object_name = fields.Char('Tên KH')
    account_object_tax_code = fields.Char('MST KH')
    account_object_address = fields.Char('Địa chỉ KH')
    contact_name = fields.Char('Người liên hệ')
    receiver_name = fields.Char('Người nhận')
    receiver_email = fields.Char('Email')
    receiver_mobile = fields.Char('SĐT')
    #  Thanh toán
    payment_method = fields.Char('Phương thức TT', default='TM/CK')
    currency_code = fields.Char('Tiền tệ', default='VND')
    exchange_rate = fields.Float('Tỷ giá', default=1.0)
    discount_rate = fields.Float('Chiết khấu tổng (%)', default=0)
    # Tổng tiền
    total_sale_amount_oc = fields.Float('Tổng tiền hàng (NT)')
    total_sale_amount = fields.Float('Tổng tiền hàng (QĐ)')
    total_discount_amount_oc = fields.Float('Tổng CK (NT)')
    total_discount_amount = fields.Float('Tổng CK (QĐ)')
    total_vat_amount_oc = fields.Float('Tổng VAT (NT)')
    total_vat_amount = fields.Float('Tổng VAT (QĐ)')
    total_amount_oc = fields.Float('Tổng cộng (NT)')
    total_amount = fields.Float('Tổng cộng (QĐ)')
    # Lines
    line_ids = fields.One2many(
        'meinvoice.invoice.line', 'invoice_id',
        string='Dòng hàng hóa',
    )
    # Raw JSON
    raw_request = fields.Text('Raw Request JSON',
                              help='Dữ liệu gửi lên MeInvoice — lưu để audit')
    raw_response = fields.Text('Raw Response JSON',
                               help='Dữ liệu nhận về từ MeInvoice — lưu để audit')
    create_date = fields.Datetime('Ngày tạo', readonly=True)


    #- A : account.move -> meinvoice.invoice
    @api.model
    def build_from_move(self, move, config):
        """
        Chiều A: Chuyển account.move → tạo meinvoice.invoice record
        và trả về invoice_data dict để gửi lên API.

        Flow:
            account.move (posted)
                → build_from_move()
                → tạo meinvoice.invoice + lines
                → return invoice_data dict
                → gọi api.insert_invoice(invoice_data)

        Args:
            move: account.move record
            config: meinvoice.config record

        Returns:
            tuple: (meinvoice.invoice record, invoice_data dict)
        """
        move.ensure_one()
        #refID: giu nguyen khi retry
        if move.meinvoice_ref_id:
            ref_id = move.meinvoice_ref_id
        else:
            ref_id = str(uuid.uuid4())
        partner = move.partner_id
        today = fields.Date.today().strftime('%Y-%m-%d')
        inv_date = move.invoice_date.strftime('%Y-%m-%d') if move.invoice_date else today
        #build lines
        line_data_list = []
        line_records = []
        for idx, line in enumerate(move.invoice_line_ids.filtered(lambda l: l.product_id), 1):
            vat_rate = self._get_vat_rate(line)
            vat_amount = 0 if vat_rate < 0 else (line.price_total - line.price_subtotal)
            discount_amount = line.price_unit * line.quantity * (line.discount or 0) / 100
            line_data = {
                'InventoryItemType': 0,
                'InventoryItemCode': line.product_id.default_code or '',
                'Description': line.name or line.product_id.name or '',
                'SortOrderView': idx,
                'SortOrder': idx,
                'UnitName': line.product_uom_id.name if line.product_uom_id else 'Cái',
                'Quantity': line.quantity,
                'UnitPrice': line.price_unit,
                'DiscountRate': line.discount or 0,
                'DiscountAmountOC': discount_amount,
                'DiscountAmount': discount_amount,
                'AmountOC':  line.price_subtotal,
                'Amount': line.price_subtotal,
                'VATRate': vat_rate,
                'VATAmountOC': vat_amount,
                'VATAmount': vat_amount,
            }
            line_data_list.append(line_data)
            line_records.append({
                'inventory_item_type': 0,
                'inventory_item_code': line.product_id.default_code or '',
                'description': line.name or line.product_id.name or '',
                'sort_order': idx,
                'unit_name': line.product_uom_id.name if line.product_uom_id else 'Cái',
                'quantity': line.quantity,
                'unit_price': line.price_unit,
                'discount_rate': line.discount or 0,
                'discount_amount_oc': discount_amount,
                'amount_oc': line.price_subtotal,
                'amount': line.price_subtotal,
                'vat_rate': vat_rate,
                'vat_amount_oc': vat_amount,
                'vat_amount': vat_amount,
                'odoo_line_id': line.id,
            })
        #Assemble invoice_data dict (V2 format)
        invoice_data = {
            'RefID': ref_id,
            'InvoiceTemplateID': config.invoice_template_id,
            'InvSeries': config.inv_series,
            'InvDate': inv_date,
            'CreatedDate': today,
            'ModifiedDate': today,
            'EInvoiceStatus': 1,
            'PaymentMethod': 'TM/CK',
            'CurrencyCode': move.currency_id.name or 'VND',
            'ExchangeRate': 1.0,
            'DiscountRate': 0,
            'AccountObjectCode': partner.ref or '',
            'AccountObjectName': partner.name or '',
            'AccountObjectTaxCode': partner.vat or '',
            'AccountObjectAddress': self._get_partner_address(partner),
            'ContactName': partner.name or '',
            'ReceiverName': partner.name or '',
            'ReceiverEmail': partner.email or '',
            'ReceiverMobile': partner.phone or partner.mobile or '',
            'TotalSaleAmountOC': move.amount_untaxed,
            'TotalSaleAmount': move.amount_untaxed,
            'TotalDiscountAmountOC': 0,
            'TotalDiscountAmount': 0,
            'TotalVATAmountOC': move.amount_tax,
            'TotalVATAmount': move.amount_tax,
            'TotalAmountOC': move.amount_total,
            'TotalAmount': move.amount_total,
            'InvoiceDetails': line_data_list,
        }
        # Tạo meinvoice.invoice record
        mei = self.create({
            'ref_id': ref_id,
            'inv_series': config.inv_series,
            'inv_date': move.invoice_date or fields.Date.today(),
            'invoice_template_id': config.invoice_template_id,
            'e_invoice_status': 1,
            'account_object_code': partner.ref or '',
            'account_object_name': partner.name or '',
            'account_object_tax_code': partner.vat or '',
            'account_object_address': self._get_partner_address(partner),
            'contact_name': partner.name or '',
            'receiver_name': partner.name or '',
            'receiver_email': partner.email or '',
            'receiver_mobile': partner.phone or partner.mobile or '',
            'payment_method': 'TM/CK',
            'currency_code': move.currency_id.name or 'VND',
            'exchange_rate': 1.0,
            'discount_rate': 0,
            'total_sale_amount_oc': move.amount_untaxed,
            'total_sale_amount': move.amount_untaxed,
            'total_discount_amount_oc': 0,
            'total_discount_amount': 0,
            'total_vat_amount_oc': move.amount_tax,
            'total_vat_amount': move.amount_tax,
            'total_amount_oc': move.amount_total,
            'total_amount': move.amount_total,
            'account_move_id': move.id,
            'config_id': config.id,
            'state': 'draft',
            'raw_request': json.dumps(invoice_data, ensure_ascii=False, indent=2),
            'line_ids': [(0, 0, lr) for lr in line_records],
        })
        #update ref_id to account.move
        move.write({
            'meinvoice_ref_id': ref_id,
        })
        return mei, invoice_data


    #B: meinvoice.invoice -> account.move

    def create_move(self):
        """
        Chiều B: Từ meinvoice.invoice record đã fetch về
        → tạo account.move (draft) trong Odoo.

        Flow:
            MeInvoice API (paging/getlist)
                → fetch raw data
                → tạo meinvoice.invoice + lines
                → create_move()
                → account.move (draft)

        Returns:
            account.move record
        """
        self.ensure_one()
        if self.account_move_id:
            raise UserError(_(
                '[MeInvoice] Hóa đơn MeInvoice này đã được liên kết với '
                'hóa đơn Odoo %s.'
            ) % self.account_move_id.name)

        partner = self._mapping_partner()

        currency = self.env['res.currency'].search([
            ('name', '=', self.currency_code or 'VND')  # ← VND không phải VNĐ
        ], limit=1)

        line_vals = []
        for line in self.line_ids:
            product = line._find_product()  # ← đổi từ _mapping_product
            tax = line._find_tax()  # ← đổi từ _mapping_tax
            line_vals.append((0, 0, {
                'name': line.description,
                'product_id': product.id if product else False,
                'quantity': line.quantity,
                'price_unit': line.unit_price,
                'discount': line.discount_rate,
                'tax_ids': [(6, 0, [tax.id])] if tax else [(5, 0, 0)],  # ← tuple
            }))

        move = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': partner.id,
            'invoice_date': self.inv_date,
            'currency_id': currency.id if currency else False,
            'invoice_line_ids': line_vals,
            'meinvoice_ref_id': self.ref_id,
            'meinvoice_inv_no': self.inv_no,
            'meinvoice_invoice_id': self.id,
            'meinvoice_state': 'published' if (
                    self.inv_no and self.inv_no != '<Chưa cấp số>'
            ) else 'draft_sent',
        })

        self.write({
            'account_move_id': move.id,
            'state': 'published' if (
                    self.inv_no and self.inv_no != '<Chưa cấp số>'
            ) else 'draft',
        })

        _logger.info('MeInvoice: Created account.move %s from RefID %s', move.name, self.ref_id)
        return move



    @api.model
    def create_from_api_response(self, raw_data, config):
        """
        Tạo meinvoice.invoice + lines từ raw data fetch về MeInvoice.
        Dùng khi fetch hóa đơn từ MeInvoice về Odoo (chiều B).

        Args:
            raw_data: dict 1 hóa đơn từ API response
            config: meinvoice.config record

        Returns:
            meinvoice.invoice record
        """
        inv_date = raw_data.get('InvDate', '')
        if inv_date and len(inv_date) >= 10:
            inv_date = inv_date[:10]
        else:
            inv_date = False
        lines = raw_data.get('InvoiceDetails') or raw_data.get('OriginalInvoiceDetail', [])
        line_vals = []
        for idx, line in enumerate(lines, 1):
            line_vals.append((0,0, {
                'inventory_item_type': line.get('InventoryItemType', 0),
                'inventory_item_code': line.get('InventoryItemCode') or line.get('ItemCode', ''),
                'description': line.get('Description') or line.get('ItemName', ''),
                'sort_order': line.get('SortOrder', idx),
                'unit_name': line.get('UnitName', ''),
                'quantity': line.get('Quantity', 0),
                'unit_price': line.get('UnitPrice', 0),
                'discount_rate': line.get('DiscountRate', 0),
                'discount_amount_oc': line.get('DiscountAmountOC', 0),
                'amount_oc': line.get('AmountOC', 0),
                'amount': line.get('Amount', 0),
                'vat_rate': line.get('VATRate', 0),
                'vat_amount_oc': line.get('VATAmountOC', 0),
                'vat_amount': line.get('VATAmount', 0),
            }))

        return self.create({
            'ref_id': raw_data.get('RefID'),
            'inv_no': raw_data.get('InvNo', ''),
            'transactionID': raw_data.get('TransactionID', ''),
            'inv_series': raw_data.get('InvSeries'),
            'inv_date': inv_date,
            'invoice_template_id': raw_data.get('InvoiceTemplateID', ''),
            'e_invoice_status': raw_data.get('EInvoiceStatus', 1),
            'account_object_code': raw_data.get('AccountObjectCode', ''),
            'account_object_name': raw_data.get('AccountObjectName', ''),
            'account_object_tax_code': raw_data.get('AccountObjectTaxCode', ''),
            'account_object_address': raw_data.get('AccountObjectAddress', ''),
            'contact_name': raw_data.get('ContactName', ''),
            'receiver_name': raw_data.get('ReceiverName', ''),
            'receiver_email': raw_data.get('ReceiverEmail', ''),
            'receiver_mobile': raw_data.get('ReceiverMobile', ''),
            'payment_method': raw_data.get('PaymentMethod', 'TM/CK'),
            'currency_code': raw_data.get('CurrencyCode', 'VND'),
            'exchange_rate': raw_data.get('ExchangeRate', 1.0),
            'discount_rate': raw_data.get('DiscountRate', 0),
            'total_sale_amount_oc': raw_data.get('TotalSaleAmountOC', 0),
            'total_sale_amount': raw_data.get('TotalSaleAmount', 0),
            'total_discount_amount_oc': raw_data.get('TotalDiscountAmountOC', 0),
            'total_discount_amount': raw_data.get('TotalDiscountAmount', 0),
            'total_vat_amount_oc': raw_data.get('TotalVATAmountOC', 0),
            'total_vat_amount': raw_data.get('TotalVATAmount', 0),
            'total_amount_oc': raw_data.get('TotalAmountOC', 0),
            'total_amount': raw_data.get('TotalAmount', 0),
            'config_id': config.id,
            'state': 'published' if raw_data.get('InvNo') else 'draft',
            'raw_response': json.dumps(raw_data, ensure_ascii=False, indent=2),
            'line_ids': line_vals,
        })

    def _get_vat_rate(self, line):
        """VAT rate integer: -1=KCT, 0,5,8,10"""
        taxes = line.tax_ids.filtered(lambda t: t.type_tax_use == 'sale')
        if not taxes:
            return -1
        tax = taxes[0]
        if 'EXEMPTION' in (tax.name or '').upper():
            return -1
        return {0: 0, 5: 5, 8: 8, 10: 10}.get(int(tax.amount), int(tax.amount))

    def _mapping_partner(self):
        """Tìm partner theo MST hoặc tên. Tạo mới nếu không có."""
        Partner = self.env['res.partner']

        if self.account_object_tax_code:
            partner = Partner.search([
                ('vat', '=', self.account_object_tax_code)
            ], limit=1)
            if partner:
                return partner

        if self.account_object_name:
            partner = Partner.search([
                ('name', '=', self.account_object_name)
            ], limit=1)
            if partner:
                return partner

        return Partner.create({
            'name': self.account_object_name or 'Khách lẻ',
            'vat': self.account_object_tax_code or False,
            'email': self.receiver_email or False,
            'phone': self.receiver_mobile or False,
            'street': self.account_object_address or False,
            'customer_rank': 1,
        })

    def _get_partner_address(self, partner):
        """Ghép địa chỉ đầy đủ từ partner."""
        parts = filter(None, [
            partner.street, partner.street2,
            partner.city,
            partner.state_id.name if partner.state_id else '',
            partner.country_id.name if partner.country_id else '',
        ])
        return ', '.join(parts)

    def action_view_account_move(self):
        """Smart button → mở account.move tương ứng."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.account_move_id.id,
            'target': 'current',
        }

    @api.model
    def cron_fetch_from_meinvoice(self):
        """
        Cron tự động fetch HĐ từ MeInvoice → tạo meinvoice.invoice records.
        Chạy mỗi ngày 1 lần.
        Flow:
            get_invoice_paging() → raw data list
            → check từng RefID đã tồn tại chưa
            → create_from_api_response() nếu chưa có
        """

        configs = self.env['meinvoice.config'].search([('active', '=', True)])
        for config in configs:
            try:
                api = self.env['meinvoice.api']
                to_date = date.today().strftime('%Y-%m-%d')
                from_date = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')
                invoices = api.get_invoice_paging(
                    config,
                    from_date=from_date,
                    to_date=to_date,
                    start=0,
                    length=100,
                )
                created = 0
                skipped = 0
                for inv_data in invoices:
                    ref_id = inv_data.get('RefID')
                    if not ref_id:
                        continue
                    # Skip nếu đã tồn tại
                    existing = self.search([
                        ('ref_id', '=', ref_id),
                    ], limit=1)
                    if existing:
                        skipped += 1
                        continue
                    # Tạo record mới
                    try:
                        detail_list = api.get_invoice_list(config, [ref_id])
                        detail_data = detail_list[0] if detail_list else inv_data
                    except Exception:
                        detail_data = inv_data  # fallback dùng data từ paging

                    mei = self.create_from_api_response(detail_data, config)
                    created += 1
                    # self.create_from_api_response(inv_data, config)
                    # created += 1
                _logger.info(
                    'MeInvoice cron fetch [%s]: created=%d skipped=%d',
                    config.name, created, skipped,
                )
                #auto tạo account.move
                try:
                    mei.create_move()
                    self.env.cr.commit()
                except Exception as e:
                    _logger.error('Failed create_move for RefID %s: %s', ref_id, str(e))
            except Exception as e:
                _logger.error(
                    'MeInvoice cron fetch failed [%s]: %s',
                    config.name, str(e),
                )

class MeinvoiceInvoiceLine(models.Model):
    """
    Dòng hàng hóa/dịch vụ theo format MeInvoice V2.
    1 record = 1 dòng InvoiceDetail.
    """
    _name = 'meinvoice.invoice.line'
    _description = 'MeInvoice Invoice Line'
    _order = 'sort_order'

    invoice_id = fields.Many2one(
        'meinvoice.invoice', string='Hóa đơn MeInvoice',
        ondelete='cascade', index=True, required=True,
    )
    odoo_line_id = fields.Many2one(
        'account.move.line', string='Dòng Odoo',
        ondelete='set null',
        help='account.move.line tương ứng (chiều A)',
    )

    # Fields theo MeInvoice V2 InvoiceDetail
    inventory_item_type = fields.Integer('Tính chất HHDV', default=0,
                                         help='0=HHDV thường, 2=Khuyến mại, 3=Ghi chú, 4=Chiết khấu')
    inventory_item_code = fields.Char('Mã HH/DV')
    description = fields.Char('Tên HH/DV', required=True)
    sort_order = fields.Integer('Thứ tự', default=1)
    unit_name = fields.Char('ĐVT')
    quantity = fields.Float('Số lượng', digits=(12, 4))
    unit_price = fields.Float('Đơn giá', digits=(12, 2))
    discount_rate = fields.Float('CK (%)', digits=(5, 2))
    discount_amount_oc = fields.Float('Tiền CK (NT)', digits=(12, 2))
    amount_oc = fields.Float('Thành tiền (NT)', digits=(12, 2))
    amount = fields.Float('Thành tiền (QĐ)', digits=(12, 2))
    vat_rate = fields.Integer('Thuế suất',
                              help='-1=KCT, -3=KKKNT, 0=0%, 5=5%, 8=8%, 10=10%')
    vat_amount_oc = fields.Float('Tiền thuế (NT)', digits=(12, 2))
    vat_amount = fields.Float('Tiền thuế (QĐ)', digits=(12, 2))

    # Helpers

    def _find_product(self):
        """Tìm product theo mã hoặc tên."""
        if self.inventory_item_code:
            p = self.env['product.product'].search([
                ('default_code', '=', self.inventory_item_code)
            ], limit=1)
            if p:
                return p
        return self.env['product.product'].search([
            ('name', '=', self.description)
        ], limit=1)

    def _find_tax(self):
        """Tìm tax Sale theo vat_rate integer."""
        if self.vat_rate < 0:
            return False
        return self.env['account.tax'].search([
            ('type_tax_use', '=', 'sale'),
            ('amount', '=', self.vat_rate),
            ('amount_type', '=', 'percent'),
        ], limit=1)