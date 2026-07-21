from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    zegal_approval_request_id = fields.Many2one("zegal.approval.request", copy=False)
    zegal_approval_state = fields.Selection(
        [("draft", "Draft"), ("to_approve", "Waiting Approval"), ("approved", "Approved"), ("rejected", "Rejected")],
        copy=False,
        readonly=True,
    )
    project_id = fields.Many2one("project.project")
    checklist_scope = fields.Boolean(string="Scope Confirmed")
    checklist_budget = fields.Boolean(string="Budget Checked")
    checklist_timeline = fields.Boolean(string="Timeline Checked")
    checklist_attachment = fields.Boolean(string="Attachments Ready")
    checklist_terms = fields.Boolean(string="Terms Confirmed")

    def action_request_zegal_approval(self):
        for order in self:
            req = self.env["zegal.approval.request"].create(
                {
                    "request_type": "purchase_po",
                    "department_code": "purchase",
                    "approval_scope": "purchase",
                    "purchase_order_id": order.id,
                    "amount_total": order.amount_total,
                    "company_id": order.company_id.id,
                    "partner_id": order.partner_id.id,
                    "source_ref": order.name,
                    "checklist_scope": order.checklist_scope,
                    "checklist_budget": order.checklist_budget,
                    "checklist_timeline": order.checklist_timeline,
                    "checklist_attachment": order.checklist_attachment,
                    "checklist_terms": order.checklist_terms,
                }
            )
            order.zegal_approval_request_id = req.id
            req.action_submit()

    def action_create_project_document(self):
        self.ensure_one()
        doc = self.env["zegal.project.document"].search([("purchase_order_id", "=", self.id)], limit=1)
        if not doc:
            doc = self.env["zegal.project.document"]._create_from_source(self, document_type="handover")
        return {
            "type": "ir.actions.act_window",
            "name": "Project Document",
            "res_model": "zegal.project.document",
            "view_mode": "form",
            "res_id": doc.id,
            "target": "current",
        }
