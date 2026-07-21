from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    zegal_approval_request_id = fields.Many2one("zegal.approval.request", copy=False)
    zegal_approval_state = fields.Selection(
        [("draft", "Draft"), ("to_approve", "Waiting Approval"), ("approved", "Approved"), ("rejected", "Rejected")],
        copy=False,
        readonly=True,
    )
    zegal_quote_revision = fields.Integer(default=1, copy=False)
    zegal_quote_type = fields.Selection(
        [("meter", "m2"), ("hour", "Hour"), ("block", "Block"), ("package", "Package"), ("product", "Product")],
        default="product",
        copy=False,
    )
    zegal_margin_percent = fields.Float(copy=False)
    checklist_scope = fields.Boolean(string="Scope Confirmed")
    checklist_margin = fields.Boolean(string="Margin Checked")
    checklist_budget = fields.Boolean(string="Budget Checked")
    checklist_timeline = fields.Boolean(string="Timeline Checked")
    checklist_attachment = fields.Boolean(string="Attachments Ready")
    checklist_terms = fields.Boolean(string="Terms Confirmed")
    checklist_handover = fields.Boolean(string="Handover Ready")

    def action_request_zegal_approval(self):
        for order in self:
            req = self.env["zegal.approval.request"].create(
                {
                    "request_type": "sale_quote",
                    "department_code": "sales",
                    "approval_scope": "quote",
                    "sale_order_id": order.id,
                    "amount_total": order.amount_total,
                    "margin_percent": order.zegal_margin_percent,
                    "company_id": order.company_id.id,
                    "partner_id": order.partner_id.id,
                    "source_ref": order.name,
                    "checklist_scope": order.checklist_scope,
                    "checklist_margin": order.checklist_margin,
                    "checklist_budget": order.checklist_budget,
                    "checklist_timeline": order.checklist_timeline,
                    "checklist_attachment": order.checklist_attachment,
                    "checklist_terms": order.checklist_terms,
                    "checklist_handover": order.checklist_handover,
                }
            )
            order.zegal_approval_request_id = req.id
            req.action_submit()

    def action_create_project_document(self):
        self.ensure_one()
        doc = self.env["zegal.project.document"].search([("sale_order_id", "=", self.id)], limit=1)
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
