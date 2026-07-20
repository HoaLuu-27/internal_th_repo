# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    """Ảnh/thông tin chữ ký dùng chung cho report báo giá, HĐ, phụ lục."""
    _inherit = 'res.company'

    report_header_logo = fields.Image(string='Logo Header')
    report_stamp_image = fields.Image(string='Ảnh con dấu')
    report_signature_image = fields.Image(string='Ảnh chữ ký')
    report_signer_name = fields.Char(string='Người ký')
    report_signer_title = fields.Char(string='Chức vụ')

    # ---- Header/footer report Trang Huy (layout att_external_layout) ----
    report_cert_iso9001 = fields.Image(string='Ảnh ISO 9001')
    report_cert_iso27001 = fields.Image(string='Ảnh ISO 27001')
    report_cert_esg = fields.Image(string='Ảnh ESG')
    report_office_address = fields.Char(
        string='Địa chỉ VPGD',
        help='Văn phòng giao dịch in trên header chứng từ — trụ sở chính '
             'lấy từ địa chỉ công ty chuẩn Odoo.')
    report_hotline = fields.Char(
        string='Hotline',
        help='In trên header/footer chứng từ, VD: 1900299933/ 0903269299.')
