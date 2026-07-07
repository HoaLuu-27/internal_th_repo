from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    """SO đóng 2 vai:

    1. BÁO GIÁ (draft/sent, chưa gắn phụ lục) — thay att.quotation.request bán
       ở module cũ: dùng pricelist/template/portal native + tầng duyệt giá manager
       + report PDF động theo rpt_show_*.
    2. SO THỰC THI (sinh từ phụ lục, att_appendix_id có giá trị) — giá bị khóa
       theo phụ lục.
    """
    _inherit = 'sale.order'

    # QUAN HỆ: att_contract_id CHỈ dành cho BÁO GIÁ (SO draft thuộc HĐ nào) —
    # 1 HĐ ↔ N báo giá. SO THỰC THI không gắn field này (chỉ gắn phụ lục;
    # truy vết HĐ qua appendix.contract_id). Editable để gắn báo giá mới
    # (đổi giá) vào HĐ đang chạy — sau đó tạo PHỤ LỤC chứ không tạo HĐ mới.
    att_contract_id = fields.Many2one('att.contract', string='Hợp đồng NT',
                                      copy=False, index=True)
    att_appendix_id = fields.Many2one('att.contract.appendix', string='Phụ lục',
                                      copy=False, index=True, readonly=True)
    # Phân biệt SO báo giá vs SO thực thi cho filter/báo cáo
    att_is_execution = fields.Boolean('Là đơn thực thi', compute='_compute_att_is_execution',
                                       store=True)

    # ---- Vòng đời báo giá TH — chạy SONG SONG với state native (không chèn
    # state vào sale.order.state để khỏi vỡ portal/report/mail native).
    # Đây là chỗ trả lời "báo giá nào đã chốt": state 'won' = KH đã chốt giá,
    # và chỉ từ 'won' mới được tạo HĐNT. ----
    att_quote_state = fields.Selection([
        ('draft', 'Nháp'),
        ('pending', 'Chờ duyệt giá'),
        ('approved', 'Đã duyệt giá'),
        ('won', 'KH đã chốt'),
        ('contracted', 'Đã tạo HĐNT'),
    ], string='Trạng thái báo giá TH', default='draft', copy=False,
        tracking=True, index=True)

    # ---- Cấu hình cột hiển thị trên PDF báo giá (port từ module cũ) ----
    rpt_show_content = fields.Boolean('Nội dung vận chuyển', default=True)
    rpt_show_pickup = fields.Boolean('Điểm đi', default=True)
    rpt_show_delivery = fields.Boolean('Điểm đến', default=True)
    rpt_show_vehicle_id = fields.Boolean('Phương tiện', default=False)
    rpt_show_transport_mode = fields.Boolean('Hình thức vận chuyển', default=False)
    rpt_show_quantity = fields.Boolean('Số lượng', default=True)
    rpt_show_uom = fields.Boolean('Đơn vị tính', default=True)
    rpt_show_expected_date = fields.Boolean('Thời gian dự kiến', default=False)
    rpt_show_cargo_description = fields.Boolean('Mô tả hàng hóa', default=False)
    rpt_show_price_unit = fields.Boolean('Đơn giá', default=True)
    rpt_show_tax = fields.Boolean('Thuế', default=False)
    rpt_show_price_subtotal = fields.Boolean('Thành tiền chưa thuế', default=False)
    rpt_show_price_total = fields.Boolean('Tổng tiền', default=False)
    rpt_show_note = fields.Boolean('Ghi chú', default=True)

    # ---- Thuê ngoài: dòng SO không gắn xe (vehicle_id trống) = không xếp
    # được xe TH → cần tạo RFQ hỏi giá NCC ----
    att_outsource_line_count = fields.Integer(
        'Số dòng thiếu xe', compute='_compute_att_outsource_line_count',
        help='Số dòng dịch vụ chưa gán được xe TH — cần thuê ngoài NCC.')
    att_ncc_rfq_count = fields.Integer(
        'Số RFQ NCC', compute='_compute_att_ncc_rfq_count')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # BÁO GIÁ đánh số QT/2026/00001[/mã KH] — tách hẳn khỏi số S00001
            # của đơn thực thi để nhìn tên là biết loại chứng từ. Nhận diện:
            # mọi SO tạo tay đều là báo giá; SO thực thi sinh từ phụ lục luôn
            # có att_appendix_id trong vals → giữ số S native.
            if vals.get('name', '/') in ('/', False) and not vals.get('att_appendix_id'):
                name = self.env['ir.sequence'].next_by_code('attqc.sale.quotation')
                if name:
                    # Ghép mã khách hàng (field ref trên danh bạ) nếu có —
                    # nhìn số báo giá biết ngay của KH nào
                    partner = self.env['res.partner'].browse(vals.get('partner_id'))
                    if partner and partner.ref:
                        name = f'{name}/{partner.ref}'
                    vals['name'] = name
        return super().create(vals_list)

    @api.depends('att_appendix_id')
    def _compute_att_is_execution(self):
        for rec in self:
            rec.att_is_execution = bool(rec.att_appendix_id)

    @api.depends('order_line.vehicle_id', 'order_line.display_type')
    def _compute_att_outsource_line_count(self):
        for rec in self:
            rec.att_outsource_line_count = len(rec.order_line.filtered(
                lambda l: not l.display_type and l.product_id and not l.vehicle_id))

    def _compute_att_ncc_rfq_count(self):
        for rec in self:
            rec.att_ncc_rfq_count = self.env['purchase.order'].search_count([
                ('att_source_sale_order_id', '=', rec.id),
                ('att_is_execution', '=', False),
            ]) if rec.id else 0

    def action_create_ncc_rfq(self):
        """Mở form RFQ mới với SO nguồn prefill — onchange bên purchase sẽ
        tự đổ CHỈ NHỮNG DÒNG THIẾU XE (context att_only_missing_vehicle),
        giá để trống cho NCC báo. User chọn NCC, lưu, rồi duplicate cho
        các NCC khác để đủ ngưỡng 5-10 báo giá."""
        self.ensure_one()
        if self.state != 'sale':
            raise UserError(_('Chỉ SO đã xác nhận mới tạo RFQ thuê ngoài.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo RFQ NCC (thuê ngoài)'),
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_att_source_sale_order_id': self.id,
                'default_currency_id': self.currency_id.id,
                # Cờ báo onchange chỉ đổ dòng chưa gán xe TH
                'att_only_missing_vehicle': True,
            },
        }

    def action_view_ncc_rfqs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Báo giá NCC của %s') % self.name,
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('att_source_sale_order_id', '=', self.id),
                       ('att_is_execution', '=', False)],
            # Bấm New từ list này: RFQ mới prefill SO nguồn, onchange đổ ĐỦ dòng
            # (không lọc thiếu xe — lọc chỉ áp dụng cho nút đỏ "Dòng thiếu xe")
            'context': {'default_att_source_sale_order_id': self.id},
        }

    def _get_report_data(self):
        """Dict show_* cho report PDF báo giá động — abstract model sẽ inject."""
        self.ensure_one()
        return {
            'show_content': self.rpt_show_content,
            'show_pickup': self.rpt_show_pickup,
            'show_delivery': self.rpt_show_delivery,
            'show_vehicle_id': self.rpt_show_vehicle_id,
            'show_transport_mode': self.rpt_show_transport_mode,
            'show_quantity': self.rpt_show_quantity,
            'show_uom': self.rpt_show_uom,
            'show_expected_date': self.rpt_show_expected_date,
            'show_cargo_description': self.rpt_show_cargo_description,
            'show_price_unit': self.rpt_show_price_unit,
            'show_tax': self.rpt_show_tax,
            'show_price_subtotal': self.rpt_show_price_subtotal,
            'show_price_total': self.rpt_show_price_total,
            'show_note': self.rpt_show_note,
        }

    # ------------------------------------------------------------------
    # Duyệt giá nội bộ
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

    def _check_att_manager(self):
        """Chặn ở server — ẩn nút theo group là chưa đủ (RPC vẫn gọi được).
        LƯU Ý khi test: user admin thuộc MỌI group nên luôn pass; phải test
        bằng user thường không có group manager mới thấy chặn."""
        if not self.env.user.has_group(
                'att_quotations_contracts.group_tranghuy_managers_sale_purchase'):
            raise UserError(_('Chỉ Quản lý Sale/Purchase mới được thực hiện thao tác này.'))

    def action_send_quotation(self):
        """Nút "Gửi báo giá" — mở popup chọn kênh (Email / Zalo).

        Email → flow gửi mail native của SO; Zalo → hook action_send_attachment_file
        của module tích hợp Zalo. Gate duyệt giá áp cho mọi kênh (check trong wizard).
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Gửi báo giá'),
            'res_model': 'attqc.send.quotation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
            },
        }

    def action_att_request_approval(self):
        """Sales yêu cầu manager duyệt giá — bước bắt buộc trước khi gửi KH."""
        for rec in self:
            if not rec.order_line:
                raise UserError(_('Vui lòng nhập ít nhất một dòng báo giá.'))
            rec.att_quote_state = 'pending'
            rec.message_post(
                body=Markup(
                    '<b>%s</b> yêu cầu duyệt giá báo giá <b>%s</b> — KH <b>%s</b>.<br/>'
                    'Tổng tiền: <b>%s %s</b>'
                ) % (
                    self.env.user.name, rec.name, rec.partner_id.name,
                    '{:,.0f}'.format(rec.amount_total), rec.currency_id.name,
                ),
                partner_ids=rec._get_manager_partners().ids,
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_att_approve(self):
        """Manager duyệt giá."""
        self._check_att_manager()
        for rec in self:
            if rec.att_quote_state != 'pending':
                raise UserError(_('Chỉ duyệt được báo giá đang Chờ duyệt giá.'))
            rec.att_quote_state = 'approved'
            rec.message_post(
                body=Markup('<b>%s</b> đã duyệt giá báo giá <b>%s</b>.') % (
                    self.env.user.name, rec.name),
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_att_refuse(self):
        """Manager trả báo giá về nháp để sales sửa giá."""
        self._check_att_manager()
        for rec in self:
            rec.att_quote_state = 'draft'
            rec.message_post(
                body=Markup('<b>%s</b> trả báo giá <b>%s</b> về nháp để điều chỉnh.') % (
                    self.env.user.name, rec.name),
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_att_mark_won(self):
        """Đánh dấu KH ĐÃ CHỐT giá — điều kiện để tạo HĐNT.

        Đây là câu trả lời cho "báo giá nào đã chốt": nhìn att_quote_state='won'
        (có filter riêng "KH đã chốt" trên list)."""
        for rec in self:
            if rec.att_quote_state != 'approved':
                raise UserError(_('Báo giá phải được duyệt giá nội bộ trước khi ghi nhận KH chốt.'))
            rec.att_quote_state = 'won'
            rec.message_post(
                body=Markup('<b>%s</b> ghi nhận KH <b>%s</b> đã chốt báo giá <b>%s</b>.') % (
                    self.env.user.name, rec.partner_id.name, rec.name),
                message_type='notification', subtype_xmlid='mail.mt_note')

    # ------------------------------------------------------------------
    # KHÓA các nút native để flow không bị đi tắt
    # ------------------------------------------------------------------
    def action_quotation_send(self):
        """Chặn gửi báo giá cho KH khi chưa được manager duyệt giá."""
        for rec in self:
            if not rec.att_is_execution and rec.att_quote_state not in (
                    'approved', 'won', 'contracted'):
                raise UserError(_(
                    'Báo giá %s chưa được duyệt giá nội bộ — dùng nút '
                    '"Yêu cầu duyệt giá" trước khi gửi khách hàng.') % rec.name)
        return super().action_quotation_send()

    def _find_mail_template(self):
        """Hook native chọn template cho wizard gửi email — tráo sang template
        của module (gắn report báo giá TH) thay vì sale.email_template_edi_sale,
        nhờ đó PDF đính kèm là bản báo giá tùy biến của Trang Huy.

        Chỉ tráo khi đang gửi BÁO GIÁ (chưa confirm, không proforma) — đơn
        đã confirm/proforma vẫn đi đường native."""
        self.ensure_one()
        if not self.env.context.get('proforma') and self.state != 'sale':
            template = self.env.ref(
                'att_quotations_contracts.email_template_attqc_sale_quotation',
                raise_if_not_found=False)
            if template:
                return template
        return super()._find_mail_template()

    def action_confirm(self):
        """SO báo giá KHÔNG xác nhận trực tiếp thành đơn bán.

        Flow chuẩn: KH chốt → HĐNT → Phụ lục → SO thực thi (sinh từ phụ lục,
        att_is_execution=True) mới được confirm. Ngoại lệ: manager được confirm
        trực tiếp cho đơn lẻ B2C (Zalo) không qua hợp đồng.
        """
        for rec in self:
            if not rec.att_is_execution and not self.env.user.has_group(
                    'att_quotations_contracts.group_tranghuy_managers_sale_purchase'):
                raise UserError(_(
                    'Báo giá %s không xác nhận trực tiếp được.\n'
                    'Flow chuẩn: KH chốt giá → Tạo HĐNT → Phụ lục → SO thực thi.\n'
                    '(Đơn lẻ không qua hợp đồng cần Quản lý Sale/Purchase xác nhận.)'
                ) % rec.name)

            if rec.att_is_execution and rec.state in ('draft', 'sent'):
                if not rec.name or rec.name == '/' or rec.name.startswith('S'):
                    seq_name = self.env['ir.sequence'].next_by_code(
                        'attqc.sale.order.execution'
                    )
                    if seq_name:
                        partner_ref = rec.partner_id.ref
                        if partner_ref:
                            seq_name = f'{seq_name}/{partner_ref}'
                        rec.name = seq_name
        return super().action_confirm()

    # ------------------------------------------------------------------
    # Tạo HĐ nguyên tắc từ báo giá đã chốt
    # ------------------------------------------------------------------
    def action_create_att_contract(self):
        self.ensure_one()
        if self.att_contract_id:
            raise UserError(_('Báo giá này đã gắn hợp đồng %s rồi.') % self.att_contract_id.name)
        # Chỉ báo giá KH ĐÃ CHỐT mới được tạo HĐNT — đây là mắt xích
        # "chốt → hợp đồng" của flow
        if self.att_quote_state != 'won':
            raise UserError(_(
                'Chỉ báo giá ở trạng thái "KH đã chốt" mới được tạo hợp đồng.\n'
                'Flow: Duyệt giá nội bộ → Gửi KH → KH chốt → Tạo HĐNT.'))
        # Báo giá hết hiệu lực thì giá không còn cam kết — không kéo vào HĐ
        if self.validity_date and self.validity_date < fields.Date.today():
            raise UserError(_(
                'Báo giá %(bg)s đã hết hiệu lực từ %(ngay)s — giá trên báo giá '
                'không còn giá trị cam kết.\n'
                'Cập nhật lại hạn hiệu lực (nếu KH vẫn đồng ý giá cũ) hoặc làm '
                'báo giá mới trước khi tạo HĐNT.',
                bg=self.name, ngay=self.validity_date.strftime('%d/%m/%Y')))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo hợp đồng nguyên tắc'),
            'res_model': 'att.contract',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_contract_type': 'sale',
                'default_partner_id': self.partner_id.id,
                'default_source_sale_order_id': self.id,
                'default_payment_term_id': self.payment_term_id.id or False,
                'default_company_id': self.company_id.id,
                'default_currency_id': self.currency_id.id,
                'default_user_id': self.user_id.id or False,
            },
        }

    def action_view_att_contract(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'att.contract',
            'view_mode': 'form',
            'res_id': self.att_contract_id.id,
        }

    def action_create_att_appendix(self):
        """Báo giá đã chốt + đã thuộc HĐ đang chạy → tạo PHỤ LỤC giá mới
        (không tạo HĐ mới). Đây là flow đổi giá / bổ sung tuyến cho HĐ cũ."""
        self.ensure_one()
        if self.att_quote_state != 'won':
            raise UserError(_('Chỉ báo giá "KH đã chốt" mới được tạo phụ lục.'))
        if not self.att_contract_id or self.att_contract_id.state != 'running':
            raise UserError(_('Báo giá phải gắn với hợp đồng đang hiệu lực.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo phụ lục từ báo giá'),
            'res_model': 'att.contract.appendix',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_contract_id': self.att_contract_id.id,
                'default_appendix_type': 'sale',
                'default_partner_id': self.partner_id.id,
                'default_source_sale_order_id': self.id,
            },
        }


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    att_appendix_line_id = fields.Many2one('att.contract.appendix.line',
                                           string='Dòng phụ lục', copy=False,
                                           readonly=True, index=True)

    # ---- Field logistics dùng cho báo giá + đơn thực thi + report.
    # Tuyến đường = cặp Điểm đi/Điểm đến; loại xe xem qua vehicle_id (fleet) —
    # không có field text trùng vai (route_detail/vehicle_type đã bỏ). ----
    pickup_location = fields.Char(string='Điểm đi')
    delivery_location = fields.Char(string='Điểm đến')
    vehicle_id = fields.Many2one('fleet.vehicle', string='Phương tiện')
    transport_mode_id = fields.Many2one('att.transport.mode', string='Hình thức vận chuyển')
    cargo_description = fields.Text(string='Mô tả hàng hóa')
    expected_date = fields.Datetime(string='Thời gian dự kiến')
    att_line_note = fields.Text(string='Ghi chú báo giá')

    @api.onchange('price_unit')
    def _onchange_price_vs_appendix(self):
        """Cảnh báo khi sửa tay giá lệch với phụ lục — phụ lục là nguồn giá duy nhất."""
        for line in self:
            if not line.att_appendix_line_id:
                continue
            appendix_price = line.att_appendix_line_id.price_unit
            if line.price_unit != appendix_price:
                return {
                    'warning': {
                        'title': _('Giá lệch phụ lục'),
                        'message': _(
                            'Đơn giá vừa nhập (%(new)s) khác giá trên phụ lục %(pl)s '
                            '(%(old)s). Nếu cần đổi giá, hãy tạo phụ lục mới thay thế '
                            'thay vì sửa tay trên đơn.',
                            new='{:,.0f}'.format(line.price_unit),
                            pl=line.att_appendix_line_id.appendix_id.name,
                            old='{:,.0f}'.format(appendix_price),
                        ),
                    }
                }
