from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    """RFQ = báo giá mua (thay att.quotation.request purchase ở module cũ).

    Flow: SO confirm + hết xe TH → tạo RFQ cho NCC (gắn SO nguồn) → duplicate
    cho các NCC khác CÙNG SO NGUỒN (nhóm báo giá gom theo att_source_sale_order_id,
    không dùng purchase_requisition) → so giá → "Chốt NCC thắng thầu" (rule
    tối thiểu N báo giá cùng nhóm) → Tạo HĐK/phụ lục kéo giá từ RFQ thắng → PO.
    """
    _inherit = 'purchase.order'

    # QUAN HỆ phía mua: att_contract_id dùng cho CẢ báo giá (RFQ thuộc HĐ)
    # lẫn PO thực thi (mua được phép tạo PO từ HĐNT/phụ lục) — phân biệt
    # bằng cờ att_is_execution, KHÔNG suy từ state native.
    att_contract_id = fields.Many2one('att.contract', string='Hợp đồng NT',
                                      copy=False, index=True)
    att_appendix_id = fields.Many2one('att.contract.appendix', string='Phụ lục',
                                      copy=False, index=True, readonly=True)
    att_source_sale_order_id = fields.Many2one(
        'sale.order', string='SO nguồn (nhu cầu thuê ngoài)', copy=True, index=True,
        help='Đơn bán làm phát sinh nhu cầu thuê NCC (khi hết xe TH).')
    # Cờ phân biệt PO THỰC THI (sinh từ phụ lục/HĐ) với RFQ MỜI THẦU.
    # Phải là field thường (không compute từ att_contract_id) vì RFQ thắng thầu
    # cũng được gắn att_contract_id nhưng nó vẫn là báo giá, không phải đơn thực thi.
    # Dùng để loại PO thực thi khỏi màn RFQ native (draft = quotation sẽ bị lẫn).
    att_is_execution = fields.Boolean('Là đơn thực thi', default=False,
                                      copy=False, index=True)

    # ---- Vòng đời báo giá mua — mirror phía bán. "Chốt" ở đây nghĩa là CHỌN
    # NCC THẮNG THẦU (không phải confirm thành PO như native — nút Confirm
    # native đã ẩn với RFQ mời thầu). ----
    att_quote_state = fields.Selection([
        ('draft', 'Nháp'),
        ('won', 'Đã chốt NCC'),
        ('contracted', 'Đã tạo HĐNT'),
        ('lost', 'Không chọn'),
    ], string='Trạng thái báo giá TH', default='draft', copy=False,
        tracking=True, index=True)

    # Số RFQ trong cùng nhóm alternatives (kể cả chính nó) — phục vụ rule tối thiểu
    att_rfq_group_count = fields.Integer('Số RFQ trong nhóm',
                                         compute='_compute_att_rfq_group_count')

    @api.onchange('att_source_sale_order_id')
    def _onchange_att_source_sale_order_id(self):
        """Chọn SO nguồn → đổ toàn bộ dữ liệu nhu cầu vận chuyển từ SO vào RFQ,
        TRỪ GIÁ (price_unit = 0 — NCC sẽ tự báo giá của họ).

        Không copy: giá bán (là giá TH chào KH, không đưa cho NCC xem),
        thuế bán (thuế mua khác thuế bán), xe TH (thuê ngoài thì xe là của NCC).
        """
        # Cờ từ smart button "Tạo RFQ NCC" trên SO: chỉ đổ dòng CHƯA GÁN XE TH
        # (vehicle_id trống = không xếp được xe nhà → phải thuê ngoài).
        # Chọn SO thủ công (hỏi giá đầu vào trước báo giá) thì đổ đủ mọi dòng.
        only_missing_vehicle = self.env.context.get('att_only_missing_vehicle')
        for rec in self:
            if not rec.att_source_sale_order_id or rec.att_is_execution:
                continue
            source = rec.att_source_sale_order_id
            commands = [(5, 0, 0)]  # nạp lại từ đầu theo SO vừa chọn
            skipped = 0
            for sol in source.order_line:
                if only_missing_vehicle and not sol.display_type and sol.vehicle_id:
                    continue  # dòng đã có xe TH chạy — không cần thuê ngoài
                if sol.display_type:
                    commands.append((0, 0, {
                        'display_type': sol.display_type,
                        'name': sol.name,
                    }))
                    continue
                if not sol.product_id:
                    # PO line bắt buộc có product — dòng SO không có thì bỏ qua
                    skipped += 1
                    continue
                commands.append((0, 0, {
                    'product_id': sol.product_id.id,
                    'name': sol.name,
                    'product_qty': sol.product_uom_qty,
                    'product_uom_id': sol.product_uom_id.id or False,
                    'price_unit': 0.0,  # NCC điền giá — không lộ giá bán của TH
                    'pickup_location': sol.pickup_location,
                    'delivery_location': sol.delivery_location,
                    'transport_mode_id': sol.transport_mode_id.id or False,
                    'cargo_description': sol.cargo_description,
                }))
            rec.order_line = commands
            if skipped:
                return {
                    'warning': {
                        'title': _('Bỏ qua %d dòng') % skipped,
                        'message': _(
                            '%d dòng trên SO không có sản phẩm/dịch vụ nên không '
                            'đưa vào RFQ được — kiểm tra lại SO nguồn.') % skipped,
                    }
                }

    def _get_sibling_rfqs(self):
        """Các báo giá NCC CÙNG NHU CẦU (bao gồm chính nó).

        Gom nhóm theo SO nguồn (att_source_sale_order_id) — đúng rule
        "5-10 báo giá cho SO đó". Không phụ thuộc purchase_requisition
        (đã bỏ khỏi depends) — RFQ không gắn SO nguồn thì đứng một mình.
        """
        self.ensure_one()
        if self.att_source_sale_order_id:
            return self.search([
                ('att_source_sale_order_id', '=', self.att_source_sale_order_id.id),
                ('att_is_execution', '=', False),
                ('state', '!=', 'cancel'),
            ])
        return self

    @api.depends('att_source_sale_order_id')
    def _compute_att_rfq_group_count(self):
        for rec in self:
            rec.att_rfq_group_count = len(rec._get_sibling_rfqs()) if rec.id else 1

    def _get_min_rfq_threshold(self):
        """Ngưỡng tối thiểu số báo giá NCC trước khi được chốt/tạo HĐK — chỉnh
        trong System Parameters (attqc.min_purchase_rfq), không phải sửa code.
        Interview ghi 10 NCC/tuyến, rule vận hành hiện tại là 5 → để config."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'attqc.min_purchase_rfq', '5')
        try:
            return int(raw)
        except ValueError:
            return 5

    def _check_min_rfq_threshold(self):
        self.ensure_one()
        threshold = self._get_min_rfq_threshold()
        count = len(self._get_sibling_rfqs())
        if count < threshold:
            raise UserError(_(
                'Cần tối thiểu %(min)d báo giá NCC cho cùng nhu cầu (SO nguồn) '
                'trước khi chốt NCC.\n'
                'Hiện tại: %(cur)d/%(min)d — duplicate RFQ này cho các NCC khác '
                '(giữ nguyên SO nguồn để được tính chung nhóm).',
                min=threshold, cur=count))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # BÁO GIÁ MUA đánh số QTM/2026/00001[/mã NCC] — tách khỏi P00001
            # của PO thực thi (sinh từ phụ lục/HĐ, có att_is_execution trong vals).
            # Mã NCC = field ref trên danh bạ (interview: mã NCC thống nhất mã KH).
            # Lưu ý: PO sinh tự động từ tồn kho/procurement (nếu sau này dùng)
            # cũng sẽ dính số QTM — khi đó cần thêm điều kiện nhận diện.
            if vals.get('name', '/') in ('/', False) and not vals.get('att_is_execution'):
                name = self.env['ir.sequence'].next_by_code('attqc.purchase.quotation')
                if name:
                    partner = self.env['res.partner'].browse(vals.get('partner_id'))
                    if partner and partner.ref:
                        name = f'{name}/{partner.ref}'
                    vals['name'] = name
        return super().create(vals_list)

    def action_send_quotation(self):
        """Nút "Gửi báo giá" — mở popup chọn kênh (Email / Zalo / Gọi điện NCC)."""
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
                # Chiều mua → bật thêm kênh gọi điện trong wizard
                'attqc_allow_call': True,
            },
        }

    def action_rfq_send(self):
        """Giữ nguyên flow gửi email native (wizard mail.compose.message),
        CHỈ tráo template sang template của module — template này gắn
        report_template_ids là report RFQ tùy biến của Trang Huy nên PDF
        đính kèm sẽ là bản yêu cầu báo giá TH thay vì report native.

        Chỉ tráo cho RFQ mời thầu (chưa phải PO thực thi, còn ở draft/sent) —
        PO thực thi/đã confirm vẫn dùng template native của Purchase.
        """
        action = super().action_rfq_send()
        if self.att_is_execution or self.state not in ('draft', 'sent'):
            return action
        template = self.env.ref(
            'att_quotations_contracts.email_template_attqc_purchase_quotation',
            raise_if_not_found=False)
        if template and isinstance(action, dict) and action.get('context'):
            ctx = dict(action['context'])
            ctx['default_template_id'] = template.id
            action['context'] = ctx
        return action

    def _action_call_ncc(self):
        """Kênh gọi điện: tạo cuộc gọi VoIP cho NCC hỏi giá.

        Có module voip thì tạo record voip.call; không có thì fallback
        activity "Gọi điện" gán người phụ trách — không chết vì thiếu voip.
        """
        self.ensure_one()
        if 'voip.call' in self.env:
            self.env['voip.call'].create({
                'partner_id': self.partner_id.id,
                'user_id': self.user_id.id or self.env.user.id,
                'phone_number': self.partner_id.phone or '',
                'direction': 'outgoing',
            })
        else:
            self.activity_schedule(
                'mail.mail_activity_data_call',
                user_id=self.user_id.id or self.env.user.id,
                summary=_('Gọi NCC %s hỏi giá cho %s') % (self.partner_id.name, self.name),
            )
        # Đã liên hệ NCC → chuyển RFQ sang "Đã gửi" như đường email
        if self.state == 'draft':
            self.write({'state': 'sent'})
        self.message_post(
            body=Markup('Đã tạo cuộc gọi hỏi giá NCC <b>%s</b> (%s).') % (
                self.partner_id.name, self.partner_id.phone or 'chưa có SĐT'),
            message_type='notification', subtype_xmlid='mail.mt_note')
        return True

    def action_att_mark_won(self):
        """CHỐT NCC thắng thầu — đây mới là nghĩa "confirm quotation" của
        nghiệp vụ mua (không phải biến thành PO). Điều kiện: đủ ngưỡng
        5-10 báo giá cùng SO nguồn."""
        self._check_att_manager()
        for rec in self:
            if rec.att_is_execution:
                raise UserError(_('Đơn thực thi không phải báo giá để chốt.'))
            if rec.att_quote_state != 'draft':
                raise UserError(_('Báo giá %s đã được xử lý rồi.') % rec.name)
            rec._check_min_rfq_threshold()
            rec.att_quote_state = 'won'
            rec.message_post(
                body=Markup(
                    '<b>%s</b> chốt NCC <b>%s</b> thắng thầu (báo giá <b>%s</b>).'
                ) % (self.env.user.name, rec.partner_id.name, rec.name),
                message_type='notification', subtype_xmlid='mail.mt_note')

    # ------------------------------------------------------------------
    # Tạo HĐK từ RFQ thắng thầu
    # ------------------------------------------------------------------
    def _check_att_manager(self):
        """Chặn ở server — user admin thuộc mọi group nên khi test phải dùng
        user thường không có group manager mới thấy chặn."""
        if not self.env.user.has_group(
                'att_quotations_contracts.group_tranghuy_managers_sale_purchase'):
            raise UserError(_('Chỉ Quản lý Sale/Purchase mới được thực hiện thao tác này.'))

    def button_confirm(self):
        """RFQ mời thầu KHÔNG xác nhận trực tiếp thành PO.

        Flow chuẩn: chốt NCC → HĐNT → Phụ lục → PO thực thi (att_is_execution)
        mới confirm tự do. Ngoại lệ: manager được confirm RFQ trực tiếp
        (trường hợp thuê chuyến lẻ gấp không qua hợp đồng).
        """
        for rec in self:
            if not rec.att_is_execution and not self.env.user.has_group(
                    'att_quotations_contracts.group_tranghuy_managers_sale_purchase'):
                raise UserError(_(
                    'RFQ %s là báo giá mời thầu — không xác nhận trực tiếp được.\n'
                    'Flow chuẩn: chốt NCC → Tạo HĐNT → Phụ lục → PO thực thi.\n'
                    '(Thuê chuyến lẻ gấp cần Quản lý Sale/Purchase xác nhận.)'
                ) % rec.name)
        return super().button_confirm()

    def action_create_att_contract(self):
        self.ensure_one()
        # Chốt NCC + tạo HĐK là quyết định của quản lý — chặn từ server
        self._check_att_manager()
        if self.att_contract_id:
            raise UserError(_('RFQ này đã gắn hợp đồng %s rồi.') % self.att_contract_id.name)
        # Chỉ báo giá ĐÃ CHỐT NCC mới được tạo HĐNT (ngưỡng 5-10 báo giá
        # đã được kiểm ở bước chốt)
        if self.att_quote_state != 'won':
            raise UserError(_(
                'Chỉ báo giá ở trạng thái "Đã chốt NCC" mới được tạo hợp đồng.\n'
                'Flow: tạo đủ %d báo giá NCC cùng SO nguồn → so sánh → '
                'Chốt NCC → Tạo HĐNT.') % self._get_min_rfq_threshold())
        # NCC đã có HĐK đang hiệu lực → không tạo mới, chỉ cần phụ lục giá mới
        existing = self.env['att.contract'].search([
            ('contract_type', '=', 'purchase'),
            ('partner_id', '=', self.partner_id.id),
            ('company_id', '=', self.company_id.id),
            ('state', '=', 'running'),
        ], limit=1)
        if existing:
            raise UserError(_(
                'NCC %(ncc)s đã có hợp đồng nguyên tắc đang hiệu lực (%(hd)s).\n'
                'Hãy tạo PHỤ LỤC mới trên hợp đồng đó (kéo giá từ RFQ này) '
                'thay vì tạo hợp đồng mới.',
                ncc=self.partner_id.name, hd=existing.name))
        # Kiểm lại ngưỡng lần nữa trước khi tạo HĐ — phòng RFQ cùng nhóm
        # bị hủy sau bước chốt NCC làm nhóm tụt dưới mức tối thiểu
        self._check_min_rfq_threshold()
        # Báo giá NCC quá hạn chốt (Order Deadline) → giá NCC chào không còn
        # cam kết — xác nhận lại với NCC (sửa deadline) trước khi kéo vào HĐ
        if self.date_order and self.date_order.date() < fields.Date.today():
            raise UserError(_(
                'Báo giá NCC %(bg)s đã quá hạn chốt từ %(ngay)s — giá NCC chào '
                'không còn giá trị cam kết.\n'
                'Xác nhận lại giá với NCC (cập nhật Hạn chốt đơn) trước khi '
                'tạo HĐNT.',
                bg=self.name, ngay=self.date_order.strftime('%d/%m/%Y')))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo hợp đồng nguyên tắc NCC'),
            'res_model': 'att.contract',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_contract_type': 'purchase',
                'default_partner_id': self.partner_id.id,
                'default_source_purchase_order_id': self.id,
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
        """RFQ đã chốt NCC + NCC đã có HĐ đang chạy → tạo PHỤ LỤC giá mới
        (kéo giá từ RFQ này), không tạo HĐ mới."""
        self.ensure_one()
        if self.att_quote_state != 'won':
            raise UserError(_('Chỉ báo giá "Đã chốt NCC" mới được tạo phụ lục.'))
        if not self.att_contract_id or self.att_contract_id.state != 'running':
            raise UserError(_('Báo giá phải gắn với hợp đồng đang hiệu lực của NCC.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo phụ lục từ RFQ'),
            'res_model': 'att.contract.appendix',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_contract_id': self.att_contract_id.id,
                'default_appendix_type': 'purchase',
                'default_partner_id': self.partner_id.id,
                'default_source_purchase_order_id': self.id,
            },
        }


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    att_appendix_line_id = fields.Many2one('att.contract.appendix.line',
                                           string='Dòng phụ lục', copy=False,
                                           readonly=True, index=True)

    # ---- Field logistics — trùng bộ với sale.order.line để map 1:1 qua phụ lục ----
    pickup_location = fields.Char(string='Điểm đi')
    delivery_location = fields.Char(string='Điểm đến')
    vehicle_id = fields.Many2one('fleet.vehicle', string='Phương tiện')
    transport_mode_id = fields.Many2one('att.transport.mode', string='Hình thức vận chuyển')
    cargo_description = fields.Text(string='Mô tả hàng hóa')

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
                            '(%(old)s). Nếu NCC đổi giá, hãy tạo phụ lục mới thay thế '
                            'thay vì sửa tay trên PO.',
                            new='{:,.0f}'.format(line.price_unit),
                            pl=line.att_appendix_line_id.appendix_id.name,
                            old='{:,.0f}'.format(appendix_price),
                        ),
                    }
                }
