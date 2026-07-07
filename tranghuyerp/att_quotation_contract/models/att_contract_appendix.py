from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
from markupsafe import Markup


class ContractAppendix(models.Model):
    _name = 'att.contract.appendix'
    _description = 'Phụ lục hợp đồng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char('Số phụ lục', required=True, copy=False, readonly=True, default='New', tracking=True, index=True)
    contract_id = fields.Many2one('att.contract', 'Hợp đồng', required=True, tracking=True, ondelete='restrict')
    appendix_type = fields.Selection([
        ('sale', 'Phụ lục bán'),
        ('purchase', 'Phụ lục mua'),
    ], string='Loại phụ lục', required=True, tracking=True, index=True)
    partner_id = fields.Many2one('res.partner', 'Đối tác', required=True, tracking=True)
    effective_date = fields.Date('Ngày hiệu lực', tracking=True)
    expired_date = fields.Date('Ngày hết hạn', tracking=True)
    company_id = fields.Many2one('res.company', 'Công ty', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one('res.currency', 'Tiền tệ', default=lambda self: self.env.user.company_id.currency_id)

    # Thông tin dầu
    fuel_ref_price = fields.Monetary('Giá dầu tham chiếu (VNĐ/lít)', currency_field='currency_id', tracking=True)
    fuel_ref_date = fields.Date('Ngày tham chiếu giá dầu', tracking=True)
    fuel_ratio = fields.Float('Tỷ trọng nhiên liệu (%)', default=30.0, tracking=True)
    fuel_note = fields.Text('Ghi chú dầu')

    appendix_line_ids = fields.One2many('att.contract.appendix.line', 'appendix_id', 'Dòng phụ lục', copy=True)
    extra_line_ids = fields.One2many('att.contract.appendix.extra.line', 'appendix_id', 'Thông tin bổ sung')

    amount_untaxed = fields.Monetary('Thành tiền chưa thuế', compute='_compute_amount', store=True, currency_field='currency_id')
    amount_tax = fields.Monetary('Tiền thuế', compute='_compute_amount', store=True, currency_field='currency_id')
    amount_total = fields.Monetary('Tổng tiền', compute='_compute_amount', store=True, currency_field='currency_id')

    sale_order_id = fields.Many2one('sale.order', 'Chứng từ bán gốc', readonly=True, copy=False)
    purchase_order_id = fields.Many2one('purchase.order', 'Chứng từ mua gốc', readonly=True, copy=False)

    # Snapshot đối tác
    partner_representative = fields.Char('Người đại diện đối tác', tracking=True)
    partner_position = fields.Char('Chức vụ người đại diện', tracking=True)

    state = fields.Selection([
        ('draft', 'Nháp'),
        ('sent_draft', 'Đã gửi nháp'),
        ('pending_approval', 'Chờ duyệt'),
        ('confirmed', 'Đã xác nhận'),
        ('done', 'Đã tạo SO/PO'),
        ('cancelled', 'Đã hủy'),
    ], string='Trạng thái', default='draft', tracking=True)

    @api.depends(
        'appendix_line_ids.price_subtotal',
        'appendix_line_ids.price_tax',
        'appendix_line_ids.price_total',
        'appendix_line_ids.is_mapping',
        'appendix_line_ids.display_type',
    )
    def _compute_amount(self):
        for rec in self:
            service_lines = rec.appendix_line_ids.filtered(
                lambda l: not l.display_type and l.is_mapping
            )
            rec.amount_untaxed = sum(service_lines.mapped('price_subtotal'))
            rec.amount_tax = sum(service_lines.mapped('price_tax'))
            rec.amount_total = sum(service_lines.mapped('price_total'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                contract_id = vals.get('contract_id')
                if not contract_id:
                    vals['name'] = 'PL'
                    continue
                existing_count = self.search_count([('contract_id', '=', contract_id)])
                vals['name'] = 'PL%02d' % (existing_count + 1)
        records = super().create(vals_list)
        for rec in records:
            if rec.contract_id:
                rec.partner_representative = rec.contract_id.partner_representative
                rec.partner_position = rec.contract_id.partner_position
        return records

    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        for rec in self:
            if not rec.sale_order_id or rec.appendix_type != 'purchase':
                continue
            lines = []
            for sol in rec.sale_order_id.order_line:
                if sol.display_type:
                    lines.append((0, 0, {
                        'display_type': sol.display_type,
                        'name': sol.name,
                        'is_mapping': False,
                    }))
                    continue
                lines.append((0, 0, {
                    'name': sol.name,
                    'product_id': sol.product_id.id if sol.product_id else False,
                    'uom_id': sol.product_uom_id.id if sol.product_uom_id else False,
                    'quantity': sol.product_uom_qty,
                    'pickup_location': sol.pickup_location if hasattr(sol, 'pickup_location') else False,
                    'delivery_location': sol.delivery_location if hasattr(sol, 'delivery_location') else False,
                    'route_detail': sol.route_detail if hasattr(sol, 'route_detail') else False,
                    'vehicle_type': sol.vehicle_type if hasattr(sol, 'vehicle_type') else False,
                    'cargo_description': sol.cargo_description if hasattr(sol, 'cargo_description') else False,
                    'is_mapping': True,
                    # price_unit để trống — NCC sẽ báo giá
                }))
            rec.appendix_line_ids = [(5, 0, 0)] + lines


    @api.onchange('contract_id')
    def _onchange_contract_id(self):
        for rec in self:
            if rec.contract_id:
                rec.appendix_type = rec.contract_id.contract_type
                rec.partner_id = rec.contract_id.partner_id
                rec.company_id = rec.contract_id.company_id
                rec.currency_id = rec.contract_id.currency_id
                rec.partner_representative = rec.contract_id.partner_representative
                rec.partner_position = rec.contract_id.partner_position

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

    def action_send_draft(self):
        self.ensure_one()
        if not self.appendix_line_ids:
            raise UserError(_('Vui lòng nhập ít nhất một dòng phụ lục.'))
        template = self.env.ref(
            'att_quotation_contract.email_template_appendix_draft',
            raise_if_not_found=False,
        )
        if template:
            template.send_mail(self.id, force_send=True)
        self.state = 'sent_draft'

    def action_send_signed(self):
        self.ensure_one()
        # Generate PDF có chữ ký
        pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(
            'att_quotation_contract.report_att_appendix',
            res_ids=[self.id],
        )
        attachment = self.env['ir.attachment'].create({
            'name': f'PL_signed_{self.name}.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        template = self.env.ref(
            'att_quotation_contract.email_template_appendix_signed',
            raise_if_not_found=False,
        )
        if template:
            template.send_mail(self.id, force_send=True)
        # Log nội bộ kèm file PDF có chữ ký
        self.message_post(
            body=Markup(
                '<b>%s</b> đã gửi bản phụ lục đã ký <b>%s</b> đến <b>%s</b> (%s).<br/>'
                'File đính kèm bên dưới.'
            ) % (
                     self.env.user.name,
                     self.name,
                     self.partner_id.name,
                     self.partner_id.email or 'không có email',
                 ),
            # attachment_ids=[attachment.id],
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )

    def action_request_approval(self):
        """Gửi yêu cầu duyệt giá lên manager."""
        for rec in self:
            if not rec.appendix_line_ids:
                raise UserError(_('Vui lòng nhập ít nhất một dòng phụ lục.'))
            service_lines = rec._get_mapping_lines()
            if not service_lines:
                raise UserError(_('Cần có ít nhất một dòng dịch vụ có giá.'))
            partner_ids = rec._get_manager_partners().ids
            rec.state = 'pending_approval'
            rec.message_post(
                body=Markup(
                    '<b>%s</b> yêu cầu duyệt phụ lục <b>%s</b> với đối tác <b>%s</b>.<br/>'
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
        """Manager duyệt → xác nhận phụ lục → tạo SO/PO."""
        for rec in self:
            service_lines = rec._get_mapping_lines()
            if not service_lines:
                raise UserError(_('Phụ lục cần có ít nhất một dòng dịch vụ.'))
            rec.state = 'confirmed'
            # Tự động tạo SO/PO
            if rec.appendix_type == 'sale':
                rec.action_create_sale_order()
            else:
                rec.action_create_purchase_order()


    def action_create_sale_order(self):
        for rec in self:
            rec._check_can_create_order()
            if rec.appendix_type != 'sale':
                raise UserError(_('Chỉ phụ lục bán mới tạo đơn bán hàng.'))
            order_lines = []
            for line in rec._get_mapping_lines():
                order_lines.append((0, 0, line._prepare_sale_order_line_vals()))
            sale_order = self.env['sale.order'].create({
                'partner_id': rec.partner_id.id,
                'company_id': rec.company_id.id,
                'currency_id': rec.currency_id.id,
                'att_contract_id': rec.contract_id.id,
                'att_appendix_id': rec.id,
                'order_line': order_lines,
            })
            sale_order.action_confirm()
            rec.sale_order_id = sale_order.id
            rec.state = 'done'

    def action_create_purchase_order(self):
        for rec in self:
            rec._check_can_create_order()
            if rec.appendix_type != 'purchase':
                raise UserError(_('Chỉ phụ lục mua mới tạo Purchase Order.'))
            order_lines = []
            for line in rec._get_mapping_lines():
                order_lines.append((0, 0, line._prepare_purchase_order_line_vals()))
            purchase_order = self.env['purchase.order'].create({
                'partner_id': rec.partner_id.id,
                'company_id': rec.company_id.id,
                'currency_id': rec.currency_id.id,
                'att_contract_id': rec.contract_id.id,
                'att_appendix_id': rec.id,
                'order_line': order_lines,
            })
            purchase_order.button_confirm()
            rec.purchase_order_id = purchase_order.id
            rec.state = 'done'

    def _check_can_create_order(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'done'):
            raise UserError(_('Chỉ phụ lục đã xác nhận mới được tạo đơn hàng.'))
        if self.sale_order_id or self.purchase_order_id:
            raise UserError(_('Phụ lục này đã tạo SO/PO rồi.'))
        if not self._get_mapping_lines():
            raise UserError(_('Không có dòng dịch vụ để tạo SO/PO.'))

    def action_view_sale_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sale Order'),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
        }

    def action_view_purchase_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Order'),
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'res_id': self.purchase_order_id.id,
        }

    def _get_mapping_lines(self):
        self.ensure_one()
        return self.appendix_line_ids.filtered(
            lambda l: not l.display_type and l.is_mapping
        )

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})




class ContractAppendixLine(models.Model):
    _name = 'att.contract.appendix.line'
    _description = 'Dòng phụ lục hợp đồng'
    _order = 'sequence, id'

    appendix_id = fields.Many2one(
        'att.contract.appendix',
        string='Phụ lục',
        required=True,
        ondelete='cascade',
    )

    sequence = fields.Integer(string='Thứ tự', default=10)

    display_type = fields.Selection([
        ('line_section', 'Tiêu đề nhóm'),
        ('line_note', 'Ghi chú'),
    ], string='Loại dòng', default=False)

    is_mapping = fields.Boolean(
        string='Tạo SO/PO',
        default=True,
        help='Nếu bật, dòng này sẽ được dùng để tạo dòng SO/PO.',
    )

    name = fields.Text(
        string='Nội dung vận chuyển',
        required=True,
    )

    route_detail = fields.Char(
        string='Chi tiết điểm đi & điểm đến',
        help='Ví dụ: 257 Phạm Văn Đồng - 129 Trường Chinh.',
    )

    service_type_id = fields.Many2one(
        'product.category',
        string='Nhóm dịch vụ',
    )

    product_id = fields.Many2one(
        'product.product',
        string='Dịch vụ',
        domain="[('type', '=', 'service')]",
        copy=False,
    )

    uom_id = fields.Many2one(
        'uom.uom',
        string='Đơn vị tính',
    )

    quantity = fields.Float(string='Số lượng', default=1.0)

    load_capacity = fields.Char(
        string='Tải trọng',
        help='Ví dụ: ≤5 tấn',
    )

    pickup_location = fields.Char(string='Nơi đi')
    delivery_location = fields.Char(string='Nơi đến')
    vehicle_type = fields.Char(string='Loại xe/phương tiện')
    vehicle_id = fields.Many2one('fleet.vehicle', string='Phương tiện')
    transport_mode_id = fields.Many2one('att.transport.mode', string='Hình thức vận chuyển')
    cargo_description = fields.Text(string='Mô tả hàng hóa')

    price_unit = fields.Monetary(
        string='Đơn giá (chưa VAT)',
        currency_field='currency_id',
    )

    tax_ids = fields.Many2many(
        'account.tax',
        string='Thuế',
    )

    currency_id = fields.Many2one(
        related='appendix_id.currency_id',
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

    extra_note = fields.Text(string='Ghi chú')

    @api.depends('quantity', 'price_unit', 'tax_ids', 'display_type', 'is_mapping')
    def _compute_amount(self):
        for line in self:
            if line.display_type or not line.is_mapping:
                line.price_subtotal = 0.0
                line.price_tax = 0.0
                line.price_total = 0.0
                continue
            if line.tax_ids:
                taxes = line.tax_ids.compute_all(
                    line.price_unit,
                    currency=line.currency_id,
                    quantity=line.quantity,
                    product=line.product_id,
                    partner=line.appendix_id.partner_id,
                )
                line.price_subtotal = taxes['total_excluded']
                line.price_tax = taxes['total_included'] - taxes['total_excluded']
                line.price_total = taxes['total_included']
            else:
                line.price_subtotal = line.quantity * line.price_unit
                line.price_tax = 0.0
                line.price_total = line.price_subtotal

    @api.onchange('display_type')
    def _onchange_display_type(self):
        for line in self:
            if line.display_type:
                line.is_mapping = False
                line.product_id = False
                line.uom_id = False
                line.quantity = 0.0
                line.price_unit = 0.0
                line.tax_ids = False

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for line in self:
            if not line.product_id:
                continue
            line.name = line.product_id.display_name
            line.uom_id = line.product_id.uom_id

    def _get_or_create_route_product(self):
        self.ensure_one()
        if self.product_id:
            return self.product_id
        product_name = self.route_detail or self.name
        if not product_name:
            raise UserError(_(
                'Vui lòng nhập Chi tiết điểm đi & điểm đến hoặc Nội dung vận chuyển để tạo sản phẩm.'
            ))
        product = self.env['product.product'].create({
            'name': product_name[:200],
            'type': 'service',
            'sale_ok': True,
            'purchase_ok': True,
            'categ_id': self.service_type_id.id if self.service_type_id else False,
        })
        self.product_id = product.id
        return product

    def _prepare_sale_order_line_vals(self):
        self.ensure_one()
        product = self._get_or_create_route_product()
        uom = self.uom_id or product.uom_id
        return {
            'product_id': product.id,
            'name': self.name,
            'product_uom_qty': self.quantity,
            'product_uom_id': uom.id,
            'price_unit': self.price_unit,
            'tax_ids': [(6, 0, self.tax_ids.ids)],
            'att_appendix_line_id': self.id,
            'pickup_location': self.pickup_location,
            'delivery_location': self.delivery_location,
            'route_detail': self.route_detail,
            'vehicle_id': self.vehicle_id.id if self.vehicle_id else False,
            'vehicle_type': self.vehicle_type,
            'cargo_description': self.cargo_description,
            'transport_mode_id': self.transport_mode_id.id if self.transport_mode_id else False,  # ✅ thêm

        }

    def _prepare_purchase_order_line_vals(self):
        self.ensure_one()
        product = self._get_or_create_route_product()
        uom = self.uom_id or product.uom_id
        return {
            'product_id': product.id,
            'name': self.name,
            'product_qty': self.quantity,
            'product_uom_id': uom.id,
            'price_unit': self.price_unit,
            'taxes_id': [(6, 0, self.tax_ids.ids)],
            'att_appendix_line_id': self.id,
            'pickup_location': self.pickup_location,
            'delivery_location': self.delivery_location,
            'route_detail': self.route_detail,
            'vehicle_id': self.vehicle_id.id if self.vehicle_id else False,
            'vehicle_type': self.vehicle_type,
            'cargo_description': self.cargo_description,
            'transport_mode_id': self.transport_mode_id.id if self.transport_mode_id else False,  # ✅ thêm

        }



class ContractAppendixExtraLine(models.Model):
    _name = 'att.contract.appendix.extra.line'
    _description = 'Thông tin bổ sung phụ lục'
    _order = 'sequence, id'

    appendix_id = fields.Many2one(
        'att.contract.appendix',
        string='Phụ lục',
        required=True,
        ondelete='cascade',
    )

    line_id = fields.Many2one(
        'att.contract.appendix.line',
        string='Dòng phụ lục liên quan',
        ondelete='set null',
        domain="[('appendix_id', '=', parent.id)]",
    )

    sequence = fields.Integer(string='Thứ tự', default=10)

    key = fields.Char(
        string='Tên thông tin',
        required=True,
    )

    value = fields.Text(
        string='Giá trị',
    )

    note = fields.Text(
        string='Ghi chú',
    )