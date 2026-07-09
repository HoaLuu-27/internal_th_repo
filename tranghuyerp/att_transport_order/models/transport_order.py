import logging

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ThTransportOrder(models.Model):
    """Lệnh vận chuyển (TO) — đối tượng lõi phân hệ Điều vận (SRS 2.5.1).
    State machine 5 trạng thái (SRS 2.7): draft → confirmed → in_transit
    → done | cancelled. Xác nhận bốc/giao hàng là hành động phụ trong
    in_transit (D-03), không thêm trạng thái mới."""
    _name = 'att.transport.order'
    _description = 'Lệnh vận chuyển'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'scheduled_date desc, id desc'

    name = fields.Char('Mã lệnh vận chuyển', default='/', copy=False, readonly=True)
    origin_type = fields.Selection([
        ('sale', 'Từ đơn hàng bán'),
        ('manual', 'Tạo nhanh'),
    ], string='Nguồn tạo lệnh', required=True, default='sale')
    sale_order_id = fields.Many2one('sale.order', 'Đơn hàng bán liên kết', index=True, copy=False)
    # 1 SO → N TO, mỗi TO ứng đúng 1 dòng SO (SOL) + 1 xe
    sale_order_line_id = fields.Many2one(
        'sale.order.line', 'Dòng SO (tuyến/hàng)', index=True, copy=False,
        domain="[('order_id', '=', sale_order_id), ('display_type', '=', False)]")
    partner_id = fields.Many2one('res.partner', 'Khách hàng', required=True, tracking=True)
    route_id = fields.Many2one('att.transport.route', 'Tuyến đường', required=True,
                               tracking=True, index=True)

    vehicle_source = fields.Selection([
        ('internal', 'Xe nội bộ Trang Huy'),
        ('external', 'Thuê nhà cung cấp'),
    ], string='Nguồn xe', required=True, default='internal')
    vehicle_id = fields.Many2one('fleet.vehicle', 'Xe', tracking=True)
    driver_id = fields.Many2one('hr.employee', 'Lái xe', tracking=True)
    carrier_id = fields.Many2one('res.partner', 'Nhà cung cấp vận tải',
                                 domain=[('supplier_rank', '>', 0)])
    purchase_order_id = fields.Many2one('purchase.order', 'PO thuê xe NCC', copy=False,
                                        help='1 lệnh ↔ 1 PO nhà cung cấp (BR-DV-011).')

    commodity_id = fields.Many2one('att.commodity', 'Loại hàng hoá')
    cargo_description = fields.Text('Mô tả hàng')
    cargo_weight = fields.Float('Trọng lượng (tấn)')
    cargo_volume = fields.Float('Thể tích (m³)')
    container_no = fields.Char('Số container')

    scheduled_date = fields.Datetime('Ngày xuất phát dự kiến', required=True, tracking=True)
    actual_departure = fields.Datetime('Giờ xuất phát thực tế', readonly=True, copy=False)
    actual_arrival = fields.Datetime('Giờ đến thực tế', readonly=True, copy=False)

    is_backhaul = fields.Boolean('Chuyến về', default=False, copy=False)
    origin_to_id = fields.Many2one('att.transport.order', 'Lệnh gốc chiều đi',
                                   readonly=True, copy=False)

    state = fields.Selection([
        ('draft', 'Nháp'),
        ('confirmed', 'Đã xác nhận'),
        ('in_transit', 'Đang vận chuyển'),
        ('done', 'Hoàn thành'),
        ('cancelled', 'Đã huỷ'),
    ], default='draft', tracking=True, index=True, copy=False)

    base_freight = fields.Monetary('Cước vận chuyển cơ bản', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency',
                                  default=lambda self: self.env.company.currency_id)
    cost_line_ids = fields.One2many('att.transport.cost.line', 'transport_order_id',
                                    'Dòng chi phí phát sinh')
    total_customer_cost = fields.Monetary('Tổng phí KH trả', compute='_compute_cost_totals')
    total_th_cost = fields.Monetary('Tổng chi phí TH chịu', compute='_compute_cost_totals')
    analytic_account_id = fields.Many2one('account.analytic.account', 'Tài khoản phân tích')

    # ---- Xác nhận bốc / giao hàng — 6 field trên chính model (D-03) ----
    source_confirmed = fields.Boolean('Đã xác nhận bốc hàng', copy=False)
    source_confirm_date = fields.Datetime('Thời điểm bốc hàng', readonly=True, copy=False)
    source_confirm_note = fields.Text('Ghi chú bốc hàng', copy=False)
    dest_confirmed = fields.Boolean('Đã xác nhận giao hàng', copy=False)
    dest_confirm_date = fields.Datetime('Thời điểm giao hàng', readonly=True, copy=False)
    dest_confirm_note = fields.Text('Ghi chú giao hàng', copy=False)

    pnv_number = fields.Char('Số phiếu nghiệm vụ', copy=False)
    incident_note = fields.Text('Ghi chú sự cố', copy=False, tracking=True)
    cancel_reason = fields.Text('Lý do huỷ', copy=False)
    survey_sent = fields.Boolean('Đã gửi khảo sát', copy=False, readonly=True)
    note = fields.Text('Ghi chú nội bộ')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    # ------------------------------------------------------------------
    @api.constrains("sale_order_line_id", "state")
    def _check_duplicate_sale_order_line(self):
        for rec in self:
            if not rec.sale_order_line_id or rec.state == "cancelled":
                continue

            duplicated = self.search_count([
                ("id", "!=", rec.id),
                ("sale_order_line_id", "=", rec.sale_order_line_id.id),
                ("state", "!=", "cancelled"),
            ])

            if duplicated:
                raise UserError(
                    _("Dòng SO %s đã có lệnh vận chuyển khác chưa hủy.")
                    % rec.sale_order_line_id.display_name
                )

    @api.depends('cost_line_ids.amount', 'cost_line_ids.paid_by')
    def _compute_cost_totals(self):
        for rec in self:
            rec.total_customer_cost = sum(
                rec.cost_line_ids.filtered(lambda l: l.paid_by == 'customer').mapped('amount'))
            rec.total_th_cost = sum(
                rec.cost_line_ids.filtered(lambda l: l.paid_by == 'company').mapped('amount'))

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        for rec in self:
            if rec.vehicle_id and rec.vehicle_id.default_driver_employee_id:
                rec.driver_id = rec.vehicle_id.default_driver_employee_id
            if (rec.vehicle_id and rec.cargo_weight and rec.vehicle_id.payload_capacity
                    and rec.cargo_weight > rec.vehicle_id.payload_capacity):
                return {'warning': {
                    'title': _('Vượt tải trọng'),
                    'message': _('Hàng %(hang)s tấn vượt tải trọng tối đa %(tai)s tấn của xe %(xe)s.',
                                 hang=rec.cargo_weight, tai=rec.vehicle_id.payload_capacity,
                                 xe=rec.vehicle_id.display_name)}}

    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        for rec in self:
            if not rec.sale_order_id:
                continue
            rec.partner_id = rec.sale_order_id.partner_id
            if (rec.sale_order_line_id
                    and rec.sale_order_line_id.order_id != rec.sale_order_id):
                rec.sale_order_line_id = False
            lines = rec.sale_order_id.order_line.filtered(lambda l: not l.display_type)
            if len(lines) == 1 and not rec.sale_order_line_id:
                rec.sale_order_line_id = lines

    @api.onchange('sale_order_line_id')
    def _onchange_sale_order_line_id(self):
        for rec in self:
            sol = rec.sale_order_line_id
            if not sol:
                continue
            rec.cargo_description = sol.cargo_description or sol.name
            if sol.vehicle_id:
                rec.vehicle_id = sol.vehicle_id
            if sol.pickup_location and sol.delivery_location and not rec.route_id:
                route = self.env['att.transport.route'].search([
                    ('origin_name', '=ilike', sol.pickup_location),
                    ('destination_name', '=ilike', sol.delivery_location),
                ], limit=1)
                if route:
                    rec.route_id = route

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') in ('/', False):
                vals['name'] = self.env['ir.sequence'].next_by_code('att.transport.order') or '/'
        records = super().create(vals_list)
        for rec in records.filtered(lambda r: r.origin_type == 'manual' and not r.sale_order_id):
            so = self.env['sale.order'].create({
                'partner_id': rec.partner_id.id,
                'origin': rec.name,
                'note': _('SO nháp sinh tự động từ lệnh tạo nhanh %s — cập nhật lại sau khi ký HĐ/PL.') % rec.name,
            })
            rec.sale_order_id = so
            rec.message_post(
                body=Markup('Lệnh tạo nhanh — SO nháp <b>%s</b> đã được tạo đồng thời. Cập nhật HĐ/PL sau khi ký.') % so.name,
                message_type='notification', subtype_xmlid='mail.mt_note')
        return records

    # ------------------------------------------------------------------
    def _get_image_attachments(self, after=None):
        """Ảnh đính kèm qua Chatter (D-03). sudo(): guard nội bộ, lái xe/user
        thường có thể không đủ quyền đọc ir.attachment."""
        self.ensure_one()
        domain = [('res_model', '=', self._name), ('res_id', '=', self.id),
                  ('mimetype', '=like', 'image/%')]
        if after:
            domain.append(('create_date', '>', after))
        return self.env['ir.attachment'].sudo().search(domain)

    def _notify_zns(self, partner, body):
        """Gửi ZNS — STUB (mẫu ZNS chờ Marketing). Có Zalo OA thì gửi tạm qua
        OA chat; không thì ghi chatter để không chặn vận hành."""
        self.ensure_one()
        try:
            zalo_uid = getattr(partner, 'zalo_user_id', False)
            if zalo_uid and 'att.zalo.oa.api' in self.env:
                config = self.env['att.zalo.service.config'].sudo()._get_active_oa_config()
                if config:
                    self.env['att.zalo.oa.api'].sudo().send_text(config, zalo_uid, body)
                    return True
        except Exception as e:  # noqa: BLE001
            _logger.warning('TO %s: gửi Zalo thất bại: %s', self.name, e)
        self.message_post(
            body=Markup('[ZNS chờ tích hợp] Gửi <b>%s</b>: %s') % (partner.name or '?', body),
            message_type='notification', subtype_xmlid='mail.mt_note')
        return False

    def _driver_partner(self):
        self.ensure_one()
        return (self.driver_id.user_id.partner_id or self.driver_id.work_contact_id
                or self.env['res.partner'])

    def _check_vehicle_free(self):
        self.ensure_one()
        if self.vehicle_source != 'internal' or not self.vehicle_id:
            return
        other = self.search_count([
            ('vehicle_id', '=', self.vehicle_id.id), ('state', '=', 'in_transit'),
            ('id', '!=', self.id)])
        if other or self.vehicle_id.th_state == 'in_transit':
            raise UserError(_('Xe %s đang thực hiện lệnh khác — không thể gán thêm.')
                            % self.vehicle_id.display_name)
        if self.vehicle_id.th_state in ('maintenance', 'broken'):
            raise UserError(_('Xe %s đang %s — chọn xe khác hoặc thuê ngoài.') % (
                self.vehicle_id.display_name,
                dict(self.vehicle_id._fields['th_state'].selection)[self.vehicle_id.th_state]))

    def _release_vehicle(self):
        for rec in self.filtered(lambda r: r.vehicle_id):
            still_busy = self.search_count([
                ('vehicle_id', '=', rec.vehicle_id.id), ('state', '=', 'in_transit'),
                ('id', '!=', rec.id)])
            if not still_busy and rec.vehicle_id.th_state == 'in_transit':
                rec.vehicle_id.th_state = 'available'

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------
    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Chỉ xác nhận được lệnh ở trạng thái Nháp.'))
            if rec.vehicle_source == 'internal' and (not rec.vehicle_id or not rec.driver_id):
                raise UserError(_('Bắt buộc có xe và lái xe trước khi xác nhận.'))
            if rec.vehicle_source == 'external' and not rec.carrier_id:
                raise UserError(_('Lệnh thuê ngoài bắt buộc chọn Nhà cung cấp vận tải.'))
            if rec.origin_type == 'sale' and not rec.sale_order_line_id:
                raise UserError(_('Lệnh từ đơn hàng bán phải chọn "Dòng SO (tuyến/hàng)" — '
                                  'mỗi lệnh ứng với đúng 1 dòng trên SO.'))
            rec._check_vehicle_free()
            rec.state = 'confirmed'
            if rec.driver_id:
                rec._notify_zns(rec._driver_partner(), _(
                    'Lệnh %(lenh)s: lấy hàng tại %(diemdi)s — %(ngay)s. Tuyến: %(tuyen)s.',
                    lenh=rec.name, diemdi=rec.route_id.origin_name,
                    ngay=rec.scheduled_date.strftime('%d/%m/%Y %H:%M'), tuyen=rec.route_id.name))

    def action_in_transit(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Chỉ bắt đầu vận chuyển từ lệnh Đã xác nhận.'))
            rec._check_vehicle_free()
            rec.actual_departure = fields.Datetime.now()
            rec.state = 'in_transit'
            if rec.vehicle_id:
                rec.vehicle_id.th_state = 'in_transit'
            rec._notify_zns(rec.partner_id, _(
                'Xe %(bienso)s đã xuất phát tới %(diemden)s.',
                bienso=rec.vehicle_id.license_plate or rec.carrier_id.name or '',
                diemden=rec.route_id.destination_name))

    def action_confirm_source(self):
        for rec in self:
            if rec.state != 'in_transit':
                raise UserError(_('Chỉ xác nhận bốc hàng khi lệnh Đang vận chuyển.'))
            if rec.source_confirmed:
                raise UserError(_('Lệnh đã xác nhận bốc hàng rồi.'))
            if not rec._get_image_attachments():
                raise UserError(_('Vui lòng đính kèm ảnh xác nhận bốc hàng (qua Chatter) trước khi xác nhận.'))
            rec.write({'source_confirmed': True, 'source_confirm_date': fields.Datetime.now()})
            rec.message_post(
                body=Markup('Đã xác nhận <b>bốc hàng</b> tại %s.') % rec.route_id.origin_name,
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_confirm_dest(self):
        for rec in self:
            if rec.state != 'in_transit':
                raise UserError(_('Chỉ xác nhận giao hàng khi lệnh Đang vận chuyển.'))
            if not rec.source_confirmed:
                raise UserError(_('Phải xác nhận bốc hàng trước khi xác nhận giao hàng.'))
            if rec.dest_confirmed:
                raise UserError(_('Lệnh đã xác nhận giao hàng rồi.'))
            if not rec._get_image_attachments(after=rec.source_confirm_date):
                raise UserError(_('Vui lòng đính kèm ảnh giao hàng và biên bản ký nhận (qua Chatter) trước khi xác nhận.'))
            rec.write({'dest_confirmed': True, 'dest_confirm_date': fields.Datetime.now()})
            address = self.env['ir.config_parameter'].sudo().get_param(
                'att.pnv.return_address', '(chưa cấu hình th.pnv.return_address)')
            pnv_msg = _('Vui lòng gửi PNV chuyến %(lenh)s về địa chỉ: %(diachi)s. Hạn: 24 giờ.',
                        lenh=rec.name, diachi=address)
            if rec.driver_id:
                rec._notify_zns(rec._driver_partner(), pnv_msg)
                rec.activity_schedule('mail.mail_activity_data_todo',
                                      user_id=rec.driver_id.user_id.id or self.env.user.id,
                                      summary=_('Gửi PNV chuyến %s về TH trong 24 giờ') % rec.name,
                                      note=pnv_msg)
            rec._notify_zns(rec.partner_id, _('Hàng đã giao tại %(diemden)s. Lệnh %(lenh)s hoàn tất.',
                                              diemden=rec.route_id.destination_name, lenh=rec.name))

    def action_done(self):
        for rec in self:
            if rec.state != 'in_transit':
                raise UserError(_('Chỉ hoàn thành được lệnh Đang vận chuyển.'))
            if not rec.dest_confirmed:
                rec.message_post(
                    body=Markup('Lưu ý: Hoàn thành lệnh khi <b>chưa xác nhận giao hàng</b>.'),
                    message_type='notification', subtype_xmlid='mail.mt_note')
            rec.actual_arrival = fields.Datetime.now()
            rec._push_cost_lines()
            rec.state = 'done'
            rec._release_vehicle()
            rec._notify_zns(rec.partner_id, _(
                'Lệnh %s đã hoàn thành. Trang Huy Logistics cảm ơn Quý khách — mong anh/chị đánh giá chất lượng chuyến hàng.') % rec.name)
            rec.survey_sent = True

    def action_cancel(self):
        for rec in self:
            if rec.state == 'done':
                raise UserError(_('Không thể huỷ lệnh đã hoàn thành.'))
            if not rec.cancel_reason:
                raise UserError(_('Vui lòng nhập Lý do huỷ trước khi huỷ lệnh.'))
            rec.state = 'cancelled'
            rec._release_vehicle()
            rec.message_post(
                body=Markup('Lệnh bị huỷ. Lý do: <b>%s</b>') % rec.cancel_reason,
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_create_backhaul(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'in_transit'):
            raise UserError(_('Chỉ tạo chuyến về từ lệnh Đã xác nhận/Đang vận chuyển.'))
        if self.is_backhaul:
            raise UserError(_('Lệnh này đã là chuyến về.'))
        if not self.route_id.reverse_route_id:
            raise UserError(_('Tuyến này chưa cấu hình tuyến ngược. Vui lòng cấu hình '
                              'trường "Tuyến ngược chiều" trên tuyến %s.') % self.route_id.name)
        backhaul = self.copy({
            'route_id': self.route_id.reverse_route_id.id, 'origin_type': 'manual',
            'sale_order_id': False, 'base_freight': 0.0, 'is_backhaul': True,
            'origin_to_id': self.id, 'scheduled_date': fields.Datetime.now(), 'state': 'draft',
        })
        self.message_post(
            body=Markup('Đã tạo chuyến về <b>%s</b> (tuyến %s).') % (backhaul.name, backhaul.route_id.name),
            message_type='notification', subtype_xmlid='mail.mt_note')
        return {'type': 'ir.actions.act_window', 'res_model': self._name,
                'view_mode': 'form', 'res_id': backhaul.id}

    def action_report_incident(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'in_transit'):
            raise UserError(_('Chỉ báo sự cố với lệnh Đã xác nhận/Đang vận chuyển.'))
        if not self.incident_note:
            raise UserError(_('Vui lòng mô tả nội dung sự cố vào ô "Ghi chú sự cố" trước khi bấm Báo sự cố.'))
        managers = self.env.ref('att_transport_order.group_th_dispatcher').users.mapped('partner_id')
        self.message_post(
            body=Markup('<b>SỰ CỐ</b> trên lệnh <b>%s</b>: %s') % (self.name, self.incident_note),
            partner_ids=managers.ids, message_type='notification', subtype_xmlid='mail.mt_comment')

    # ------------------------------------------------------------------
    # Đẩy chi phí khi hoàn thành (SRS 2.6.2 / BR-DV-010)
    # ------------------------------------------------------------------
    # def _push_cost_lines(self):
    #     self.ensure_one()
    #     skipped = 0
    #     for line in self.cost_line_ids:
    #         if line.state == 'pushed':
    #             continue
    #         if line.needs_approval and line.state != 'approved':
    #             skipped += 1
    #             continue
    #         if line.paid_by == 'customer' and line.expense_type == 'so_line':
    #             if not self.sale_order_id:
    #                 skipped += 1
    #                 continue
    #             sol = self.env['sale.order.line'].create({
    #                 'order_id': self.sale_order_id.id,
    #                 'product_id': line.cost_type_id.product_id.id,
    #                 'name': _('%(mota)s (Lệnh %(lenh)s)',
    #                           mota=line.description or line.cost_type_id.name, lenh=self.name),
    #                 'product_uom_qty': 1.0, 'price_unit': line.amount,
    #             })
    #             line.write({'sale_order_line_id': sol.id, 'state': 'pushed'})
    #         elif line.paid_by == 'company' and line.expense_type == 'vendor_bill':
    #             partner = self.carrier_id or line.cost_type_id.product_id.seller_ids[:1].partner_id
    #             if not partner:
    #                 skipped += 1
    #                 continue
    #             bill = self.env['account.move'].create({
    #                 'move_type': 'in_invoice', 'partner_id': partner.id,
    #                 'invoice_date': line.date, 'ref': _('Chi phí lệnh %s') % self.name,
    #                 'invoice_line_ids': [(0, 0, {
    #                     'product_id': line.cost_type_id.product_id.id,
    #                     'name': line.description or line.cost_type_id.name,
    #                     'quantity': 1.0, 'price_unit': line.amount})],
    #             })
    #             line.write({'vendor_bill_id': bill.id, 'state': 'pushed'})
    #         elif line.expense_type == 'internal':
    #             line.state = 'pushed'
    #     if skipped:
    #         self.message_post(
    #             body=Markup('Lưu ý: <b>%d</b> dòng chi phí chưa được duyệt/thiếu thông tin — không đẩy lên đơn hàng.') % skipped,
    #             message_type='notification', subtype_xmlid='mail.mt_note')

    def _push_cost_lines(self):
        self.ensure_one()
        skipped = 0

        for line in self.cost_line_ids:
            if line.state == "pushed":
                continue

            if line.needs_approval and line.state != "approved":
                skipped += 1
                continue

            if line.paid_by == "customer" and line.expense_type == "so_line":
                if not self.sale_order_id or not line.cost_type_id.product_id:
                    skipped += 1
                    continue

                sol = self.env["sale.order.line"].create({
                    "order_id": self.sale_order_id.id,
                    "product_id": line.cost_type_id.product_id.id,
                    "name": "%s (Lệnh %s)" % (
                        line.description or line.cost_type_id.name,
                        self.name,
                    ),
                    "product_uom_qty": 1.0,
                    "price_unit": line.amount,
                })
                line.write({
                    "sale_order_line_id": sol.id,
                    "state": "pushed",
                })

            elif line.paid_by in ("company", "vendor") and line.expense_type == "vendor_bill":
                partner = self.carrier_id or line.partner_id
                if not partner or not line.cost_type_id.product_id:
                    skipped += 1
                    continue

                bill = self.env["account.move"].create({
                    "move_type": "in_invoice",
                    "partner_id": partner.id,
                    "invoice_date": line.date,
                    "ref": "Chi phí lệnh %s" % self.name,
                    "invoice_line_ids": [(0, 0, {
                        "product_id": line.cost_type_id.product_id.id,
                        "name": line.description or line.cost_type_id.name,
                        "quantity": 1.0,
                        "price_unit": line.amount,
                    })],
                })
                line.write({
                    "vendor_bill_id": bill.id,
                    "state": "pushed",
                })

            elif line.expense_type == "internal":
                line.state = "pushed"

            else:
                skipped += 1

        if skipped:
            self.message_post(
                body="Lưu ý: %s dòng chi phí chưa được xử lý do thiếu duyệt hoặc thiếu thông tin." % skipped,
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )
