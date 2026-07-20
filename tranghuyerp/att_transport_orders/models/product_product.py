from odoo import fields, models


class ProductProduct(models.Model):
    """Hình thức vận chuyển (Đường bộ, Đa phương thức...) CHÍNH LÀ sản phẩm
    dịch vụ — không tách model att.transport.mode riêng nữa. Product đã có
    sẵn cơ chế ảnh/publish/mô tả, tự custom trang web dễ hơn."""
    _inherit = 'product.product'

    website_published = fields.Boolean(string='Hiển thị website', default=False)
    image = fields.Image(string='Ảnh dịch vụ')
    website_short_description = fields.Text(string='Mô tả website')

    # Mỗi sản phẩm dịch vụ vận chuyển có nhiều loại xe phù hợp
    # (att.vehicle.type ở att_fleet_extend)
    vehicle_type_ids = fields.Many2many(
        'att.vehicle.type', 'att_product_vehicle_type_rel',
        'product_id', 'vehicle_type_id', string='Loại xe áp dụng')
