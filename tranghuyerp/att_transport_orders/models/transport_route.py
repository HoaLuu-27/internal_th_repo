from odoo import api, fields, models, _
from math import radians, sin, cos, sqrt, atan2
import json
import logging


_logger = logging.getLogger(__name__)



class AttTransportRoute(models.Model):
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
    route_geometry = fields.Text(
        'Toạ độ chi tiết tuyến (JSON)',
        help='List [[lat,lng],...] lấy từ VietMap Route v4 — dùng để vẽ '
             'polyline lên bản đồ nhiệt, không hiển thị trực tiếp cho user.')
    reverse_route_id = fields.Many2one('att.transport.route', 'Tuyến ngược chiều',
                                       help='Tuyến chiều về — phát hiện cơ hội backhaul.')
    vendor_route_ids = fields.One2many('att.vendor.route.rule', 'route_id', 'NCC chuyên tuyến')
    cost_line_ids = fields.One2many('att.transport.cost.line', 'route_id', 'Chi phí phát sinh')
    cost_total = fields.Monetary('Tổng chi phí', compute='_compute_cost_total',
                                 currency_field='currency_id')
    currency_id = fields.Many2one('res.currency',
                                  default=lambda self: self.env.company.currency_id)
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

    @api.depends('cost_line_ids.amount')
    def _compute_cost_total(self):
        for rec in self:
            rec.cost_total = sum(rec.cost_line_ids.mapped('amount'))


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

    def action_resolve_route_info(self, vehicle='truck', capacity=None):
        """Gọi VietMap Route v4 lấy khoảng cách/thời gian thật — chỉ gọi khi
        CHƯA có ĐỦ dữ liệu (route mới tạo, HOẶC route cũ từ trước khi có
        field route_geometry — thiếu geometry vẫn gọi lại để bổ sung, dù đã
        có sẵn distance_km), tránh gọi lại tốn phí cho route đã có sẵn ĐẦY ĐỦ.
        KHÔNG raise lỗi — API tạm trục trặc không được chặn việc tạo
        Transport Order/confirm SO chỉ vì thiếu số liệu tham khảo này.
        vehicle/capacity nên truyền từ att.vehicle.type._vietmap_route_params()
        của xe thực tế chạy tuyến, không hardcode chung 1 loại cho mọi tuyến."""
        self.ensure_one()
        # route_geometry lưu JSON string — "[]" (mảng rỗng) vẫn là chuỗi
        # KHÔNG rỗng nên truthy trong Python, phải so sánh rõ với "[]" chứ
        # không chỉ kiểm tra truthy, nếu không sẽ chặn nhầm route có
        # geometry rỗng (lấy thất bại) không cho gọi lại lần sau.
        if (self.distance_km or self.eta_minutes) and self.route_geometry not in (False, '', '[]'):
            return
        config = self.env['att.vietmap.config']._get_active_config()
        if not config:
            return
        try:
            info = self.env['att.vietmap.api'].get_route_info(
                config, self.origin_lat, self.origin_lng,
                self.destination_lat, self.destination_lng,
                vehicle=vehicle, capacity=capacity)
            self.write({
                'distance_km': info.get('distance_km') or 0.0,
                'eta_minutes': info.get('eta_minutes') or 0,
                'route_geometry': json.dumps(info.get('geometry') or []),
            })
            self.env['att.transport.cost.line']._create_from_route_tolls(
                self, info.get('tolls'))
        except Exception:
            _logger.warning('Không lấy được khoảng cách/thời gian tuyến %s', self.name, exc_info=True)

    @api.model
    def _find_or_create(self, origin_name, destination_name, origin_lat, origin_lng,
                        destination_lat, destination_lng):
        if not origin_name or not destination_name:
            return self.browse()
        route = self.search([
            ('origin_name', '=ilike', origin_name.strip()),
            ('destination_name', '=ilike', destination_name.strip()),
            ('origin_lat', '=', origin_lat),
            ('origin_lng', '=', origin_lng),
            ('destination_lat', '=', destination_lat),
            ('destination_lng', '=', destination_lng),
        ], limit=1)
        if not route:
            route = self.create({
                'name': '%s – %s' % (origin_name.strip(), destination_name.strip()),
                'origin_name': origin_name.strip(), 'destination_name': destination_name.strip(),
                'origin_lat': origin_lat, 'origin_lng': origin_lng,
                'destination_lat': destination_lat, 'destination_lng': destination_lng,
            })
        return route




class AttVendorRouteRule(models.Model):
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


class AttCommodity(models.Model):
    """Loại hàng hóa: hàng thường / vật tư / máy móc / hàng quá khổ (SRS 2.5.1)."""
    _name = 'att.commodity'
    _description = 'Loại hàng hóa'
    _order = 'name'

    name = fields.Char('Tên loại hàng', required=True)
    is_oversized = fields.Boolean('Hàng quá khổ/siêu trường',
                                  help='Hàng siêu trường → thuê ngoài, permit đặc biệt.')
    note = fields.Text('Ghi chú')
    active = fields.Boolean(default=True)
