from odoo import fields, models


class AttContractAppendix(models.Model):
    """Override hook của att_contract_management: khi nạp dòng từ báo giá
    nguồn vào phụ lục, mang thêm field logistics theo — module contract
    không biết field này tồn tại, chỉ module vận tải override được."""
    _inherit = 'att.contract.appendix'

    def _prepare_appendix_line_vals(self, sol):
        vals = super()._prepare_appendix_line_vals(sol)
        if not sol.display_type:
            vals.update({
                'pickup_location': sol.pickup_location,
                'delivery_location': sol.delivery_location,
                'pickup_lat': sol.pickup_lat,
                'pickup_lng': sol.pickup_lng,
                'delivery_lat': sol.delivery_lat,
                'delivery_lng': sol.delivery_lng,
                'vehicle_type_id': sol.vehicle_type_id.id,
                'vehicle_id': sol.vehicle_id.id,
                'cargo_description': sol.cargo_description,
            })
        return vals


class AttContractAppendixLine(models.Model):
    """Thêm field logistics trên dòng phụ lục (đồng bộ SOL/POL) + override
    hook sinh SO thực thi để mang field này xuống dòng SO mới, giúp
    _th_auto_create_transport_orders (sale_order.py) có đủ Điểm đi/Điểm đến
    + TOẠ ĐỘ tạo Lệnh vận chuyển ngay khi confirm — thiếu toạ độ thì Route
    vẫn tạo được nhưng toạ độ = 0, không gọi được VietMap.

    Hình thức vận chuyển = chính product_id (field đã có sẵn trên
    att.contract.appendix.line gốc) — không cần field transport_mode_id
    riêng nữa."""
    _inherit = 'att.contract.appendix.line'

    pickup_location = fields.Char(string='Điểm đi')
    delivery_location = fields.Char(string='Điểm đến')
    pickup_lat = fields.Float('Vĩ độ điểm đi', digits=(10, 7))
    pickup_lng = fields.Float('Kinh độ điểm đi', digits=(10, 7))
    delivery_lat = fields.Float('Vĩ độ điểm đến', digits=(10, 7))
    delivery_lng = fields.Float('Kinh độ điểm đến', digits=(10, 7))
    vehicle_type_id = fields.Many2one(
        'att.vehicle.type', string='Loại xe vận chuyển',
        domain="[('transport_mode_ids', 'in', product_id)] if product_id else []")
    vehicle_id = fields.Many2one('fleet.vehicle', string='Phương tiện')
    cargo_description = fields.Text(string='Mô tả hàng hóa')

    def _prepare_sale_order_line_vals(self):
        vals = super()._prepare_sale_order_line_vals()
        if not self.display_type:
            vals.update({
                'pickup_location': self.pickup_location,
                'delivery_location': self.delivery_location,
                'pickup_lat': self.pickup_lat,
                'pickup_lng': self.pickup_lng,
                'delivery_lat': self.delivery_lat,
                'delivery_lng': self.delivery_lng,
                'vehicle_type_id': self.vehicle_type_id.id,
                'vehicle_id': self.vehicle_id.id,
                'cargo_description': self.cargo_description,
            })
        return vals
