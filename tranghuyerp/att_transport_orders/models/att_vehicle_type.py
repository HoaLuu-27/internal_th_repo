from odoo import fields, models


class AttVehicleType(models.Model):
    """Bổ sung quan hệ ngược Loại xe ↔ Sản phẩm dịch vụ vận chuyển. Model gốc
    att.vehicle.type ở att_fleet_extend; quan hệ với product.product khai
    báo tại đây (lớp att_transport_orders nhìn được cả 2)."""
    _inherit = "att.vehicle.type"

    transport_mode_ids = fields.Many2many(
        "product.product", "att_product_vehicle_type_rel",
        "vehicle_type_id", "product_id", string="Sản phẩm dịch vụ áp dụng")
