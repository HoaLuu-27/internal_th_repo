from odoo import fields, models, _


class ZegalSubContract(models.Model):
    _name = "zegal.subcontract"
    _description = "Zegal Subcontract"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default=lambda self: _("New"), required=True, tracking=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    project_id = fields.Many2one("project.project", required=True, tracking=True)
    partner_id = fields.Many2one("res.partner", required=True, tracking=True)
    source_request_id = fields.Many2one("zegal.purchase.request")
    approval_request_id = fields.Many2one("zegal.approval.request")
    state = fields.Selection(
        [("draft", "Draft"), ("to_approve", "Waiting Approval"), ("approved", "Approved"), ("in_progress", "In Progress"), ("accepted", "Accepted"), ("paid", "Paid"), ("cancelled", "Cancelled")],
        default="draft",
        tracking=True,
    )
    scope = fields.Text(required=True)
    start_date = fields.Date(tracking=True)
    end_date = fields.Date(tracking=True)
    amount_total = fields.Monetary(currency_field="currency_id", tracking=True)
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    line_ids = fields.One2many("zegal.subcontract.line", "subcontract_id", string="Lines")
    acceptance_ids = fields.One2many("zegal.subcontract.acceptance", "subcontract_id", string="Acceptance")
    note = fields.Text()
    paid_amount = fields.Monetary(compute="_compute_paid_amount", store=True, currency_field="currency_id")
    unbilled_amount = fields.Monetary(compute="_compute_unbilled_amount", store=True, currency_field="currency_id")

    def action_submit(self):
        for rec in self:
            req = self.env["zegal.approval.request"].create(
                {
                    "request_type": "purchase_po",
                    "approval_scope": "purchase",
                    "department_code": "purchase",
                    "project_id": rec.project_id.id,
                    "company_id": rec.company_id.id,
                    "source_ref": rec.name,
                    "partner_id": rec.partner_id.id,
                    "amount_total": rec.amount_total,
                    "note": rec.scope,
                    "checklist_scope": True,
                    "checklist_budget": True,
                    "checklist_terms": True,
                    "checklist_attachment": True,
                }
            )
            rec.approval_request_id = req.id
            rec.state = "to_approve"
            req.action_submit()

    def action_approve(self):
        self.write({"state": "approved"})

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_accept(self):
        self.write({"state": "accepted"})

    def action_mark_paid(self):
        self.write({"state": "paid"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def _compute_paid_amount(self):
        for rec in self:
            rec.paid_amount = sum(rec.acceptance_ids.filtered(lambda l: l.state == "paid").mapped("amount"))

    def _compute_unbilled_amount(self):
        for rec in self:
            rec.unbilled_amount = max((rec.amount_total or 0.0) - (rec.paid_amount or 0.0), 0.0)


class ZegalSubContractLine(models.Model):
    _name = "zegal.subcontract.line"
    _description = "Zegal Subcontract Line"

    subcontract_id = fields.Many2one("zegal.subcontract", required=True, ondelete="cascade")
    name = fields.Char(required=True)
    scope = fields.Text()
    quantity = fields.Float(default=1.0)
    uom_id = fields.Many2one("uom.uom")
    unit_price = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="subcontract_id.currency_id", readonly=True)
    total_amount = fields.Monetary(compute="_compute_total_amount", store=True, currency_field="currency_id")
    timeline_start = fields.Date()
    timeline_end = fields.Date()

    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = (rec.quantity or 0.0) * (rec.unit_price or 0.0)


class ZegalSubContractAcceptance(models.Model):
    _name = "zegal.subcontract.acceptance"
    _description = "Zegal Subcontract Acceptance"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    subcontract_id = fields.Many2one("zegal.subcontract", required=True, ondelete="cascade")
    name = fields.Char(default=lambda self: _("New"), required=True)
    acceptance_date = fields.Date(default=fields.Date.context_today, required=True)
    quantity = fields.Float(default=1.0)
    amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="subcontract_id.currency_id", readonly=True)
    state = fields.Selection([("draft", "Draft"), ("approved", "Approved"), ("paid", "Paid")], default="draft")
    note = fields.Text()
    payment_approval_id = fields.Many2one("zegal.approval.request", copy=False)

    def action_approve(self):
        self.write({"state": "approved"})
        req = self.env["zegal.approval.request"].create(
            {
                "request_type": "purchase_po",
                "approval_scope": "purchase",
                "department_code": "purchase",
                "project_id": self.subcontract_id.project_id.id,
                "company_id": self.subcontract_id.company_id.id,
                "source_ref": self.name,
                "partner_id": self.subcontract_id.partner_id.id,
                "amount_total": self.amount,
                "note": self.note,
                "checklist_scope": True,
                "checklist_budget": True,
                "checklist_terms": True,
                "checklist_attachment": True,
            }
        )
        self.payment_approval_id = req.id
        req.action_submit()

    def action_paid(self):
        self.write({"state": "paid"})
