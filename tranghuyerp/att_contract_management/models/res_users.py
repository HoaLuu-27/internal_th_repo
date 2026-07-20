# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsers(models.Model):
    """Ảnh chữ ký nhân viên — dùng cho các flow ký/duyệt sau này."""
    _inherit = 'res.users'

    signature_image = fields.Image(string='Ảnh chữ ký')
