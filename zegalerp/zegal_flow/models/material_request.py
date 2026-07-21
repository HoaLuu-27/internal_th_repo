from odoo import fields, models, _


class ZegalProjectMaterialRequest(models.Model):
    _name = "zegal.project.material.request"
    _description = "Zegal Project Material Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default=lambda self: _("New"), required=True, tracking=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    project_id = fields.Many2one("project.project", required=True, tracking=True)
    request_date = fields.Date(default=fields.Date.context_today, tracking=True)
    need_date = fields.Date(tracking=True)
    state = fields.Selection(
        [("draft", "Draft"), ("to_quote", "Request For Quote"), ("to_purchase", "To Purchase"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="draft",
        tracking=True,
    )
    line_ids = fields.One2many("zegal.project.material.request.line", "request_id", string="Lines")
    purchase_request_id = fields.Many2one("zegal.purchase.request", copy=False)
    approval_request_id = fields.Many2one("zegal.approval.request", copy=False)
    note = fields.Text()

    def action_request_quote(self):
        for rec in self:
            rec.state = "to_quote"

    def action_create_purchase_request(self):
        for rec in self:
            pr = self.env["zegal.purchase.request"].create(
                {
                    "name": rec.name,
                    "project_id": rec.project_id.id,
                    "company_id": rec.company_id.id,
                    "request_type": "material",
                    "need_date": rec.need_date,
                    "note": rec.note,
                }
            )
            rec.purchase_request_id = pr.id
            rec.state = "to_purchase"
            return {
                "type": "ir.actions.act_window",
                "name": "Purchase Request",
                "res_model": "zegal.purchase.request",
                "view_mode": "form",
                "res_id": pr.id,
                "target": "current",
            }

    def action_submit_approval(self):
        for rec in self:
            req = self.env["zegal.approval.request"].create(
                {
                    "request_type": "purchase_po",
                    "approval_scope": "purchase",
                    "department_code": "purchase",
                    "project_id": rec.project_id.id,
                    "company_id": rec.company_id.id,
                    "source_ref": rec.name,
                    "note": rec.note,
                    "checklist_scope": True,
                    "checklist_budget": True,
                    "checklist_terms": True,
                    "checklist_attachment": True,
                }
            )
            rec.approval_request_id = req.id
            req.action_submit()
            return {
                "type": "ir.actions.act_window",
                "name": "Approval Request",
                "res_model": "zegal.approval.request",
                "view_mode": "form",
                "res_id": req.id,
                "target": "current",
            }


class ZegalProjectMaterialRequestLine(models.Model):
    _name = "zegal.project.material.request.line"
    _description = "Zegal Project Material Request Line"

    request_id = fields.Many2one("zegal.project.material.request", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", required=True)
    description = fields.Char()
    quantity = fields.Float(default=1.0)
    uom_id = fields.Many2one("uom.uom", required=True)
    needed_date = fields.Date()
    budget_amount = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="request_id.company_id.currency_id", readonly=True)
