from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)


class QuotationRequest(models.Model):
    _name = 'att.quotation.request'
    _description = 'Yêu cầu báo giá'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Mã báo giá',required=True,copy=False,index=True,readonly=True,default='New',tracking=True,)

    quotation_type = fields.Selection([
        ('sale', 'Báo giá bán'),
        ('purchase', 'Báo giá mua'),
    ], string='Loại báo giá', required=True, index=True, default='sale', tracking=True)

    partner_id = fields.Many2one(
        'res.partner',
        string='Đối tác',
        required=True,
        tracking=True,
    )

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Chứng từ gốc',
        copy=False,
        tracking=True,
        help='Dùng cho báo giá mua phát sinh từ Sale Order đã xác nhận.',
    )

    contract_id = fields.Many2one(
        'att.contract',
        string='Hợp đồng được tạo',
        readonly=True,
        copy=False,
    )

    user_id = fields.Many2one(
        'res.users',
        string='Người phụ trách',
        default=lambda self: self.env.user,
        tracking=True,
    )

    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Tiền tệ',
        default=lambda self: self.env.company.currency_id,
    )

    valid_until = fields.Date(
        string='Hiệu lực báo giá đến',
    )

    payment_term_id = fields.Many2one(
        'account.payment.term',
        string='Điều khoản thanh toán',
    )

    quotation_line_ids = fields.One2many(
        'att.quotation.request.line',
        'quotation_id',
        string='Dòng báo giá',
        copy=True,
    )

    amount_untaxed = fields.Monetary(
        string='Thành tiền chưa thuế',
        compute='_compute_amount',
        store=True,
        currency_field='currency_id',
        tracking=True,
    )

    amount_tax = fields.Monetary(
        string='Tiền thuế',
        compute='_compute_amount',
        store=True,
        currency_field='currency_id',
        tracking=True,
    )

    amount_total = fields.Monetary(
        string='Tổng tiền',
        compute='_compute_amount',
        store=True,
        currency_field='currency_id',
        tracking=True,
    )

    note = fields.Text(
        string='Ghi chú',
    )

    state = fields.Selection([
        ('draft', 'Nháp'),
        ('sent', 'Đã gửi/Đã gọi'),
        ('received', 'Đã nhận phản hồi'),
        ('pending_approval', 'Chờ duyệt'),
        ('confirmed', 'Đã chốt'),
        ('lost', 'Không chọn'),
        ('cancelled', 'Đã hủy'),
    ], string='Trạng thái', default='draft', tracking=True)

    @api.depends(
        'quotation_line_ids.price_subtotal',
        'quotation_line_ids.price_tax',
        'quotation_line_ids.price_total',
    )
    def _compute_amount(self):
        for rec in self:
            rec.amount_untaxed = sum(rec.quotation_line_ids.mapped('price_subtotal'))
            rec.amount_tax = sum(rec.quotation_line_ids.mapped('price_tax'))
            rec.amount_total = sum(rec.quotation_line_ids.mapped('price_total'))

    @api.model
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                quotation_type = vals.get('quotation_type', 'sale')
                sequence_code = (
                    'att.quotation.request.purchase'
                    if quotation_type == 'purchase'
                    else 'att.quotation.request.sale'
                )
                vals['name'] = self.env['ir.sequence'].next_by_code(sequence_code) or 'New'

        return super().create(vals_list)


    def _get_manager_partners(self):
        group = self.env.ref(
            'att_quotation_contract.group_tranghuy_managers_sale_purchase',
            raise_if_not_found=False,
        )
        if not group:
            return self.env['res.partner']
        users = self.env['res.users'].search([
            ('group_ids', 'in', [group.id]),
            ('active', '=', True),
        ])
        return users.mapped('partner_id')


    def action_mark_sent(self):
        for rec in self:
            if rec.quotation_type == 'sale':
                # Mở wizard chọn fields thay vì gửi thẳng
                wizard = self.env['att.quotation.print.wizard'].create({
                    'quotation_id': rec.id,
                })
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'att.quotation.print.wizard',
                    'view_mode': 'form',
                    'res_id': wizard.id,
                    'target': 'new',
                    'name': 'Gửi / In báo giá',
                }
            else:
                # Mua: trigger voip call
                phone = rec.partner_id.phone or rec.partner_id.mobile
                if not phone:
                    raise UserError(_('Đối tác %s chưa có số điện thoại.') % rec.partner_id.name)
                self.env['voip.call'].create({
                    'partner_id': rec.partner_id.id,
                    'phone_number': phone,
                    'user_id': rec.user_id.id or self.env.user.id,
                    'direction': 'outgoing',
                    'activity_name': f'Báo giá NCC: {rec.name}',
                })
                rec.message_post(
                    body=Markup('Đã khởi tạo cuộc gọi đến NCC <b>%s</b> — SĐT: <b>%s</b>.') % (
                        rec.partner_id.name, phone,
                    ),
                    message_type='notification',
                    subtype_xmlid='mail.mt_note',
                )
                rec.state = 'sent'
    def _send_quotation_pdf(self, data=None):
        self.ensure_one()
        data = data or {}
        report = self.env.ref('att_quotation_contract.action_report_att_quotation_request')
        pdf_content, _ = report._render_qweb_pdf(
            report,
            res_ids=[self.id],
            data=data,
        )
        attachment = self.env['ir.attachment'].create({
            'name': f'Bao_gia_{self.name}.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        template = self.env.ref(
            'att_quotation_contract.email_template_quotation_sent',
            raise_if_not_found=False,
        )
        if template:
            template.send_mail(self.id, force_send=True)
        self.message_post(
            body=Markup('Đã gửi báo giá <b>%s</b> đến <b>%s</b> (%s).') % (
                self.name,
                self.partner_id.name,
                self.partner_id.email or 'không có email',
            ),
            attachment_ids=[attachment.id],
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )
        self.state = 'sent'

    def action_mark_received(self):
        for rec in self:
            if not rec.quotation_line_ids:
                raise UserError(_('Vui lòng nhập ít nhất một dòng báo giá.'))
            rec.state = 'received'


    def action_create_contract(self):
        """Tạo HĐ nguyên tắc sau khi BG đã chốt."""
        self.ensure_one()

        if self.contract_id:
            raise UserError(_('Báo giá này đã tạo hợp đồng rồi.'))

        if self.quotation_type == 'purchase':
            self._check_purchase_minimum_quotations()

        # Mở form HĐ mới với context prefill
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo hợp đồng nguyên tắc'),
            'res_model': 'att.contract',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_contract_type': self.quotation_type,
                'default_partner_id': self.partner_id.id,
                'default_source_quotation_id': self.id,
                'default_sale_order_id': self.sale_order_id.id if self.sale_order_id else False,
                'default_payment_term_id': self.payment_term_id.id if self.payment_term_id else False,
                'default_company_id': self.company_id.id,
                'default_currency_id': self.currency_id.id,
            },
        }

    def _check_purchase_minimum_quotations(self):
        self.ensure_one()
        if not self.sale_order_id:
            return
        confirmed_quotations = self.search([
            ('quotation_type', '=', 'purchase'),
            ('sale_order_id', '=', self.sale_order_id.id),
            ('state', '=', 'confirmed'),
        ])
        if len(confirmed_quotations) < 5:
            raise UserError(_(
                'Cần có tối thiểu 5 báo giá NCC đã được chốt cho đơn hàng %s trước khi tạo hợp đồng mua.\n'
                'Hiện tại: %d/5'
            ) % (self.sale_order_id.name, len(confirmed_quotations)))


    def _mark_other_purchase_quotations_lost(self):
        self.ensure_one()
        other_quotations = self.search([
            ('quotation_type', '=', 'purchase'),
            ('sale_order_id', '=', self.sale_order_id.id),
            ('id', '!=', self.id),
            ('state', 'not in', ['cancelled', 'confirmed']),
        ])
        other_quotations.write({'state': 'lost'})


    def action_request_approval(self):
        """User thường gọi — gửi yêu cầu duyệt chốt BG."""
        for rec in self:
            if not rec.quotation_line_ids:
                raise UserError(_('Vui lòng nhập ít nhất một dòng báo giá.'))
            partner_ids = self._get_manager_partners().ids
            rec.state = 'pending_approval'
            rec.message_post(
                body=Markup(
                    '<b>%s</b> yêu cầu duyệt chốt báo giá <b>%s</b> với đối tác <b>%s</b>.<br/>'
                    'Tổng tiền: <b>%s %s</b>'
                ) % (
                    self.env.user.name,
                    rec.name,
                    rec.partner_id.name,
                    '{:,.0f}'.format(rec.amount_total),
                    rec.currency_id.name,
                ),
                partner_ids=partner_ids,
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )

    def action_confirm(self):
        """Chỉ manager group mới gọi được."""
        for rec in self:
            if rec.contract_id:
                raise UserError(_('Báo giá này đã tạo hợp đồng rồi.'))
            if not rec.quotation_line_ids:
                raise UserError(_('Vui lòng nhập ít nhất một dòng báo giá.'))
            rec.state = 'confirmed'
            rec.message_post(
                body=Markup(
                    '<b>%s</b> đã duyệt và chốt báo giá <b>%s</b>.'
                ) % (self.env.user.name, rec.name),
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )

    def action_view_contract(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'att.contract',
            'view_mode': 'form',
            'res_id': self.contract_id.id,
        }


    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})




class QuotationRequestLine(models.Model):
    _name = 'att.quotation.request.line'
    _description = 'Dòng yêu cầu báo giá'
    _order = 'sequence, id'

    quotation_id = fields.Many2one(
        'att.quotation.request',
        string='Yêu cầu báo giá',
        required=True,
        ondelete='cascade',
    )

    sequence = fields.Integer(
        string='Thứ tự',
        default=10,
    )

    name = fields.Text(
        string='Nội dung chi tiết',
        required=True,
    )

    pickup_location = fields.Char(
        string='Điểm đi',
    )

    delivery_location = fields.Char(
        string='Điểm đến',
    )

    route_detail = fields.Char(
        string='Chi tiết điểm đi & điểm đến',
        help='Ví dụ: 257 Phạm Văn Đồng - 129 Trường Chinh.',
    )

    vehicle_type = fields.Char(
        string='Loại xe',
    )

    expected_date = fields.Datetime(
        string='Thời gian dự kiến',
    )

    quantity = fields.Float(
        string='Số chuyến dự kiến',
        default=1.0,
    )

    uom_id = fields.Many2one(
        'uom.uom',
        string='Đơn vị tính',
    )

    price_unit = fields.Monetary(
        string='Đơn giá',
        currency_field='currency_id',
    )

    tax_ids = fields.Many2many(
        comodel_name='account.tax',
        string='Thuế',
    )

    currency_id = fields.Many2one(
        related='quotation_id.currency_id',
        store=True,
        readonly=True,
    )

    price_subtotal = fields.Monetary(
        string='Thành tiền chưa thuế',
        compute='_compute_amount',
        store=True,
        currency_field='currency_id',
    )

    price_tax = fields.Monetary(
        string='Tiền thuế',
        compute='_compute_amount',
        store=True,
        currency_field='currency_id',
    )

    price_total = fields.Monetary(
        string='Tổng tiền',
        compute='_compute_amount',
        store=True,
        currency_field='currency_id',
    )

    note = fields.Text(
        string='Ghi chú',
    )
    transport_mode_id = fields.Many2one(
        "att.transport.mode",
        string="Hình thức vận chuyển",
    )

    @api.depends('quantity', 'price_unit', 'tax_ids', 'currency_id')
    def _compute_amount(self):
        for line in self:
            if line.tax_ids:
                taxes = line.tax_ids.compute_all(
                    line.price_unit,
                    currency=line.currency_id,
                    quantity=line.quantity,
                    partner=line.quotation_id.partner_id,
                )
                line.price_subtotal = taxes['total_excluded']
                line.price_tax = taxes['total_included'] - taxes['total_excluded']
                line.price_total = taxes['total_included']
            else:
                line.price_subtotal = line.quantity * line.price_unit
                line.price_tax = 0.0
                line.price_total = line.price_subtotal



