from odoo import fields, models


class AttVehicleType(models.Model):
    """Bổ sung quan hệ ngược Loại xe ↔ Hình thức VC. Model gốc att.vehicle.type
    ở att_fleet_extend; quan hệ với att.transport.mode khai báo tại đây (lớp
    att_transport_order nhìn được cả 2)."""
    _inherit = "att.vehicle.type"

    transport_mode_ids = fields.Many2many(
        "att.transport.mode", "att_mode_vehicle_type_rel",
        "vehicle_type_id", "mode_id", string="Hình thức vận chuyển áp dụng")
