from odoo import fields, models


class AttTransportMode(models.Model):
    """Hình thức vận chuyển (Loại hình dịch vụ) — Đường bộ, Đa phương thức,
    Đường biển... Dùng chung cho dòng SO/PO báo giá, phụ lục và lệnh vận chuyển.

    Đặt ở att_transport_order (lớp vận tải). att_quotations_contracts (lớp trên)
    tham chiếu tới đây."""
    _name = "att.transport.mode"
    _description = "Hình thức vận chuyển"
    _order = "sequence, name"

    name = fields.Char(string="Tên hình thức vận chuyển", required=True)
    code = fields.Char(string="Mã")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    website_published = fields.Boolean(string="Hiển thị website", default=False)
    image = fields.Image(string="Ảnh dịch vụ")
    website_short_description = fields.Text(string="Mô tả website")
    default_product_id = fields.Many2one(
        "product.product", string="Sản phẩm dịch vụ mặc định",
        domain=[("sale_ok", "=", True)],
        help="Sản phẩm dịch vụ dùng để tạo dòng SO draft khi khách gửi yêu cầu báo giá.")

    # Mỗi hình thức VC có nhiều loại xe phù hợp (att.vehicle.type ở att_fleet_extend)
    vehicle_type_ids = fields.Many2many(
        "att.vehicle.type", "att_mode_vehicle_type_rel",
        "mode_id", "vehicle_type_id", string="Loại xe áp dụng")
