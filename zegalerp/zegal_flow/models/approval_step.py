from odoo import fields, models


class ZegalApprovalStep(models.Model):
    _name = "zegal.approval.step"
    _description = "Zegal Approval Step"
    _order = "sequence, id"

    request_id = fields.Many2one("zegal.approval.request", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    approver_id = fields.Many2one("res.users", required=True)
    state = fields.Selection([("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")], default="pending")
    note = fields.Text()
