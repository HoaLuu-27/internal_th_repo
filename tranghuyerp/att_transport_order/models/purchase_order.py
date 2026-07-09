from markupsafe import Markup

from odoo import api, fields, models, _


class PurchaseOrderLine(models.Model):
    """Field vận chuyển trên dòng PO — trùng bộ với SOL để map 1:1 qua phụ lục."""
    _inherit = 'purchase.order.line'

    pickup_location = fields.Char(string='Điểm đi')
    delivery_location = fields.Char(string='Điểm đến')
    transport_mode_id = fields.Many2one('att.transport.mode', string='Loại hình dịch vụ')
    vehicle_type_id = fields.Many2one(
        'att.vehicle.type', string='Loại xe vận chuyển',
        domain="[('transport_mode_ids', 'in', transport_mode_id)] if transport_mode_id else []")
    vehicle_id = fields.Many2one('fleet.vehicle', string='Phương tiện')
    cargo_description = fields.Text(string='Mô tả hàng hóa')


class PurchaseOrder(models.Model):
    """1 PO → N TO thuê ngoài (mỗi TO gắn đúng 1 PO — BR-DV-011)."""
    _inherit = 'purchase.order'

    transport_order_ids = fields.One2many('att.transport.order', 'purchase_order_id', 'Lệnh vận chuyển')
    transport_order_count = fields.Integer(compute='_compute_transport_order_count')

    @api.depends('transport_order_ids')
    def _compute_transport_order_count(self):
        for rec in self:
            rec.transport_order_count = len(rec.transport_order_ids)

    def action_view_transport_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lệnh vận chuyển của %s') % self.name,
            'res_model': 'att.transport.order', 'view_mode': 'list,form',
            'domain': [('purchase_order_id', '=', self.id)],
            'context': {'default_purchase_order_id': self.id,
                        'default_vehicle_source': 'external',
                        'default_carrier_id': self.partner_id.id},
        }

    def button_confirm(self):
        """PO confirm → tự sinh TO thuê ngoài (nháp) mỗi dòng."""
        res = super().button_confirm()
        self._th_auto_create_transport_orders()
        return res

    def _th_auto_create_transport_orders(self):
        TO = self.env['att.transport.order']
        Route = self.env['att.transport.route']
        for order in self.filtered(lambda o: o.state in ('purchase', 'done')):
            if TO.search_count([('purchase_order_id', '=', order.id),
                                ('state', '!=', 'cancelled')]):
                continue
            # att_source_sale_order_id do att_quotations_contracts (lớp trên) thêm.
            # Đọc bằng getattr để KHÔNG phụ thuộc ngược → tránh vòng phụ thuộc.
            source_so = getattr(order, 'att_source_sale_order_id', False)
            if not source_so:
                order.message_post(
                    body=Markup('PO không có <b>SO nguồn</b> — không xác định được khách hàng của chuyến, điều vận tạo lệnh VC thủ công (menu Điều vận).'),
                    message_type='notification', subtype_xmlid='mail.mt_note')
                continue
            created = TO.browse()
            skipped = []
            for pol in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
                route = Route._find_or_create(pol.pickup_location, pol.delivery_location)
                if not route:
                    skipped.append(pol.name)
                    continue
                sol = source_so.order_line.filtered(
                    lambda l: not l.display_type
                    and (l.pickup_location or '').strip().lower() == (pol.pickup_location or '').strip().lower()
                    and (l.delivery_location or '').strip().lower() == (pol.delivery_location or '').strip().lower())[:1]
                created += TO.create({
                    'origin_type': 'sale', 'sale_order_id': source_so.id,
                    'sale_order_line_id': sol.id or False, 'partner_id': source_so.partner_id.id,
                    'route_id': route.id, 'vehicle_source': 'external',
                    'carrier_id': order.partner_id.id, 'purchase_order_id': order.id,
                    'scheduled_date': order.date_planned or fields.Datetime.now(),
                    'cargo_description': pol.cargo_description or pol.name,
                    'base_freight': pol.price_unit,
                })
            if created:
                order.message_post(
                    body=Markup('Đã tự tạo <b>%d lệnh vận chuyển thuê ngoài</b> (nháp): %s') % (
                        len(created), ', '.join(created.mapped('name'))),
                    message_type='notification', subtype_xmlid='mail.mt_note')
            if skipped:
                order.message_post(
                    body=Markup('<b>%d dòng</b> thiếu Điểm đi/Điểm đến — chưa tạo được lệnh VC: %s') % (
                        len(skipped), ', '.join(skipped)),
                    message_type='notification', subtype_xmlid='mail.mt_note')
