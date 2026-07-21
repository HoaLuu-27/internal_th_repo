from odoo import api, fields, models, _


class ZegalPurchaseRequest(models.Model):
    _name = "zegal.purchase.request"
    _description = "Zegal Purchase Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default=lambda self: _("New"), required=True, tracking=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    request_type = fields.Selection(
        [("material", "Material"), ("service", "Service"), ("subcontract", "Subcontract"), ("other", "Other")],
        default="material",
        required=True,
        tracking=True,
    )
    project_id = fields.Many2one("project.project", tracking=True)
    vendor_id = fields.Many2one("res.partner", tracking=True)
    need_date = fields.Date(tracking=True)
    request_date = fields.Date(default=fields.Date.context_today, tracking=True)
    line_ids = fields.One2many("zegal.purchase.request.line", "request_id", string="Lines")
    budget_total = fields.Monetary(currency_field="currency_id", compute="_compute_budget_total", store=True)
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    lead_time_days = fields.Integer(compute="_compute_lead_time_days", store=True)
    state = fields.Selection(
        [("draft", "Draft"), ("to_approve", "Waiting Approval"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="draft",
        tracking=True,
    )
    note = fields.Text()
    approval_request_id = fields.Many2one("zegal.approval.request", copy=False)
    rfq_count = fields.Integer(compute="_compute_po_counts")
    po_count = fields.Integer(compute="_compute_po_counts")

    def action_submit(self):
        for rec in self:
            if rec.approval_request_id:
                continue
            req = self.env["zegal.approval.request"].create(
                {
                    "request_type": "purchase_po",
                    "approval_scope": "purchase",
                    "department_code": "purchase",
                    "purchase_order_id": False,
                    "project_id": rec.project_id.id,
                    "company_id": rec.company_id.id,
                    "partner_id": rec.vendor_id.id,
                    "source_ref": rec.name,
                    "amount_total": rec.budget_total,
                    "note": rec.note,
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

    def action_reject(self):
        self.write({"state": "rejected"})

    def action_create_rfq(self):
        self.ensure_one()
        order = self.env["purchase.order"].create(
            {
                "partner_id": self.vendor_id.id or self.env.company.partner_id.id,
                "company_id": self.company_id.id,
                "origin": self.name,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": "RFQ",
            "res_model": "purchase.order",
            "view_mode": "form",
            "res_id": order.id,
            "target": "current",
        }

    def action_create_po(self):
        return self.action_create_rfq()

    @api.depends("line_ids.budget_amount")
    def _compute_budget_total(self):
        for rec in self:
            rec.budget_total = sum(rec.line_ids.mapped("budget_amount"))

    @api.depends("request_date", "need_date")
    def _compute_lead_time_days(self):
        for rec in self:
            rec.lead_time_days = (rec.need_date - rec.request_date).days if rec.request_date and rec.need_date else 0

    def _compute_po_counts(self):
        for rec in self:
            rec.rfq_count = self.env["purchase.order"].search_count([("origin", "=", rec.name)])
            rec.po_count = rec.rfq_count


class ZegalPurchaseRequestLine(models.Model):
    _name = "zegal.purchase.request.line"
    _description = "Zegal Purchase Request Line"

    request_id = fields.Many2one("zegal.purchase.request", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True)
    description = fields.Char()
    quantity = fields.Float(default=1.0)
    uom_id = fields.Many2one("uom.uom", required=True)
    budget_amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="request_id.company_id.currency_id", readonly=True)
