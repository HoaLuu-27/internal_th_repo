from odoo import fields, models


class ZegalApprovalMatrix(models.Model):
    _name = "zegal.approval.matrix"
    _description = "Zegal Approval Matrix"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    request_type = fields.Selection(
        [
            ("sale_quote", "Sales Quote"),
            ("purchase_po", "Purchase Order"),
            ("stock_out", "Stock Out"),
            ("project_cost", "Project Cost"),
            ("document", "Document"),
        ],
        required=True,
        default="sale_quote",
    )
    department_code = fields.Selection(
        [
            ("sales", "Sales"),
            ("purchase", "Purchase"),
            ("warehouse", "Warehouse"),
            ("accounting", "Accounting"),
            ("project", "Project"),
            ("document", "Document"),
        ]
    )
    approval_scope = fields.Selection(
        [("internal", "Internal Approval"), ("quote", "Quote Approval"), ("purchase", "Purchase Approval"), ("expense", "Expense Approval"), ("handover", "Handover Approval")],
        default="internal",
        required=True,
    )
    min_amount = fields.Monetary(currency_field="currency_id")
    max_amount = fields.Monetary(currency_field="currency_id")
    min_margin = fields.Float()
    approver_id = fields.Many2one("res.users", required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    active = fields.Boolean(default=True)
