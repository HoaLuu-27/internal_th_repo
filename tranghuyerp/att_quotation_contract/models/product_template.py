from odoo import fields, models


class AttTransportMode(models.Model):
    _name = "att.transport.mode"
    _description = "Hình thức vận chuyển"
    _order = "sequence, name"

    name = fields.Char(string="Tên hình thức vận chuyển", required=True)
    code = fields.Char(string="Mã")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)