from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AttTransportCostType(models.Model):
    """Loại chi phí phát sinh (SRS 2.5.2). Một bản ghi gói đủ bên chịu,
    cách xử lý kế toán, product ánh xạ, logic duyệt.
    paid_by/expense_type ở đây chỉ là GIÁ TRỊ MẶC ĐỊNH — mỗi dòng chi phí
    (att.transport.cost.line) có thể tự "chốt" lại khác đi (VD 1 trạm BOT
    trên tuyến này khách trả, tuyến khác Trang Huy chịu), không bắt buộc
    theo cứng loại chi phí."""
    _name = 'att.transport.cost.type'
    _description = 'Loại chi phí phát sinh'
    _order = 'name'

    name = fields.Char('Tên loại chi phí', required=True)
    is_toll = fields.Boolean(
        'Là phí trạm BOT', default=False,
        help='Đánh dấu loại này dùng cho phí trạm thu phí — hệ thống tự tạo '
             'dòng chi phí loại này khi lấy dữ liệu tuyến từ VietMap.')
    paid_by = fields.Selection([
        ('customer', 'Khách hàng trả'),
        ('company', 'Trang Huy chịu'),
        ('vendor', 'NCC chịu'),
    ], string='Bên chịu chi phí (mặc định)', required=True, default='customer')
    expense_type = fields.Selection([
        ('so_line', 'Thêm vào dòng đơn hàng bán'),
        ('vendor_bill', 'Tạo phiếu chi NCC nháp'),
        ('internal', 'Chi phí nội bộ'),
    ], string='Cách xử lý kế toán (mặc định)', required=True, default='so_line')
    product_id = fields.Many2one('product.product', 'Sản phẩm Odoo ánh xạ',
                                 domain=[('type', '=', 'service')],
                                 help='Dùng tạo dòng SO hoặc dòng phiếu chi NCC.')
    expense_account_id = fields.Many2one('account.account', 'Tài khoản hạch toán',
                                         help='Tài khoản GL mặc định cho chi phí nội bộ.')
    requires_approval = fields.Boolean('Cần phê duyệt', default=False,
                                       help='KD phải duyệt trước khi đẩy lên đơn hàng.')
    approval_threshold = fields.Monetary('Ngưỡng phê duyệt (VNĐ)', currency_field='currency_id',
                                         help='Vượt ngưỡng mới cần duyệt. 0 = luôn cần duyệt.')
    currency_id = fields.Many2one('res.currency',
                                  default=lambda self: self.env.company.currency_id)
    default_description = fields.Char('Mô tả mặc định')
    active = fields.Boolean(default=True)

    @api.constrains('expense_type', 'product_id')
    def _check_product_required(self):
        for rec in self:
            if rec.expense_type in ('so_line', 'vendor_bill') and not rec.product_id:
                raise UserError(_(
                    'Loại chi phí "%s": cách xử lý "%s" bắt buộc chọn Sản phẩm ánh xạ.'
                ) % (rec.name, dict(rec._fields['expense_type'].selection)[rec.expense_type]))


class AttTransportCostLine(models.Model):
    """Dòng chi phí — 2 VAI TRÒ tách bạch:

    1. TEMPLATE của tuyến (route_id set, KHÔNG có sale_order_id/
       transport_order_id): chi phí chuẩn ai đi tuyến đó cũng gặp (phí BOT
       VietMap tự tạo, phí cố định nhập tay). CHỈ để tham khảo/bảo trì —
       không chốt/duyệt ở đây vì đó là quyết định theo từng khách hàng.
    2. BẢN GHI RIÊNG theo chứng từ (sale_order_id set, route_id KHÔNG set,
       giữ vết tuyến qua source_route_id): copy từ template khi báo giá/SO
       có tuyến — khách A chốt/duyệt trên bản của khách A, không đụng
       khách B. Khi SO sinh Lệnh vận chuyển thì gắn thêm
       transport_order_id (KHÔNG copy lần nữa — giữ nguyên đã chốt/duyệt),
       TO hoàn thành đẩy thành dòng SO/phiếu chi NCC.
    Vòng đời bản ghi riêng: pending → approved → pushed."""
    _name = 'att.transport.cost.line'
    _description = 'Dòng chi phí phát sinh'
    _order = 'date desc, id desc'

    route_id = fields.Many2one(
        'att.transport.route', 'Tuyến đường (template)',
        ondelete='cascade', index=True,
        help='CHỈ set với dòng chi phí chuẩn của tuyến. Bản ghi riêng theo '
             'SO/TO dùng source_route_id, không set field này — để tab chi '
             'phí trên form Tuyến chỉ hiện template, không lẫn bản của khách.')
    source_route_id = fields.Many2one(
        'att.transport.route', 'Tuyến gốc (tham khảo)',
        ondelete='set null', index=True,
        help='Bản ghi riêng theo SO/TO ghi lại tuyến nguồn ở đây.')
    sale_order_id = fields.Many2one('sale.order', 'Báo giá / Đơn bán',
                                    ondelete='cascade', index=True)
    customer_id = fields.Many2one(related='sale_order_id.partner_id',
                                  string='Khách hàng', store=True, readonly=True)
    transport_order_id = fields.Many2one('att.transport.order', 'Lệnh vận chuyển',
                                         ondelete='cascade', index=True)
    cost_type_id = fields.Many2one('att.transport.cost.type', 'Loại chi phí', required=True)
    description = fields.Char('Mô tả')
    amount = fields.Monetary('Số tiền', required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency',
                                  default=lambda self: self.env.company.currency_id)
    date = fields.Date('Ngày phát sinh', required=True, default=fields.Date.today)
    # KHÔNG còn related — mỗi dòng tự chốt riêng, mặc định lấy theo loại chi
    # phí lúc chọn (xem _onchange_cost_type_id) nhưng sửa được sau đó.
    paid_by = fields.Selection([
        ('customer', 'Khách hàng trả'),
        ('company', 'Trang Huy chịu'),
        ('vendor', 'NCC chịu'),
    ], string='Bên chịu chi phí')
    expense_type = fields.Selection([
        ('so_line', 'Thêm vào dòng đơn hàng bán'),
        ('vendor_bill', 'Tạo phiếu chi NCC nháp'),
        ('internal', 'Chi phí nội bộ'),
    ], string='Cách xử lý kế toán')
    is_confirmed = fields.Boolean(
        'Đã chốt', default=False,
        help='Đánh dấu đã xác nhận bên chịu/cách xử lý — Phụ lục chỉ cho '
             'sinh đơn thực thi khi TẤT CẢ dòng chi phí của các tuyến liên '
             'quan đã được chốt.')
    # Nhãn pending là "Chờ xử lý" (KHÔNG phải "Chờ duyệt") — đa số dòng
    # (BOT...) không cần ai duyệt cả, chỉ chờ TO hoàn thành để đẩy; chỉ
    # dòng needs_approval=True mới thực sự chờ quản lý duyệt.
    state = fields.Selection([
        ('pending', 'Chờ xử lý'),
        ('approved', 'Đã duyệt'),
        ('pushed', 'Đã xử lý'),
    ], default='pending', index=True, copy=False)
    needs_approval = fields.Boolean('Cần duyệt', compute='_compute_needs_approval', store=True)
    approved_by = fields.Many2one('res.users', 'Người duyệt', readonly=True, copy=False)
    approved_date = fields.Datetime('Ngày duyệt', readonly=True, copy=False)
    vendor_bill_id = fields.Many2one('account.move', 'Phiếu chi NCC', readonly=True, copy=False)
    sale_order_line_id = fields.Many2one('sale.order.line', 'Dòng đơn hàng bán',
                                         readonly=True, copy=False)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Đối tác/NCC')

    # ---- Riêng cho dòng là phí trạm BOT (tự tạo từ VietMap) ----
    is_toll = fields.Boolean('Là phí trạm BOT', related='cost_type_id.is_toll',
                             store=True, readonly=True)
    toll_ref_id = fields.Char('Mã trạm (VietMap)', readonly=True)
    toll_type = fields.Selection([
        ('entry', 'Trạm vào'),
        ('exit', 'Trạm ra'),
    ], string='Loại trạm', readonly=True)
    toll_lat = fields.Float('Vĩ độ trạm', digits=(10, 7), readonly=True)
    toll_lng = fields.Float('Kinh độ trạm', digits=(10, 7), readonly=True)

    @api.depends('description', 'cost_type_id')
    def _compute_display_name(self):
        """Tên bản ghi = mô tả (tên trạm...) — không để Odoo hiện
        'att.transport.cost.line,26' vô nghĩa trên breadcrumb/chatter."""
        for rec in self:
            rec.display_name = rec.description or rec.cost_type_id.name or _('Chi phí')

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise UserError(_('Số tiền chi phí phải lớn hơn 0.'))

    @api.depends('cost_type_id', 'amount', 'paid_by')
    def _compute_needs_approval(self):
        for rec in self:
            ct = rec.cost_type_id
            rec.needs_approval = bool(
                ct and ct.requires_approval and rec.paid_by == 'customer'
                and (not ct.approval_threshold or rec.amount > ct.approval_threshold))

    @api.onchange('cost_type_id')
    def _onchange_cost_type_id(self):
        for rec in self:
            if rec.cost_type_id:
                if not rec.description:
                    rec.description = rec.cost_type_id.default_description or rec.cost_type_id.name
                # Chỉ mặc định lúc CHỌN loại — không ghi đè nếu user đã tự
                # chốt khác đi trước đó (is_confirmed).
                if not rec.is_confirmed:
                    rec.paid_by = rec.cost_type_id.paid_by
                    rec.expense_type = rec.cost_type_id.expense_type

    def action_confirm_payer(self):
        """Chốt bên chịu/cách xử lý cho dòng này — đồng thời đồng bộ lại
        dòng báo giá gửi khách: khách trả → giữ/tạo dòng trên báo giá;
        TH/NCC chịu → gỡ khỏi báo giá (đi đường phiếu chi NCC khi Lệnh
        hoàn thành, không tính tiền khách)."""
        for rec in self:
            if not rec.paid_by or not rec.expense_type:
                raise UserError(_('Dòng "%s" cần chọn Bên chịu và Cách xử lý trước khi chốt.')
                                % (rec.description or rec.cost_type_id.name))
            rec.is_confirmed = True
        self._th_sync_quote_line()

    def _th_sync_quote_line(self):
        """Đồng bộ dòng chi phí ↔ dòng BÁO GIÁ (SOL) để khách thấy đủ chi
        phí ngay trên báo giá gửi đi:
        - Khách trả (hoặc CHƯA quyết — mặc định cứ liệt kê cho khách biết)
          → phải có 1 SOL tương ứng (mô tả + số tiền).
        - Trang Huy / NCC chịu → gỡ SOL khỏi báo giá.
        Chỉ áp dụng cho bản ghi riêng đã gắn sale_order_id; loại chi phí
        phải có Sản phẩm ánh xạ mới tạo được SOL (BOT có sẵn)."""
        for rec in self:
            order = rec.sale_order_id
            if not order or rec.route_id:
                continue
            want_sol = rec.paid_by in (False, 'customer')
            if want_sol and not rec.sale_order_line_id:
                product = rec.cost_type_id.product_id
                if not product:
                    continue
                rec.sale_order_line_id = self.env['sale.order.line'].create({
                    'order_id': order.id,
                    'product_id': product.id,
                    'name': rec.description or rec.cost_type_id.name,
                    'product_uom_qty': 1.0,
                    'price_unit': rec.amount,
                })
            elif not want_sol and rec.sale_order_line_id:
                sol = rec.sale_order_line_id
                rec.sale_order_line_id = False
                sol.unlink()

    def action_approve(self):
        """KD/Quản lý duyệt chi phí KH trả — dùng group sale manager native."""
        if not self.env.user.has_group('sales_team.group_sale_manager'):
            raise UserError(_('Bạn không có quyền duyệt chi phí phát sinh.'))
        for rec in self:
            if rec.state != 'pending':
                raise UserError(_('Chỉ duyệt được dòng đang Chờ duyệt.'))
            rec.write({
                'state': 'approved',
                'approved_by': self.env.user.id,
                'approved_date': fields.Datetime.now(),
            })
            if rec.transport_order_id:
                rec.transport_order_id.message_post(
                    body=_('%(user)s đã duyệt chi phí %(mota)s: %(tien)s.',
                           user=self.env.user.name,
                           mota=rec.description or rec.cost_type_id.name,
                           tien=rec.currency_id.format(rec.amount)),
                    message_type='notification', subtype_xmlid='mail.mt_note')

    @api.model
    def _create_from_route_tolls(self, route, tolls):
        """Tạo dòng chi phí BOT từ kết quả att.vietmap.api.get_route_info()
        (field 'tolls' — list dict {id, name, address, type, price, lat, lng}).
        Bỏ qua trạm price=0 (trạm VÀO chỉ đánh dấu điểm vào, không tính phí
        — hệ thống VietMap tính phí ở trạm RA theo đúng điểm vào/ra thực
        tế) — tạo dòng cho trạm price=0 sẽ vi phạm ràng buộc "Số tiền > 0"
        và cũng không có ý nghĩa kế toán gì."""
        cost_type = self.env.ref('att_transport_orders.cost_type_bot', raise_if_not_found=False)
        if not cost_type:
            return self.browse()
        existing_refs = set(self.search([
            ('route_id', '=', route.id), ('toll_ref_id', '!=', False),
        ]).mapped('toll_ref_id'))
        vals_list = []
        for t in (tolls or []):
            price = t.get('price') or 0
            ref_id = str(t.get('id') or '')
            if price <= 0 or (ref_id and ref_id in existing_refs):
                continue
            address = t.get('address') or ''
            name = t.get('name') or cost_type.name
            vals_list.append({
                'route_id': route.id,
                'cost_type_id': cost_type.id,
                'description': '%s — %s' % (name, address) if address else name,
                'amount': price,
                'paid_by': cost_type.paid_by,
                'expense_type': cost_type.expense_type,
                'toll_ref_id': ref_id,
                'toll_type': t.get('type') if t.get('type') in ('entry', 'exit') else False,
                'toll_lat': t.get('lat') or 0.0,
                'toll_lng': t.get('lng') or 0.0,
            })
        return self.create(vals_list) if vals_list else self.browse()

    @api.model
    def _copy_route_lines_to_sale_order(self, route, order):
        """Copy TEMPLATE của tuyến thành bản ghi riêng cho 1 báo giá/SO —
        gọi khi dòng SO có đủ điểm đi/đến và tuyến đã resolve. Mỗi khách
        chốt/duyệt trên bản của mình. Khử trùng theo (SO, tuyến gốc,
        toll_ref_id/mô tả) để lưu lại báo giá nhiều lần không đẻ thêm."""
        if not route or not order:
            return self.browse()
        existing = self.search([
            ('sale_order_id', '=', order.id),
            ('source_route_id', '=', route.id),
        ])
        existing_keys = {(l.toll_ref_id or l.description) for l in existing}
        copies = self.browse()
        for line in route.cost_line_ids:
            key = line.toll_ref_id or line.description
            if key in existing_keys:
                continue
            copies += line.copy({
                'route_id': False,
                'source_route_id': route.id,
                'sale_order_id': order.id,
                'state': 'pending',
                'is_confirmed': False,
                'approved_by': False,
                'approved_date': False,
                'vendor_bill_id': False,
                'sale_order_line_id': False,
            })
        # Liệt kê NGAY thành dòng báo giá để gửi khách thấy đủ chi phí trên
        # tuyến — sau đó KD chốt từng dòng: khách trả giữ nguyên, TH/NCC
        # chịu thì dòng báo giá tương ứng bị gỡ (xem _th_sync_quote_line).
        copies._th_sync_quote_line()
        return copies

    @api.model
    def _copy_route_lines_to_order(self, route, transport_order):
        """Gắn dòng chi phí vào LỆNH vận chuyển mới tạo. Ưu tiên GẮN các
        bản ghi riêng đã có của chính SO nguồn (giữ nguyên trạng thái đã
        chốt/duyệt từ khâu báo giá — không copy lần nữa, không reset).
        TO không có SO nguồn (tạo nhanh) hoặc SO chưa có bản ghi riêng nào
        thì mới copy template của tuyến."""
        if not route or not transport_order:
            return self.browse()
        so = transport_order.sale_order_id
        if so:
            so_lines = self.search([
                ('sale_order_id', '=', so.id),
                ('source_route_id', '=', route.id),
                ('transport_order_id', '=', False),
            ])
            if so_lines:
                so_lines.write({'transport_order_id': transport_order.id})
                return so_lines
        copies = self.browse()
        for line in route.cost_line_ids:
            copies += line.copy({
                'route_id': False,
                'source_route_id': route.id,
                'sale_order_id': so.id if so else False,
                'transport_order_id': transport_order.id,
                'state': 'pending',
                'is_confirmed': False,
                'approved_by': False,
                'approved_date': False,
                'vendor_bill_id': False,
                'sale_order_line_id': False,
            })
        return copies
