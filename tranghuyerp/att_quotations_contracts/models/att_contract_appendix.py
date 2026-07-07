import base64

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class ContractAppendix(models.Model):
    """Phụ lục hợp đồng — NƠI GIỮ GIÁ DUY NHẤT của cả flow.

    - Bán : kéo dòng giá từ SO báo giá gốc → sinh SO thực thi theo từng đợt đặt
    - Mua : kéo dòng giá từ RFQ thắng thầu → sinh PO, giá tự điền từ phụ lục
            (thay vai trò blanket order native nhưng không đụng purchase.requisition)
    - Đổi giá: tạo phụ lục MỚI thay phụ lục cũ (replaces_appendix_id),
      phụ lục cũ chuyển 'superseded' — không sửa đè phụ lục đã ký.
    """
    _name = 'att.contract.appendix'
    _description = 'Phụ lục hợp đồng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char('Số phụ lục', required=True, copy=False, readonly=True,
                       default='New', tracking=True, index=True)
    contract_id = fields.Many2one('att.contract', 'Hợp đồng', required=True,
                                  tracking=True, ondelete='restrict')
    appendix_type = fields.Selection([
        ('sale', 'Phụ lục bán'),
        ('purchase', 'Phụ lục mua'),
    ], string='Loại phụ lục', required=True, tracking=True, index=True)
    partner_id = fields.Many2one('res.partner', 'Đối tác', required=True, tracking=True)
    user_id = fields.Many2one('res.users', 'Người phụ trách',
                              default=lambda self: self.env.user, tracking=True)
    effective_date = fields.Date('Ngày hiệu lực', tracking=True)
    expired_date = fields.Date('Ngày hết hạn', tracking=True)
    company_id = fields.Many2one('res.company', 'Công ty', required=True,
                                 default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one('res.currency', 'Tiền tệ',
                                  default=lambda self: self.env.company.currency_id)

    # ---- Nguồn kéo dòng giá (báo giá native) ----
    source_sale_order_id = fields.Many2one(
        'sale.order', 'SO báo giá nguồn', copy=False,
        domain="[('partner_id', '=', partner_id)]",
        help='Phụ lục bán: kéo dòng giá từ SO báo giá KH đã chốt.')
    source_purchase_order_id = fields.Many2one(
        'purchase.order', 'RFQ nguồn', copy=False,
        domain="[('partner_id', '=', partner_id)]",
        help='Phụ lục mua: kéo dòng giá từ RFQ thắng thầu của NCC.')

    # ---- Thay thế phụ lục khi đổi giá ----
    replaces_appendix_id = fields.Many2one(
        'att.contract.appendix', 'Thay thế phụ lục', copy=False, tracking=True,
        domain="[('contract_id', '=', contract_id), ('state', 'in', ('confirmed', 'done'))]",
        help='Khi đổi giá: phụ lục này confirm thì phụ lục được chọn chuyển "Đã thay thế".')
    replaced_by_id = fields.Many2one('att.contract.appendix', 'Bị thay thế bởi',
                                     readonly=True, copy=False)

    # ---- Thông tin điều chỉnh giá dầu (phụ lục bán) ----
    fuel_ref_price = fields.Monetary('Giá dầu tham chiếu (VNĐ/lít)',
                                     currency_field='currency_id', tracking=True)
    fuel_ref_date = fields.Date('Ngày tham chiếu giá dầu', tracking=True)
    fuel_ratio = fields.Float('Tỷ trọng nhiên liệu (%)', default=30.0, tracking=True)
    fuel_note = fields.Text('Ghi chú dầu')

    appendix_line_ids = fields.One2many('att.contract.appendix.line', 'appendix_id',
                                        'Dòng phụ lục', copy=True)
    extra_line_ids = fields.One2many('att.contract.appendix.extra.line', 'appendix_id',
                                     'Thông tin bổ sung')

    amount_untaxed = fields.Monetary('Thành tiền chưa thuế', compute='_compute_amount',
                                     store=True, currency_field='currency_id')
    amount_tax = fields.Monetary('Tiền thuế', compute='_compute_amount',
                                 store=True, currency_field='currency_id')
    amount_total = fields.Monetary('Tổng tiền', compute='_compute_amount',
                                   store=True, currency_field='currency_id')

    # SO/PO thực thi sinh ra từ phụ lục (1 phụ lục → N đơn theo từng đợt)
    sale_order_ids = fields.One2many('sale.order', 'att_appendix_id', 'SO thực thi', readonly=True)
    purchase_order_ids = fields.One2many('purchase.order', 'att_appendix_id', 'PO thực thi', readonly=True)
    order_count = fields.Integer('Số đơn', compute='_compute_order_count')

    # Người đại diện ký = M2M contact (nhiều người ký được) — mặc định kế thừa
    # từ HĐ, sửa được theo từng phụ lục; 2 field text là computed cho report
    partner_representative_ids = fields.Many2many(
        'res.partner', 'att_appendix_representative_rel', 'appendix_id', 'partner_id',
        string='Người đại diện ký',
        domain="[('id', 'child_of', partner_id)]", tracking=True)
    partner_representative = fields.Char(
        'Người đại diện đối tác', compute='_compute_representative_display', store=True)
    partner_position = fields.Char(
        'Chức vụ người đại diện', compute='_compute_representative_display', store=True)

    @api.depends('partner_representative_ids', 'partner_representative_ids.function')
    def _compute_representative_display(self):
        for rec in self:
            reps = rec.partner_representative_ids
            rec.partner_representative = ', '.join(reps.mapped('name')) or False
            rec.partner_position = ', '.join(
                r.function for r in reps if r.function) or False

    state = fields.Selection([
        ('draft', 'Nháp'),
        ('sent_draft', 'Đã gửi nháp'),
        ('pending_approval', 'Chờ duyệt'),
        ('confirmed', 'Đã xác nhận'),
        ('done', 'Đang thực thi'),
        ('superseded', 'Đã thay thế'),
        ('cancelled', 'Đã hủy'),
    ], string='Trạng thái', default='draft', tracking=True)

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('appendix_line_ids.price_subtotal', 'appendix_line_ids.price_tax',
                 'appendix_line_ids.price_total', 'appendix_line_ids.is_mapping',
                 'appendix_line_ids.display_type')
    def _compute_amount(self):
        for rec in self:
            service_lines = rec.appendix_line_ids.filtered(
                lambda l: not l.display_type and l.is_mapping)
            rec.amount_untaxed = sum(service_lines.mapped('price_subtotal'))
            rec.amount_tax = sum(service_lines.mapped('price_tax'))
            rec.amount_total = sum(service_lines.mapped('price_total'))

    @api.depends('sale_order_ids', 'purchase_order_ids', 'appendix_type')
    def _compute_order_count(self):
        for rec in self:
            rec.order_count = (
                len(rec.sale_order_ids) if rec.appendix_type == 'sale'
                else len(rec.purchase_order_ids)
            )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                contract_id = vals.get('contract_id')
                if not contract_id:
                    vals['name'] = 'PL'
                    continue
                # Đánh số theo số LỚN NHẤT hiện có + 1 (không dùng search_count —
                # xóa PL giữa chừng sẽ sinh trùng tên)
                existing_names = self.search(
                    [('contract_id', '=', contract_id)]).mapped('name')
                max_num = 0
                for n in existing_names:
                    if n and n.startswith('PL') and n[2:].isdigit():
                        max_num = max(max_num, int(n[2:]))
                vals['name'] = 'PL%02d' % (max_num + 1)
        records = super().create(vals_list)
        for rec in records:
            # Kế thừa danh sách người ký từ HĐ nếu phụ lục chưa chọn riêng
            if rec.contract_id and not rec.partner_representative_ids:
                rec.partner_representative_ids = rec.contract_id.partner_representative_ids
        return records

    @api.constrains('effective_date', 'expired_date', 'contract_id')
    def _check_dates_vs_contract(self):
        """Ngày phụ lục phải khớp logic với HĐNT cha:
        - hết hạn PL > hiệu lực PL
        - PL phải BẮT ĐẦU hiệu lực trong thời hạn HĐ (không trước ngày hiệu
          lực HĐ, không sau ngày HĐ hết hạn — HĐ hết hạn thì gia hạn HĐ trước,
          không dùng phụ lục "đắp" lên hợp đồng chết).
        Ngày hết hạn PL được phép vượt hết hạn HĐ (phụ lục gia hạn là hợp lệ)."""
        for rec in self:
            if (rec.effective_date and rec.expired_date
                    and rec.expired_date <= rec.effective_date):
                raise ValidationError(_(
                    'Phụ lục %(pl)s: ngày hết hạn (%(exp)s) phải sau ngày hiệu lực '
                    '(%(eff)s).', pl=rec.name,
                    exp=rec.expired_date.strftime('%d/%m/%Y'),
                    eff=rec.effective_date.strftime('%d/%m/%Y')))
            contract = rec.contract_id
            if not contract or not rec.effective_date:
                continue
            if contract.effective_date and rec.effective_date < contract.effective_date:
                raise ValidationError(_(
                    'Phụ lục %(pl)s hiệu lực từ %(eff)s — TRƯỚC ngày hiệu lực của '
                    'hợp đồng %(hd)s (%(hd_eff)s). Phụ lục không thể có hiệu lực '
                    'trước hợp đồng cha.',
                    pl=rec.name, eff=rec.effective_date.strftime('%d/%m/%Y'),
                    hd=contract.name,
                    hd_eff=contract.effective_date.strftime('%d/%m/%Y')))
            if contract.expired_date and rec.effective_date > contract.expired_date:
                raise ValidationError(_(
                    'Phụ lục %(pl)s hiệu lực từ %(eff)s — SAU khi hợp đồng %(hd)s '
                    'đã hết hạn (%(hd_exp)s). Hãy gia hạn hợp đồng trước khi thêm '
                    'phụ lục mới.',
                    pl=rec.name, eff=rec.effective_date.strftime('%d/%m/%Y'),
                    hd=contract.name,
                    hd_exp=contract.expired_date.strftime('%d/%m/%Y')))

    @api.onchange('contract_id')
    def _onchange_contract_id(self):
        for rec in self:
            if not rec.contract_id:
                continue
            contract = rec.contract_id
            rec.appendix_type = contract.contract_type
            rec.partner_id = contract.partner_id
            rec.company_id = contract.company_id
            rec.currency_id = contract.currency_id
            rec.partner_representative_ids = contract.partner_representative_ids
            # Gợi ý sẵn nguồn kéo dòng từ chứng từ gốc của HĐ
            if contract.contract_type == 'sale':
                rec.source_sale_order_id = contract.source_sale_order_id
            else:
                rec.source_purchase_order_id = contract.source_purchase_order_id

    # ------------------------------------------------------------------
    # Kéo dòng giá từ báo giá native (SO / RFQ)
    # ------------------------------------------------------------------
    def action_load_source_lines(self):
        """Nạp dòng phụ lục từ SO báo giá (bán) hoặc RFQ thắng (mua).

        Thay cho việc nhập tay 3 lần (BG → PL → đơn) ở module cũ:
        dữ liệu logistics + giá copy 1:1 từ dòng báo giá native.
        """
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Chỉ nạp dòng khi phụ lục còn Nháp.'))

        commands = [(5, 0, 0)]  # xóa dòng hiện có, nạp lại từ nguồn
        if self.appendix_type == 'sale':
            source = self.source_sale_order_id
            if not source:
                raise UserError(_('Vui lòng chọn SO báo giá nguồn trước.'))
            # Giá từ báo giá hết hiệu lực không còn cam kết — không kéo vào PL
            if source.validity_date and source.validity_date < fields.Date.today():
                raise UserError(_(
                    'Báo giá nguồn %(bg)s đã hết hiệu lực từ %(ngay)s — cập nhật '
                    'hạn hiệu lực hoặc chọn báo giá khác trước khi nạp dòng.',
                    bg=source.name, ngay=source.validity_date.strftime('%d/%m/%Y')))
            for sol in source.order_line:
                if sol.display_type:
                    commands.append((0, 0, {
                        'display_type': sol.display_type,
                        'name': sol.name,
                        'is_mapping': False,
                    }))
                    continue
                commands.append((0, 0, {
                    'name': sol.name,
                    'product_id': sol.product_id.id or False,
                    'uom_id': sol.product_uom_id.id or False,
                    'quantity': sol.product_uom_qty,
                    'price_unit': sol.price_unit,
                    'tax_ids': [(6, 0, sol.tax_ids.ids)],
                    'pickup_location': sol.pickup_location,
                    'delivery_location': sol.delivery_location,
                    'vehicle_id': sol.vehicle_id.id or False,
                    'transport_mode_id': sol.transport_mode_id.id or False,
                    'cargo_description': sol.cargo_description,
                    'is_mapping': True,
                }))
        else:
            source = self.source_purchase_order_id
            if not source:
                raise UserError(_('Vui lòng chọn RFQ nguồn trước.'))
            # RFQ quá hạn chốt — giá NCC chào không còn cam kết
            if source.date_order and source.date_order.date() < fields.Date.today():
                raise UserError(_(
                    'Báo giá NCC nguồn %(bg)s đã quá hạn chốt từ %(ngay)s — xác '
                    'nhận lại giá với NCC (cập nhật Hạn chốt đơn) trước khi nạp dòng.',
                    bg=source.name, ngay=source.date_order.strftime('%d/%m/%Y')))
            for pol in source.order_line:
                if pol.display_type:
                    commands.append((0, 0, {
                        'display_type': pol.display_type,
                        'name': pol.name,
                        'is_mapping': False,
                    }))
                    continue
                commands.append((0, 0, {
                    'name': pol.name,
                    'product_id': pol.product_id.id or False,
                    'uom_id': pol.product_uom_id.id or False,
                    'quantity': pol.product_qty,
                    # Giá NCC đã chốt trên RFQ thắng — nguồn giá của phụ lục mua
                    'price_unit': pol.price_unit,
                    'tax_ids': [(6, 0, pol.tax_ids.ids)],
                    'pickup_location': pol.pickup_location,
                    'delivery_location': pol.delivery_location,
                    'vehicle_id': pol.vehicle_id.id or False,
                    'transport_mode_id': pol.transport_mode_id.id or False,
                    'cargo_description': pol.cargo_description,
                    'is_mapping': True,
                }))
        self.appendix_line_ids = commands

    # ------------------------------------------------------------------
    # Vòng đời phụ lục
    # ------------------------------------------------------------------
    def _get_manager_partners(self):
        group = self.env.ref(
            'att_quotations_contracts.group_tranghuy_managers_sale_purchase',
            raise_if_not_found=False)
        if not group:
            return self.env['res.partner']
        users = self.env['res.users'].search([
            ('group_ids', 'in', [group.id]),
            ('active', '=', True),
        ])
        return users.mapped('partner_id')

    def _get_mapping_lines(self):
        self.ensure_one()
        return self.appendix_line_ids.filtered(
            lambda l: not l.display_type and l.is_mapping)

    def action_send_quotation(self):
        """Nút "Gửi bản nháp" — popup chọn kênh gửi phụ lục cho đối tác
        (Email / Zalo; phụ lục mua thêm kênh Gọi điện)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Gửi bản nháp phụ lục'),
            'res_model': 'attqc.send.quotation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
                'attqc_allow_call': self.appendix_type == 'purchase',
            },
        }

    def action_send_draft(self):
        self.ensure_one()
        if not self.appendix_line_ids:
            raise UserError(_('Vui lòng nhập ít nhất một dòng phụ lục.'))
        template = self.env.ref('att_quotations_contracts.email_template_appendix_draft',
                                raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=True)
        self.state = 'sent_draft'

    def action_request_approval(self):
        for rec in self:
            if not rec._get_mapping_lines():
                raise UserError(_('Cần có ít nhất một dòng dịch vụ có giá.'))
            rec.state = 'pending_approval'
            rec.message_post(
                body=Markup(
                    '<b>%s</b> yêu cầu duyệt phụ lục <b>%s</b> với đối tác <b>%s</b>.<br/>'
                    'Tổng tiền: <b>%s %s</b>'
                ) % (
                    self.env.user.name, rec.name, rec.partner_id.name,
                    '{:,.0f}'.format(rec.amount_total), rec.currency_id.name,
                ),
                partner_ids=rec._get_manager_partners().ids,
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_confirm(self):
        """Manager duyệt giá. SO/PO do user tự tạo bằng nút riêng sau khi PL ký."""
        if not self.env.user.has_group(
                'att_quotations_contracts.group_tranghuy_managers_sale_purchase'):
            raise UserError(_('Chỉ Quản lý Sale/Purchase mới được duyệt phụ lục.'))
        for rec in self:
            if not rec._get_mapping_lines():
                raise UserError(_('Phụ lục cần có ít nhất một dòng dịch vụ.'))
            rec.state = 'confirmed'
            # Đổi giá: phụ lục mới confirm → phụ lục cũ tự chuyển "Đã thay thế".
            # SO/PO tạo sau thời điểm này chỉ lấy giá từ phụ lục mới.
            if rec.replaces_appendix_id and rec.replaces_appendix_id.state in ('confirmed', 'done'):
                rec.replaces_appendix_id.write({'state': 'superseded',
                                                'replaced_by_id': rec.id})
                rec.replaces_appendix_id.message_post(
                    body=Markup('Phụ lục này đã được thay thế bởi <b>%s</b>.') % rec.name,
                    message_type='notification', subtype_xmlid='mail.mt_note')

    def action_send_signed(self):
        self.ensure_one()
        # Không gán biến vào _ để tránh đè hàm dịch _() import ở đầu file
        pdf_content, _dummy = self.env['ir.actions.report']._render_qweb_pdf(
            'att_quotations_contracts.report_att_appendix', res_ids=[self.id])
        attachment = self.env['ir.attachment'].create({
            'name': f'PL_signed_{self.name}.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        template = self.env.ref('att_quotations_contracts.email_template_appendix_signed',
                                raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=True)
        self.message_post(
            body=Markup(
                '<b>%s</b> đã gửi bản phụ lục đã ký <b>%s</b> đến <b>%s</b> (%s).'
            ) % (self.env.user.name, self.name, self.partner_id.name,
                 self.partner_id.email or 'không có email'),
            attachment_ids=[attachment.id],
            message_type='notification', subtype_xmlid='mail.mt_note')

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state == 'superseded':
                raise UserError(_('Phụ lục đã bị thay thế — không đưa về nháp được.'))
        self.write({'state': 'draft'})

    # ------------------------------------------------------------------
    # Sinh SO/PO thực thi — giá LUÔN lấy từ dòng phụ lục
    # ------------------------------------------------------------------
    def _check_can_create_order(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'done'):
            raise UserError(_('Chỉ phụ lục đã xác nhận mới được tạo đơn hàng.'))
        if not self._get_mapping_lines():
            raise UserError(_('Không có dòng dịch vụ để tạo đơn.'))

    def action_create_sale_order(self):
        """Tạo SO thực thi (nháp) từ phụ lục bán — 1 phụ lục có thể sinh nhiều SO theo đợt."""
        for rec in self:
            rec._check_can_create_order()
            if rec.appendix_type != 'sale':
                raise UserError(_('Chỉ phụ lục bán mới tạo đơn bán hàng.'))
            order_lines = [(0, 0, line._prepare_sale_order_line_vals())
                           for line in rec._get_mapping_lines()]
            # SO thực thi CHỈ gắn phụ lục, KHÔNG gắn att_contract_id —
            # trên sale.order field đó dành riêng cho BÁO GIÁ thuộc HĐ;
            # truy vết HĐ của đơn thực thi đi qua phụ lục (appendix.contract_id)
            sale_order = self.env['sale.order'].create({
                'partner_id': rec.partner_id.id,
                'company_id': rec.company_id.id,
                'currency_id': rec.currency_id.id,
                'att_appendix_id': rec.id,
                'order_line': order_lines,
            })
            # Để SO ở NHÁP cho user rà soát số lượng thực tế từng đợt rồi tự confirm
            # (khác module cũ auto-confirm ngay — dễ sai số lượng)
            rec.state = 'done'
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'sale.order',
                'view_mode': 'form',
                'res_id': sale_order.id,
            }

    def action_create_purchase_order(self):
        """Tạo PO thực thi (nháp) từ phụ lục mua — giá tự điền từ phụ lục
        (đây chính là hành vi hữu ích của blanket order, tự làm để không
        phải dùng purchase.requisition).

        Header kế thừa trực tiếp từ QTM (RFQ thắng thầu — source_purchase_order_id):
        SO nguồn, điều khoản thanh toán, người mua, mã NCC, origin — để PO
        thực thi truy vết được về báo giá mua và nhu cầu bán gốc. Dòng + giá
        vẫn lấy từ phụ lục (nguồn giá duy nhất)."""
        for rec in self:
            rec._check_can_create_order()
            if rec.appendix_type != 'purchase':
                raise UserError(_('Chỉ phụ lục mua mới tạo Purchase Order.'))
            order_lines = [(0, 0, line._prepare_purchase_order_line_vals())
                           for line in rec._get_mapping_lines()]
            po_vals = {
                'partner_id': rec.partner_id.id,
                'company_id': rec.company_id.id,
                'currency_id': rec.currency_id.id,
                'att_contract_id': rec.contract_id.id,
                'att_appendix_id': rec.id,
                # Đánh dấu đơn thực thi để không lẫn vào màn RFQ mời thầu native
                'att_is_execution': True,
                'origin': rec.name,
                'order_line': order_lines,
            }
            source_rfq = rec.source_purchase_order_id
            if source_rfq:
                po_vals.update({
                    'origin': '%s, %s' % (source_rfq.name, rec.name),
                    'att_source_sale_order_id':
                        source_rfq.att_source_sale_order_id.id or False,
                    'payment_term_id': source_rfq.payment_term_id.id or False,
                    'user_id': source_rfq.user_id.id or False,
                    'partner_ref': source_rfq.partner_ref or False,
                })
            purchase_order = self.env['purchase.order'].create(po_vals)
            rec.state = 'done'
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order',
                'view_mode': 'form',
                'res_id': purchase_order.id,
            }

    def action_view_orders(self):
        self.ensure_one()
        if self.appendix_type == 'sale':
            return {
                'type': 'ir.actions.act_window',
                'name': _('SO thực thi'),
                'res_model': 'sale.order',
                'view_mode': 'list,form',
                'domain': [('att_appendix_id', '=', self.id)],
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('PO thực thi'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('att_appendix_id', '=', self.id)],
        }


class ContractAppendixLine(models.Model):
    _name = 'att.contract.appendix.line'
    _description = 'Dòng phụ lục hợp đồng'
    _order = 'sequence, id'

    appendix_id = fields.Many2one('att.contract.appendix', string='Phụ lục',
                                  required=True, ondelete='cascade')
    sequence = fields.Integer(string='Thứ tự', default=10)
    display_type = fields.Selection([
        ('line_section', 'Tiêu đề nhóm'),
        ('line_note', 'Ghi chú'),
    ], string='Loại dòng', default=False)
    is_mapping = fields.Boolean(
        string='Tạo SO/PO', default=True,
        help='Nếu bật, dòng này sẽ được dùng để tạo dòng SO/PO.')
    # Tách khỏi is_mapping: một dòng có thể lên SO/PO nhưng không muốn phô
    # trong file PDF gửi đối tác (và ngược lại) — mirror tab cấu hình PDF
    # của SO/PO nhưng ở mức DÒNG thay vì mức cột
    rpt_include = fields.Boolean(
        string='In vào PDF', default=True,
        help='Nếu bật, dòng này xuất hiện trong file PDF phụ lục khi in/gửi đối tác.')

    name = fields.Text(string='Nội dung vận chuyển', required=True)
    service_type_id = fields.Many2one('product.category', string='Nhóm dịch vụ')
    product_id = fields.Many2one('product.product', string='Dịch vụ',
                                 domain="[('type', '=', 'service')]", copy=False)
    uom_id = fields.Many2one('uom.uom', string='Đơn vị tính')
    quantity = fields.Float(string='Số lượng', default=1.0)
    load_capacity = fields.Char(string='Tải trọng', help='Ví dụ: ≤5 tấn')
    # Tuyến = cặp Nơi đi/Nơi đến; phương tiện dùng vehicle_id (fleet) —
    # route_detail/vehicle_type dạng text đã bỏ vì trùng vai
    pickup_location = fields.Char(string='Nơi đi')
    delivery_location = fields.Char(string='Nơi đến')
    vehicle_id = fields.Many2one('fleet.vehicle', string='Phương tiện')
    transport_mode_id = fields.Many2one('att.transport.mode', string='Hình thức vận chuyển')
    cargo_description = fields.Text(string='Mô tả hàng hóa')

    price_unit = fields.Monetary(string='Đơn giá (chưa VAT)', currency_field='currency_id')
    tax_ids = fields.Many2many('account.tax', string='Thuế')
    currency_id = fields.Many2one(related='appendix_id.currency_id', store=True, readonly=True)
    price_subtotal = fields.Monetary(string='Thành tiền chưa thuế', compute='_compute_amount',
                                     store=True, currency_field='currency_id')
    price_tax = fields.Monetary(string='Tiền thuế', compute='_compute_amount',
                                store=True, currency_field='currency_id')
    price_total = fields.Monetary(string='Tổng tiền', compute='_compute_amount',
                                  store=True, currency_field='currency_id')
    extra_note = fields.Text(string='Ghi chú')

    @api.depends('quantity', 'price_unit', 'tax_ids', 'display_type', 'is_mapping')
    def _compute_amount(self):
        for line in self:
            if line.display_type or not line.is_mapping:
                line.price_subtotal = line.price_tax = line.price_total = 0.0
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
            if line.product_id:
                line.name = line.product_id.display_name
                line.uom_id = line.product_id.uom_id

    def _get_or_create_route_product(self):
        """Dòng không gắn dịch vụ sẵn → tạo product service theo tuyến để lên SO/PO."""
        self.ensure_one()
        if self.product_id:
            return self.product_id
        # Tên product: ưu tiên tuyến "Nơi đi - Nơi đến", fallback nội dung dòng
        route = ' - '.join(p for p in (self.pickup_location, self.delivery_location) if p)
        product_name = route or self.name
        if not product_name:
            raise UserError(_(
                'Vui lòng nhập Nơi đi/Nơi đến hoặc Nội dung vận chuyển để tạo sản phẩm.'))
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
            'price_unit': self.price_unit,  # giá từ phụ lục — nguồn giá duy nhất
            'tax_ids': [(6, 0, self.tax_ids.ids)],
            'att_appendix_line_id': self.id,
            'pickup_location': self.pickup_location,
            'delivery_location': self.delivery_location,
            'vehicle_id': self.vehicle_id.id or False,
            'cargo_description': self.cargo_description,
            'transport_mode_id': self.transport_mode_id.id or False,
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
            'price_unit': self.price_unit,  # giá từ phụ lục — nguồn giá duy nhất
            'tax_ids': [(6, 0, self.tax_ids.ids)],
            'att_appendix_line_id': self.id,
            'pickup_location': self.pickup_location,
            'delivery_location': self.delivery_location,
            'vehicle_id': self.vehicle_id.id or False,
            'cargo_description': self.cargo_description,
            'transport_mode_id': self.transport_mode_id.id or False,
        }


class ContractAppendixExtraLine(models.Model):
    _name = 'att.contract.appendix.extra.line'
    _description = 'Thông tin bổ sung phụ lục'
    _order = 'sequence, id'

    appendix_id = fields.Many2one('att.contract.appendix', string='Phụ lục',
                                  required=True, ondelete='cascade')
    line_id = fields.Many2one('att.contract.appendix.line', string='Dòng phụ lục liên quan',
                              ondelete='set null',
                              domain="[('appendix_id', '=', parent.id)]")
    sequence = fields.Integer(string='Thứ tự', default=10)
    key = fields.Char(string='Tên thông tin', required=True)
    value = fields.Text(string='Giá trị')
    note = fields.Text(string='Ghi chú')
