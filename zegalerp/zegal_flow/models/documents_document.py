from odoo import fields, models


class DocumentsDocument(models.Model):
    _inherit = "documents.document"

    project_id = fields.Many2one("project.project")
    sale_order_id = fields.Many2one("sale.order")
    purchase_order_id = fields.Many2one("purchase.order")
    approval_request_id = fields.Many2one("zegal.approval.request")
    zegal_approval_state = fields.Selection(
        [("draft", "Draft"), ("to_approve", "Waiting Approval"), ("approved", "Approved"), ("rejected", "Rejected")],
        copy=False,
    )
    is_project_document = fields.Boolean(default=False)
