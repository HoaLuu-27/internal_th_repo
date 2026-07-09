from odoo import api, fields, models, _


class ThTransportRoute(models.Model):
    """Tuyến đường chuẩn (SRS 2.5.4) — xương sống bản đồ nhiệt.
    Tọa độ GPS 2 đầu để vẽ polyline; tuyến ngược để phát hiện chuyến về."""
    _name = 'att.transport.route'
    _description = 'Tuyến đường vận chuyển'
    _order = 'name'

    name = fields.Char('Tên tuyến', required=True)
    origin_name = fields.Char('Điểm đi', required=True)
    destination_name = fields.Char('Điểm đến', required=True)
    distance_km = fields.Float('Khoảng cách (km)')
    eta_minutes = fields.Integer('Thời gian ước tính (phút)')
    origin_lat = fields.Float('GPS điểm đi (lat)', digits=(10, 7))
    origin_lng = fields.Float('GPS điểm đi (lng)', digits=(10, 7))
    destination_lat = fields.Float('GPS điểm đến (lat)', digits=(10, 7))
    destination_lng = fields.Float('GPS điểm đến (lng)', digits=(10, 7))
    reverse_route_id = fields.Many2one('att.transport.route', 'Tuyến ngược chiều',
                                       help='Tuyến chiều về — phát hiện cơ hội backhaul.')
    vendor_route_ids = fields.One2many('att.vendor.route.rule', 'route_id', 'NCC chuyên tuyến')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    active_to_count = fields.Integer('Lệnh đang chạy', compute='_compute_active_to_count')

    @api.onchange('origin_name', 'destination_name')
    def _onchange_points(self):
        for rec in self:
            if rec.origin_name and rec.destination_name and not rec.name:
                rec.name = '%s – %s' % (rec.origin_name, rec.destination_name)

    def _compute_active_to_count(self):
        data = self.env['att.transport.order']._read_group(
            [('route_id', 'in', self.ids), ('state', '=', 'in_transit')],
            ['route_id'], ['__count'])
        counts = {route.id: count for route, count in data}
        for rec in self:
            rec.active_to_count = counts.get(rec.id, 0)

    @api.model
    def _find_or_create(self, origin, destination):
        """Tìm tuyến theo cặp điểm đi/đến; chưa có thì tạo — phục vụ auto-sinh
        TO khi confirm SO/PO. Rỗng nếu thiếu 1 trong 2 điểm."""
        if not origin or not destination:
            return self.browse()
        route = self.search([
            ('origin_name', '=ilike', origin.strip()),
            ('destination_name', '=ilike', destination.strip()),
        ], limit=1)
        if not route:
            route = self.create({
                'name': '%s – %s' % (origin.strip(), destination.strip()),
                'origin_name': origin.strip(),
                'destination_name': destination.strip(),
            })
        return route

    def action_view_transport_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Lệnh vận chuyển tuyến %s') % self.name,
            'res_model': 'att.transport.order',
            'view_mode': 'list,form',
            'domain': [('route_id', '=', self.id)],
            'context': {'default_route_id': self.id},
        }


class ThVendorRouteRule(models.Model):
    """NCC chuyên tuyến (SRS 2.5.5) — gợi ý carrier khi TO thuê ngoài."""
    _name = 'att.vendor.route.rule'
    _description = 'Nhà cung cấp chuyên tuyến'
    _order = 'priority, id'

    route_id = fields.Many2one('att.transport.route', 'Tuyến đường', required=True,
                               ondelete='cascade', index=True)
    vendor_id = fields.Many2one('res.partner', 'Nhà cung cấp', required=True,
                                domain=[('supplier_rank', '>', 0)])
    vehicle_type_id = fields.Many2one('att.vehicle.type', 'Loại xe')
    price_per_trip = fields.Monetary('Giá/chuyến', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency',
                                  default=lambda self: self.env.company.currency_id)
    priority = fields.Integer('Mức ưu tiên', default=0, help='Số nhỏ = ưu tiên cao hơn.')
    active = fields.Boolean(default=True)


class ThCommodity(models.Model):
    """Loại hàng hóa: hàng thường / vật tư / máy móc / hàng quá khổ (SRS 2.5.1)."""
    _name = 'att.commodity'
    _description = 'Loại hàng hóa'
    _order = 'name'

    name = fields.Char('Tên loại hàng', required=True)
    is_oversized = fields.Boolean('Hàng quá khổ/siêu trường',
                                  help='Hàng siêu trường → thuê ngoài, permit đặc biệt.')
    note = fields.Text('Ghi chú')
    active = fields.Boolean(default=True)
