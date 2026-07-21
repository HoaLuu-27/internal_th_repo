from odoo import fields, models


class ZegalApprovalLog(models.Model):
    _name = "zegal.approval.log"
    _description = "Zegal Approval Log"
    _order = "create_date desc, id desc"

    request_id = fields.Many2one("zegal.approval.request", required=True, ondelete="cascade")
    state_from = fields.Char()
    state_to = fields.Char()
    action = fields.Selection(
        [("submit", "Submit"), ("approve", "Approve"), ("reject", "Reject"), ("reset", "Reset")],
        required=True,
    )
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    note = fields.Text()
    create_date = fields.Datetime(readonly=True)
