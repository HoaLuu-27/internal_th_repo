from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    zegal_approval_request_id = fields.Many2one("zegal.approval.request", copy=False)
    zegal_approval_state = fields.Selection(
        [("draft", "Draft"), ("to_approve", "Waiting Approval"), ("approved", "Approved"), ("rejected", "Rejected")],
        copy=False,
        readonly=True,
    )
    project_id = fields.Many2one("project.project")
    zegal_request_type = fields.Selection(
        [("sale_quote", "Sales Quote"), ("purchase_po", "Purchase Order"), ("stock_out", "Stock Out"), ("project_cost", "Project Cost"), ("document", "Document"), ("expense", "Expense"), ("handover", "Handover")],
        default="stock_out",
    )
    zegal_department_code = fields.Selection(
        [("sales", "Sales"), ("purchase", "Purchase"), ("warehouse", "Warehouse"), ("accounting", "Accounting"), ("project", "Project"), ("document", "Document")],
        default="warehouse",
    )
    zegal_approval_scope = fields.Selection(
        [("internal", "Internal Approval"), ("quote", "Quote Approval"), ("purchase", "Purchase Approval"), ("expense", "Expense Approval"), ("handover", "Handover Approval")],
        default="internal",
    )
    zegal_checklist_required_ok = fields.Boolean(default=True)

    def action_request_zegal_approval(self):
        for rec in self:
            req = self.env["zegal.approval.request"].create(
                {
                    "request_type": rec.zegal_request_type,
                    "approval_scope": rec.zegal_approval_scope,
                    "department_code": rec.zegal_department_code,
                    "purchase_order_id": False,
                    "project_id": rec.project_id.id,
                    "company_id": rec.company_id.id,
                    "source_ref": rec.name,
                    "amount_total": sum(rec.move_ids_without_package.mapped("product_uom_qty")),
                    "note": rec.note,
                    "checklist_scope": True,
                    "checklist_budget": True,
                    "checklist_terms": True,
                    "checklist_attachment": True,
                }
            )
            rec.zegal_approval_request_id = req.id
            rec.zegal_approval_state = "to_approve"
            req.action_submit()
        return True
