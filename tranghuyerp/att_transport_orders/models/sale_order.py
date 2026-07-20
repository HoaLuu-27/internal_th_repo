from markupsafe import Markup

from odoo import api, fields, models, _


class SaleOrderLine(models.Model):
    """Field vận chuyển trên dòng SO — đặt ở att_transport_orders (lớp vận
    tải) để CẢ báo giá (att_contract_management) LẪN điều vận đều dùng chung."""
    _inherit = 'sale.order.line'

    pickup_location = fields.Char(string='Điểm đi')
    pickup_address_id = fields.Many2one('att.address.suggestion', string='Điểm đi (tìm)',
                                        ondelete='set null')
    delivery_location = fields.Char(string='Điểm đến')
    delivery_address_id = fields.Many2one('att.address.suggestion', string='Điểm đến (tìm)',
                                          ondelete='set null')
    pickup_lat = fields.Float('Vĩ độ điểm đi', digits=(10, 7))
    pickup_lng = fields.Float('Kinh độ điểm đi', digits=(10, 7))
    delivery_lat = fields.Float('Vĩ độ điểm đến', digits=(10, 7))
    delivery_lng = fields.Float('Kinh độ điểm đến', digits=(10, 7))

    # Hình thức vận chuyển = chính product_id (Đường bộ, Đa phương thức...
    # giờ là sản phẩm dịch vụ thật, không tách field/model riêng nữa).
    vehicle_type_id = fields.Many2one(
        'att.vehicle.type', string='Loại xe vận chuyển',
        domain="[('transport_mode_ids', 'in', product_id)] if product_id else []")
    vehicle_id = fields.Many2one('fleet.vehicle', string='Phương tiện')
    cargo_description = fields.Text(string='Mô tả hàng hóa')
    cargo_weight = fields.Char('Khối lượng')
    expected_date = fields.Datetime(string='Thời gian dự kiến')

    transport_order_ids = fields.One2many('att.transport.order', 'sale_order_line_id',
                                          'Lệnh vận chuyển')
    transport_order_count = fields.Integer(compute='_compute_transport_order_count')

    @api.onchange('pickup_address_id')
    def _onchange_pickup_address_id(self):
        if self.pickup_address_id:
            self.pickup_address_id.action_resolve_coordinates()
            self.pickup_location = self.pickup_address_id.name
            self.pickup_lat = self.pickup_address_id.lat
            self.pickup_lng = self.pickup_address_id.lng

    @api.onchange('delivery_address_id')
    def _onchange_delivery_address_id(self):
        if self.delivery_address_id:
            self.delivery_address_id.action_resolve_coordinates()
            self.delivery_location = self.delivery_address_id.name
            self.delivery_lat = self.delivery_address_id.lat
            self.delivery_lng = self.delivery_address_id.lng

    @api.depends('transport_order_ids')
    def _compute_transport_order_count(self):
        for rec in self:
            rec.transport_order_count = len(rec.transport_order_ids)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._th_resolve_route_costs()
        return lines

    def write(self, vals):
        res = super().write(vals)
        trigger_fields = {'pickup_lat', 'pickup_lng', 'delivery_lat', 'delivery_lng',
                          'vehicle_id', 'vehicle_type_id'}
        if trigger_fields & set(vals):
            self._th_resolve_route_costs()
        return res

    def _th_resolve_route_costs(self):
        """Tính tuyến + phí BOT (VietMap) NGAY khi dòng đã đủ điểm đi/điểm
        đến — không đợi tới lúc SO xác nhận mới tạo Lệnh vận chuyển mới
        tính (xem SaleOrder._th_auto_create_transport_orders bên dưới), để
        KD/điều vận thấy phí BOT tham khảo ngay từ lúc lập báo giá/phụ lục,
        trước khi có Lệnh vận chuyển thật nào.

        Chạy lại khi user ĐỔI điểm đi/đến của dòng đã có sẵn (không chỉ lúc
        tạo mới) — nên cuối hàm phải DỌN chi phí của tuyến CŨ không còn
        dòng nào trên báo giá tham chiếu tới nữa (_th_cleanup_stale_route_
        costs), nếu không dòng cũ nằm lì mãi dù đã đổi tuyến khác hẳn."""
        Route = self.env['att.transport.route']
        CostLine = self.env['att.transport.cost.line']
        orders = self.mapped('order_id')
        for sol in self:
            if sol.display_type or not sol.pickup_location or not sol.delivery_location:
                continue
            if not (sol.pickup_lat or sol.pickup_lng) or not (sol.delivery_lat or sol.delivery_lng):
                continue
            route = Route._find_or_create(
                sol.pickup_location, sol.delivery_location,
                sol.pickup_lat, sol.pickup_lng, sol.delivery_lat, sol.delivery_lng)
            if not route:
                continue
            if sol.vehicle_id:
                vehicle, capacity = sol.vehicle_id._vietmap_route_params()
            elif sol.vehicle_type_id:
                vehicle, capacity = sol.vehicle_type_id._vietmap_route_params()
            else:
                vehicle, capacity = ('truck', None)
            route.action_resolve_route_info(vehicle=vehicle, capacity=capacity)
            # Template của tuyến → bản ghi riêng của báo giá này, để KD
            # chốt bên chịu/duyệt theo TỪNG khách (không đụng template).
            CostLine._copy_route_lines_to_sale_order(route, sol.order_id)
        orders._th_cleanup_stale_route_costs()


class SaleOrder(models.Model):
    """1 SO → N TO. Smart button + auto-sinh TO khi confirm SO.

    Cũng override 2 hook của att_contract_management (_att_get_outsource_lines,
    _att_purchase_rfq_line_vals) để RFQ thuê ngoài NCC mang đủ thông tin
    tuyến/loại xe — module contract KHÔNG biết gì về các field này, chỉ có
    module vận tải mới override được vì đây là nơi field logistics thật sự
    tồn tại."""
    _inherit = 'sale.order'

    transport_order_ids = fields.One2many('att.transport.order', 'sale_order_id', 'Lệnh vận chuyển')
    transport_order_count = fields.Integer(compute='_compute_transport_order_count')
    th_route_cost_count = fields.Integer(compute='_compute_th_route_cost_count')

    # ---- Cấu hình cột in PDF báo giá (tab "Cấu hình PDF báo giá") ----
    # Dòng báo giá vận tải có RẤT nhiều cột — mỗi báo giá tự chọn cột nào
    # in ra PDF/gửi khách. PDF gửi đi (email/Zalo) render từ chính report
    # này nên tự động ăn theo cấu hình, không cần xử lý riêng lúc gửi.
    th_pdf_show_content = fields.Boolean('In: Nội dung vận chuyển', default=True)
    th_pdf_show_pickup = fields.Boolean('In: Điểm đi', default=True)
    th_pdf_show_delivery = fields.Boolean('In: Điểm đến', default=True)
    th_pdf_show_vehicle = fields.Boolean('In: Phương tiện', default=False)
    th_pdf_show_transport_mode = fields.Boolean('In: Hình thức vận chuyển', default=False)
    th_pdf_show_qty = fields.Boolean('In: Số lượng', default=True)
    th_pdf_show_uom = fields.Boolean('In: Đơn vị tính', default=True)
    th_pdf_show_expected_date = fields.Boolean('In: Thời gian dự kiến', default=False)
    th_pdf_show_cargo_desc = fields.Boolean('In: Mô tả hàng hóa', default=False)
    th_pdf_show_price_unit = fields.Boolean('In: Đơn giá', default=True)
    th_pdf_show_taxes = fields.Boolean('In: Thuế', default=False)
    th_pdf_show_subtotal = fields.Boolean('In: Thành tiền chưa thuế', default=False)
    th_pdf_show_total = fields.Boolean('In: Tổng tiền', default=False)
    th_pdf_show_notes = fields.Boolean('In: Ghi chú', default=True)

    @api.depends('transport_order_ids')
    def _compute_transport_order_count(self):
        for rec in self:
            rec.transport_order_count = len(rec.transport_order_ids)

    def _th_cleanup_stale_route_costs(self):
        """Xoá chi phí RIÊNG của báo giá thuộc tuyến KHÔNG CÒN dòng nào
        trên báo giá tham chiếu tới nữa (user đổi điểm đi/đến sang tuyến
        khác) — chỉ xoá dòng CHƯA CHỐT + CHƯA ĐẨY, tuyệt đối không đụng
        dòng đã chốt/đã lên hoá đơn (quyết định của KD với khách đã xong
        thì không tự ý xoá dù tuyến gốc không còn khớp nữa)."""
        Route = self.env['att.transport.route']
        CostLine = self.env['att.transport.cost.line']
        for order in self:
            current_route_ids = set()
            for sol in order.order_line:
                if sol.display_type or not sol.pickup_location or not sol.delivery_location:
                    continue
                route = Route._find_or_create(
                    sol.pickup_location, sol.delivery_location,
                    sol.pickup_lat, sol.pickup_lng, sol.delivery_lat, sol.delivery_lng)
                if route:
                    current_route_ids.add(route.id)
            stale = CostLine.search([
                ('sale_order_id', '=', order.id),
                ('route_id', '=', False),
                ('is_confirmed', '=', False),
                ('state', '=', 'pending'),
                ('source_route_id', 'not in', list(current_route_ids) or [0]),
            ])
            # Xoá cost line KHÔNG tự xoá dòng báo giá (SOL) mà nó đã sinh ra
            # (_th_sync_quote_line) — phải gỡ tay, nếu không khách vẫn bị
            # tính tiền trạm BOT của tuyến CŨ không còn liên quan.
            stale.sale_order_line_id.unlink()
            stale.unlink()

    @api.depends('order_line.pickup_location', 'order_line.delivery_location',
                 'order_line.pickup_lat', 'order_line.delivery_lat')
    def _compute_th_route_cost_count(self):
        """Đếm bản ghi chi phí RIÊNG của báo giá này (copy từ template tuyến
        lúc lưu — xem _copy_route_lines_to_sale_order), KD chốt/duyệt trên
        các bản ghi này, không đụng template dùng chung của tuyến."""
        counts = dict(self.env['att.transport.cost.line']._read_group(
            [('sale_order_id', 'in', self.ids)], ['sale_order_id'], ['__count']))
        for rec in self:
            rec.th_route_cost_count = counts.get(rec, 0)

    def action_view_route_costs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Chi phí tuyến của %s') % self.name,
            'res_model': 'att.transport.cost.line',
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {'default_sale_order_id': self.id},
        }

    def _th_check_cost_lines_confirmed(self):
        """Override hook att_contract_management — chặn tạo HĐNT nếu còn
        dòng chi phí (bản ghi riêng của báo giá này, KHÔNG tính template
        tuyến) chưa được KD chốt bên chịu. Không chặn dòng nào chưa từng
        tồn tại (báo giá không có tuyến/chưa có chi phí)."""
        self.ensure_one()
        unconfirmed = self.env['att.transport.cost.line'].search([
            ('sale_order_id', '=', self.id),
            ('route_id', '=', False),
            ('is_confirmed', '=', False),
        ])
        if unconfirmed:
            raise UserError(_(
                'Còn %(so_dong)d dòng chi phí chưa chốt bên chịu (xem smart '
                'button "Chi phí tuyến") — phải chốt xong mới tạo được HĐNT: %(mo_ta)s',
                so_dong=len(unconfirmed),
                mo_ta=', '.join(unconfirmed.mapped(
                    lambda l: l.description or l.cost_type_id.name)[:5])))
        return super()._th_check_cost_lines_confirmed()

    def action_th_sync_route_costs(self):
        """Đồng bộ TAY chi phí tuyến → bản ghi riêng của báo giá. Bình
        thường việc này tự chạy khi lưu dòng có toạ độ mới; nút này dành
        cho: (1) báo giá cũ tạo trước khi có cơ chế bản-ghi-riêng, (2) tuyến
        vừa được bổ sung chi phí template sau khi báo giá đã lưu."""
        for order in self:
            order.order_line._th_resolve_route_costs()
        return True

    def action_view_transport_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lệnh vận chuyển của %s') % self.name,
            'res_model': 'att.transport.order',
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {'default_sale_order_id': self.id, 'default_partner_id': self.partner_id.id},
        }

    def action_create_transport_order(self):
        self.ensure_one()
        sol = self.order_line.filtered(lambda l: not l.display_type)[:1]
        ctx = {
            'default_origin_type': 'sale', 'default_sale_order_id': self.id,
            'default_partner_id': self.partner_id.id,
            'default_scheduled_date': fields.Datetime.now(),
        }
        if sol:
            ctx.update({'default_sale_order_line_id': sol.id,
                        'default_cargo_description': sol.cargo_description or sol.name})
            if sol.vehicle_id:
                ctx['default_vehicle_id'] = sol.vehicle_id.id
        return {'type': 'ir.actions.act_window', 'name': _('Tạo lệnh vận chuyển'),
                'res_model': 'att.transport.order', 'view_mode': 'form',
                'target': 'current', 'context': ctx}

    @api.model
    def action_new_quotation_for_route(self, route_vals):
        """Mở form báo giá MỚI (chưa lưu) với sẵn 1 dòng dịch vụ mang đủ
        điểm đi/đến + toạ độ + cước tham khảo — gọi từ nút "Tạo báo giá
        với tuyến này" trên panel Tìm đường của dashboard điều vận.
        KHÔNG create() record ở đây: báo giá bắt buộc có khách hàng mà
        panel tìm đường không biết khách nào — trả action mở form với
        default_ để KD tự chọn khách rồi lưu."""
        product = self.env.ref('att_transport_orders.product_tmode_duong_bo',
                               raise_if_not_found=False)
        # Cột "Điểm đi/Điểm đến" trên form SO hiển thị pickup_address_id/
        # delivery_address_id (M2O att.address.suggestion) — pickup_location
        # (Char) chỉ là cột ẩn. Phải tạo/tái dùng record gợi ý và fill vào
        # M2O thì user mới NHÌN THẤY giá trị; detail_fetched=True để cron
        # dọn gợi ý rác không bao giờ xoá record đang được SO tham chiếu.
        origin_sug = self._th_find_or_create_suggestion(
            route_vals.get('origin_name'), route_vals.get('origin_lat'),
            route_vals.get('origin_lng'))
        dest_sug = self._th_find_or_create_suggestion(
            route_vals.get('destination_name'), route_vals.get('destination_lat'),
            route_vals.get('destination_lng'))
        line_vals = {
            'product_id': product.id if product else False,
            'name': product.name if product else _('Vận chuyển đường bộ'),
            'product_uom_qty': 1.0,
            'pickup_address_id': origin_sug.id or False,
            'delivery_address_id': dest_sug.id or False,
            'pickup_location': route_vals.get('origin_name') or '',
            'pickup_lat': route_vals.get('origin_lat') or 0.0,
            'pickup_lng': route_vals.get('origin_lng') or 0.0,
            'delivery_location': route_vals.get('destination_name') or '',
            'delivery_lat': route_vals.get('destination_lat') or 0.0,
            'delivery_lng': route_vals.get('destination_lng') or 0.0,
        }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Báo giá từ tuyến tìm được'),
            'res_model': 'sale.order',
            'view_mode': 'form',
            # 'views' bắt buộc khai tường minh: action dict tự dựng trả qua
            # RPC không đi qua ir.actions.act_window.read() nên không được
            # framework tự sinh 'views' từ view_mode — thiếu là JS
            # _preprocessAction crash "undefined.map".
            'views': [(False, 'form')],
            'target': 'current',
            'context': {
                'default_order_line': [fields.Command.create(line_vals)],
            },
        }

    @api.model
    def _th_find_or_create_suggestion(self, name, lat, lng):
        """Tìm/tạo att.address.suggestion cho 1 điểm đã có sẵn toạ độ (từ
        panel Tìm đường). Tái dùng theo (name, lat, lng) để không đẻ record
        trùng mỗi lần tạo báo giá cùng tuyến."""
        if not name:
            return self.env['att.address.suggestion'].browse()
        Suggestion = self.env['att.address.suggestion']
        sug = Suggestion.search([
            ('name', '=', name), ('lat', '=', lat), ('lng', '=', lng),
        ], limit=1)
        if not sug:
            sug = Suggestion.create({
                'name': name, 'lat': lat or 0.0, 'lng': lng or 0.0,
                'detail_fetched': True,
            })
        elif not sug.detail_fetched:
            sug.detail_fetched = True
        return sug

    def action_confirm(self):
        """SO confirm → tự sinh TO nháp mỗi dòng dịch vụ (1 TO ↔ 1 SOL)."""
        res = super().action_confirm()
        self._th_auto_create_transport_orders()
        return res

    def _th_auto_create_transport_orders(self):
        TO = self.env['att.transport.order']
        Route = self.env['att.transport.route']
        for order in self:
            created = TO.browse()
            skipped = []
            # SOL sinh từ dòng chi phí (phí BOT... khách trả) chỉ là dòng
            # TIỀN trên báo giá — không phải chuyến hàng, không tạo Lệnh
            # vận chuyển và không được than "thiếu điểm đi/đến".
            cost_sols = self.env['att.transport.cost.line'].search([
                ('sale_order_line_id', 'in', order.order_line.ids),
            ]).mapped('sale_order_line_id')
            for sol in order.order_line.filtered(
                    lambda l: not l.display_type and l.product_id and l not in cost_sols):
                if TO.search_count([('sale_order_line_id', '=', sol.id),
                                    ('state', '!=', 'cancelled')]):
                    continue
                route = Route._find_or_create(
                    sol.pickup_location, sol.delivery_location,
                    sol.pickup_lat, sol.pickup_lng,
                    sol.delivery_lat, sol.delivery_lng)
                if not route:
                    skipped.append(sol.name)
                    continue
                # Ưu tiên xe THẬT (vehicle_id) nếu điều vận đã gán — số liệu
                # chính xác hơn loại xe chung chung (vehicle_type_id).
                if sol.vehicle_id:
                    vehicle_param, capacity_param = sol.vehicle_id._vietmap_route_params()
                elif sol.vehicle_type_id:
                    vehicle_param, capacity_param = sol.vehicle_type_id._vietmap_route_params()
                else:
                    vehicle_param, capacity_param = ('truck', None)
                route.action_resolve_route_info(vehicle=vehicle_param, capacity=capacity_param)
                vehicle = sol.vehicle_id
                to = TO.create({
                    'origin_type': 'sale', 'sale_order_id': order.id,
                    'sale_order_line_id': sol.id, 'partner_id': order.partner_id.id,
                    'route_id': route.id,
                    'scheduled_date': sol.expected_date or fields.Datetime.now(),
                    'vehicle_id': vehicle.id or False,
                    'driver_id': vehicle.default_driver_employee_id.id if vehicle else False,
                    'cargo_description': sol.cargo_description or sol.name,
                    'base_freight': sol.price_unit,
                })
                self.env['att.transport.cost.line']._copy_route_lines_to_order(route, to)
                created += to
            if created:
                order.message_post(
                    body=Markup('Đã tự tạo <b>%d lệnh vận chuyển</b> (nháp): %s') % (
                        len(created), ', '.join(created.mapped('name'))),
                    message_type='notification', subtype_xmlid='mail.mt_note')
            if skipped:
                order.message_post(
                    body=Markup('<b>%d dòng</b> thiếu Điểm đi/Điểm đến — chưa tạo được lệnh VC, điều vận tạo thủ công: %s') % (
                        len(skipped), ', '.join(skipped)),
                    message_type='notification', subtype_xmlid='mail.mt_note')


    def _att_get_outsource_lines(self):
        """Base (att_contract_management) trả về mọi dòng dịch vụ thật.
        Transport override: chỉ dòng THIẾU XE nội bộ (đã gán vehicle_id thì
        tự chạy nội bộ, không cần hỏi giá thuê ngoài)."""
        lines = super()._att_get_outsource_lines()
        return lines.filtered(lambda l: not l.vehicle_id)

    def _att_purchase_rfq_line_vals(self, sol):
        """Bổ sung logistics (tuyến, loại xe, mô tả hàng) vào dòng RFQ để
        NCC biết chạy tuyến nào, loại xe nào — base dùng product mặc định
        chung, ở đây đổi lại dùng ĐÚNG sản phẩm dịch vụ (hình thức vận
        chuyển) của dòng báo giá gốc, vì giờ product_id đã thể hiện rõ
        hình thức vận chuyển cụ thể (Đường bộ, Đa phương thức...)."""
        vals = super()._att_purchase_rfq_line_vals(sol)
        vals.update({
            'product_id': sol.product_id.id,
            'pickup_location': sol.pickup_location,
            'delivery_location': sol.delivery_location,
            'vehicle_type_id': sol.vehicle_type_id.id,
            'cargo_description': sol.cargo_description,
        })
        return vals
