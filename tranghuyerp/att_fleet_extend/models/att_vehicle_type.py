from odoo import fields, models, api, _


class AttVehicleType(models.Model):
    _name = "att.vehicle.type"
    _description = "Loại xe vận chuyển"
    _order = "sequence, name"

    name = fields.Char(string="Tên loại xe", required=True)
    code = fields.Char(string="Mã")
    sequence = fields.Integer(default=10)

    length_cm = fields.Float(string="Dài thùng xe (cm)")
    width_cm = fields.Float(string="Rộng thùng xe (cm)")
    height_cm = fields.Float(string="Cao thùng xe (cm)")

    dimension_text = fields.Char(
        string="Kích thước thùng xe",
        compute="_compute_dimension_text",
        store=True,
    )

    max_weight_kg = fields.Float(string="Tải trọng tối đa (kg)")
    max_weight_per_package_kg = fields.Float(string="Tối đa kg/kiện")

    max_volume_m3 = fields.Float(
        string="Thể tích tối đa (m³)",
        compute="_compute_max_volume_m3",
        store=True,
    )

    description = fields.Text(string="Diễn giải")
    active = fields.Boolean(default=True)

    @api.depends("length_cm", "width_cm", "height_cm")
    def _compute_dimension_text(self):
        for rec in self:
            values = [rec.length_cm, rec.width_cm, rec.height_cm]
            if all(values):
                rec.dimension_text = "%s x %s x %s" % (
                    int(rec.length_cm),
                    int(rec.width_cm),
                    int(rec.height_cm),
                )
            else:
                rec.dimension_text = False

    @api.depends("length_cm", "width_cm", "height_cm")
    def _compute_max_volume_m3(self):
        for rec in self:
            if rec.length_cm and rec.width_cm and rec.height_cm:
                rec.max_volume_m3 = (
                    rec.length_cm * rec.width_cm * rec.height_cm
                ) / 1000000
            else:
                rec.max_volume_m3 = 0.0