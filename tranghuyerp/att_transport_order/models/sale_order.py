from markupsafe import Markup

from odoo import api, fields, models, _


class SaleOrderLine(models.Model):
    """Field vận chuyển trên dòng SO — đặt ở att_transport_order (lớp vận tải)
    để CẢ báo giá (att_quotations_contracts) LẪN điều vận đều dùng chung."""
    _inherit = 'sale.order.line'

    pickup_location = fields.Char(string='Điểm đi')
    delivery_location = fields.Char(string='Điểm đến')
    transport_mode_id = fields.Many2one('att.transport.mode', string='Loại hình dịch vụ')
    vehicle_type_id = fields.Many2one(
        'att.vehicle.type', string='Loại xe vận chuyển',
        domain="[('transport_mode_ids', 'in', transport_mode_id)] if transport_mode_id else []")
    vehicle_id = fields.Many2one('fleet.vehicle', string='Phương tiện')
    cargo_description = fields.Text(string='Mô tả hàng hóa')
    cargo_weight = fields.Char('Khối lượng')
    expected_date = fields.Datetime(string='Thời gian dự kiến')

    transport_order_ids = fields.One2many('att.transport.order', 'sale_order_line_id',
                                          'Lệnh vận chuyển')
    transport_order_count = fields.Integer(compute='_compute_transport_order_count')

    @api.depends('transport_order_ids')
    def _compute_transport_order_count(self):
        for rec in self:
            rec.transport_order_count = len(rec.transport_order_ids)


class SaleOrder(models.Model):
    """1 SO → N TO. Smart button + auto-sinh TO khi confirm SO."""
    _inherit = 'sale.order'

    transport_order_ids = fields.One2many('att.transport.order', 'sale_order_id', 'Lệnh vận chuyển')
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
            for sol in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
                if TO.search_count([('sale_order_line_id', '=', sol.id),
                                    ('state', '!=', 'cancelled')]):
                    continue
                route = Route._find_or_create(sol.pickup_location, sol.delivery_location)
                if not route:
                    skipped.append(sol.name)
                    continue
                vehicle = sol.vehicle_id
                created += TO.create({
                    'origin_type': 'sale', 'sale_order_id': order.id,
                    'sale_order_line_id': sol.id, 'partner_id': order.partner_id.id,
                    'route_id': route.id,
                    'scheduled_date': sol.expected_date or fields.Datetime.now(),
                    'vehicle_id': vehicle.id or False,
                    'driver_id': vehicle.default_driver_employee_id.id if vehicle else False,
                    'cargo_description': sol.cargo_description or sol.name,
                    'base_freight': sol.price_unit,
                })
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
