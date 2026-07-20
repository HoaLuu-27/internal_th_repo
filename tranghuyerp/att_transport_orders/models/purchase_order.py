from markupsafe import Markup

from odoo import api, fields, models, _


class PurchaseOrderLine(models.Model):
    """Field vận chuyển trên dòng PO — trùng bộ với SOL để map 1:1 qua phụ lục."""
    _inherit = 'purchase.order.line'

    pickup_location = fields.Char(string='Điểm đi')
    delivery_location = fields.Char(string='Điểm đến')
    pickup_lat = fields.Float('Vĩ độ điểm đi', digits=(10, 7))
    pickup_lng = fields.Float('Kinh độ điểm đi', digits=(10, 7))
    delivery_lat = fields.Float('Vĩ độ điểm đến', digits=(10, 7))
    delivery_lng = fields.Float('Kinh độ điểm đến', digits=(10, 7))
    # Hình thức vận chuyển = chính product_id (xem sale_order.py)
    vehicle_type_id = fields.Many2one(
        'att.vehicle.type', string='Loại xe vận chuyển',
        domain="[('transport_mode_ids', 'in', product_id)] if product_id else []")
    vehicle_id = fields.Many2one('fleet.vehicle', string='Phương tiện')
    cargo_description = fields.Text(string='Mô tả hàng hóa')


class PurchaseOrder(models.Model):
    """1 PO → N TO thuê ngoài (mỗi TO gắn đúng 1 PO — BR-DV-011).

    att_source_sale_order_id do att_contract_management (att_purchase_quotation.py)
    khai báo — module này phụ thuộc thẳng vào att_contract_management (khai
    trong depends) nên đọc trực tiếp, không cần getattr phòng thủ nữa."""
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

    @api.model
    def action_new_rfq_for_route(self, route_vals):
        """Bản mua của sale.order.action_new_quotation_for_route — mở form
        RFQ mới với sẵn 1 dòng mang điểm đi/đến + toạ độ từ panel Tìm
        đường (thuê NCC chạy tuyến này). POL hiển thị thẳng pickup_location
        (Char) nên không cần record att.address.suggestion như bên bán."""
        product = self.env.ref('att_transport_orders.product_tmode_duong_bo',
                               raise_if_not_found=False)
        line_vals = {
            'product_id': product.id if product else False,
            'name': product.name if product else _('Vận chuyển đường bộ'),
            'product_qty': 1.0,
            'pickup_location': route_vals.get('origin_name') or '',
            'pickup_lat': route_vals.get('origin_lat') or 0.0,
            'pickup_lng': route_vals.get('origin_lng') or 0.0,
            'delivery_location': route_vals.get('destination_name') or '',
            'delivery_lat': route_vals.get('destination_lat') or 0.0,
            'delivery_lng': route_vals.get('destination_lng') or 0.0,
        }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Báo giá mua từ tuyến tìm được'),
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
            'context': {'default_order_line': [fields.Command.create(line_vals)]},
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
            source_so = order.att_source_sale_order_id
            if not source_so:
                order.message_post(
                    body=Markup('PO không có <b>SO nguồn</b> — không xác định được khách hàng của chuyến, điều vận tạo lệnh VC thủ công (menu Điều vận).'),
                    message_type='notification', subtype_xmlid='mail.mt_note')
                continue
            created = TO.browse()
            skipped = []
            for pol in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
                route = Route._find_or_create(
                    pol.pickup_location, pol.delivery_location,
                    pol.pickup_lat, pol.pickup_lng,
                    pol.delivery_lat, pol.delivery_lng)
                if not route:
                    skipped.append(pol.name)
                    continue
                sol = source_so.order_line.filtered(
                    lambda l: not l.display_type
                    and (l.pickup_location or '').strip().lower() == (pol.pickup_location or '').strip().lower()
                    and (l.delivery_location or '').strip().lower() == (pol.delivery_location or '').strip().lower())[:1]
                to = TO.create({
                    'origin_type': 'sale', 'sale_order_id': source_so.id,
                    'sale_order_line_id': sol.id or False, 'partner_id': source_so.partner_id.id,
                    'route_id': route.id, 'vehicle_source': 'external',
                    'carrier_id': order.partner_id.id, 'purchase_order_id': order.id,
                    'scheduled_date': order.date_planned or fields.Datetime.now(),
                    'cargo_description': pol.cargo_description or pol.name,
                    'base_freight': pol.price_unit,
                })
                self.env['att.transport.cost.line']._copy_route_lines_to_order(route, to)
                created += to
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
