from odoo import fields, models


class AttTransportMode(models.Model):
    _name = "att.transport.mode"
    _description = "Hình thức vận chuyển"
    _order = "sequence, name"

    name = fields.Char(string="Tên hình thức vận chuyển", required=True)
    code = fields.Char(string="Mã")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    # Website
    website_published = fields.Boolean(string="Hiển thị website", default=False)
    image = fields.Image(string="Ảnh dịch vụ")
    website_description = fields.Html(string="Mô tả website")
    default_product_id = fields.Many2one(
        "product.product",
        string="Sản phẩm dịch vụ mặc định",
        domain=[("sale_ok", "=", True)],
        help="Dùng để tạo dòng SO draft từ form yêu cầu báo giá.",
    )