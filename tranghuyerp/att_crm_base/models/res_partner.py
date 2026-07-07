from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    phone = fields.Char(
        tracking=False,
    )

    phone_masked = fields.Char(
        string="Phone",
        compute="_compute_phone_masked",
        readonly=True,
    )

    def _mask_phone_number(self, value):
        if not value:
            return False

        value = value.strip()

        if len(value) <= 6:
            return "*" * len(value)

        return value[:4] + "*" * (len(value) - 6) + value[-2:]

    @api.depends("phone")
    def _compute_phone_masked(self):
        for rec in self:
            rec.phone_masked = rec._mask_phone_number(rec.phone)