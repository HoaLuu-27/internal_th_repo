from odoo import fields, models


class StockMove(models.Model):
    _inherit = "stock.move"

    project_id = fields.Many2one("project.project")
    zegal_required_date = fields.Date()
    zegal_delay_flag = fields.Boolean(compute="_compute_zegal_delay_flag")
    zegal_delay_days = fields.Integer(compute="_compute_zegal_delay_flag")

    def _compute_zegal_delay_flag(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.zegal_required_date and rec.zegal_required_date < today:
                rec.zegal_delay_flag = True
                rec.zegal_delay_days = (today - rec.zegal_required_date).days
            else:
                rec.zegal_delay_flag = False
                rec.zegal_delay_days = 0
