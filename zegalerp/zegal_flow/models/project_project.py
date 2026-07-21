from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    zegal_approval_state = fields.Selection(
        [("draft", "Draft"), ("to_approve", "Waiting Approval"), ("approved", "Approved"), ("rejected", "Rejected")],
        copy=False,
        readonly=True,
    )
    zegal_document_count = fields.Integer(compute="_compute_zegal_counts")
    zegal_approval_count = fields.Integer(compute="_compute_zegal_counts")
    zegal_project_document_count = fields.Integer(compute="_compute_zegal_counts")
    budget_total = fields.Monetary(currency_field="currency_id")
    committed_cost = fields.Monetary(currency_field="currency_id", compute="_compute_budget_metrics")
    actual_cost = fields.Monetary(currency_field="currency_id", compute="_compute_budget_metrics")
    purchase_delay_count = fields.Integer(compute="_compute_budget_metrics")
    subcontract_count = fields.Integer(compute="_compute_budget_metrics")
    budget_remaining = fields.Monetary(currency_field="currency_id", compute="_compute_budget_metrics")
    over_budget = fields.Boolean(compute="_compute_budget_metrics")
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)

    def _compute_zegal_counts(self):
        Approval = self.env["zegal.approval.request"]
        Document = self.env["zegal.project.document"]
        for project in self:
            project.zegal_approval_count = Approval.search_count([("project_id", "=", project.id)])
            project.zegal_document_count = Document.search_count([("project_id", "=", project.id)])
            project.zegal_project_document_count = project.zegal_document_count

    def _compute_budget_metrics(self):
        PurchaseRequest = self.env["zegal.purchase.request"]
        SubContract = self.env["zegal.subcontract"]
        today = fields.Date.context_today(self)
        for project in self:
            prs = PurchaseRequest.search([("project_id", "=", project.id)])
            scs = SubContract.search([("project_id", "=", project.id)])
            project.committed_cost = sum(prs.mapped("budget_total"))
            project.actual_cost = sum(scs.mapped("paid_amount"))
            project.purchase_delay_count = len(prs.filtered(lambda r: r.need_date and r.need_date < today and r.state != "approved"))
            project.subcontract_count = len(scs)
            project.budget_remaining = (project.budget_total or 0.0) - (project.committed_cost or 0.0)
            project.over_budget = project.budget_remaining < 0

    def action_view_zegal_project_documents(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("zegal_flow.action_zegal_project_document")
        action["domain"] = [("project_id", "=", self.id)]
        action["context"] = {"default_project_id": self.id, "search_default_project_id": self.id}
        return action

    def action_create_zegal_project_document(self):
        self.ensure_one()
        doc = self.env["zegal.project.document"].create(
            {
                "name": self.name,
                "project_id": self.id,
                "company_id": self.company_id.id,
                "owner_id": self.env.user.id,
                "document_type": "handover",
                "state": "draft",
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": "Project Document",
            "res_model": "zegal.project.document",
            "view_mode": "form",
            "res_id": doc.id,
            "target": "current",
        }

    def action_view_purchase_requests(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("zegal_flow.action_zegal_purchase_request")
        action["domain"] = [("project_id", "=", self.id)]
        action["context"] = {"default_project_id": self.id}
        return action

    def action_view_subcontracts(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("zegal_flow.action_zegal_subcontract")
        action["domain"] = [("project_id", "=", self.id)]
        action["context"] = {"default_project_id": self.id}
        return action
