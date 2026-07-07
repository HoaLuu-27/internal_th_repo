from odoo import fields, models


class ResCompany(models.Model):
    """Ảnh/thông tin chữ ký dùng chung cho report báo giá, HĐ, phụ lục."""
    _inherit = "res.company"

    report_header_logo = fields.Image(string="Logo Header")
    report_esg_logo = fields.Image(string="Logo ESG / Logistics xanh")
    report_footer_image = fields.Image(string="Ảnh Footer")
    report_stamp_image = fields.Image(string="Ảnh con dấu")
    report_signature_image = fields.Image(string="Ảnh chữ ký")
    report_signer_name = fields.Char(string="Người ký")
    report_signer_title = fields.Char(string="Chức vụ")
