from odoo import fields, models, _


class ZegalProjectDocument(models.Model):
    _name = "zegal.project.document"
    _description = "Zegal Project Document"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default=lambda self: _("New"), required=True, tracking=True)
    project_id = fields.Many2one("project.project", required=True, tracking=True)
    sale_order_id = fields.Many2one("sale.order", tracking=True)
    purchase_order_id = fields.Many2one("purchase.order", tracking=True)
    approval_request_id = fields.Many2one("zegal.approval.request", tracking=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    owner_id = fields.Many2one("res.users", default=lambda self: self.env.user, tracking=True)
    description = fields.Html()
    document_type = fields.Selection(
        [("contract", "Contract"), ("appendix", "Appendix"), ("handover", "Handover"), ("invoice", "Invoice"), ("other", "Other")],
        default="other",
        required=True,
        tracking=True,
    )
    reference = fields.Char(tracking=True)
    attachment_count = fields.Integer(compute="_compute_attachment_count")
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "zegal_project_document_attachment_rel",
        "document_id",
        "attachment_id",
        string="Attachments",
    )
    attachment_domain = fields.Char(compute="_compute_attachment_domain")
    attachment_note = fields.Text()
    state = fields.Selection(
        [("draft", "Draft"), ("linked", "Linked"), ("in_review", "In Review"), ("approved", "Approved"), ("archived", "Archived")],
        default="draft",
        tracking=True,
    )

    def action_link(self):
        self.write({"state": "linked"})

    def action_submit_review(self):
        self.write({"state": "in_review"})

    def action_approve(self):
        self.write({"state": "approved"})

    def action_archive(self):
        self.write({"state": "archived"})

    def action_reset(self):
        self.write({"state": "draft"})

    def action_open_sale(self):
        self.ensure_one()
        if not self.sale_order_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": "Sale Order",
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.sale_order_id.id,
            "target": "current",
        }

    def action_open_purchase(self):
        self.ensure_one()
        if not self.purchase_order_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": "Purchase Order",
            "res_model": "purchase.order",
            "view_mode": "form",
            "res_id": self.purchase_order_id.id,
            "target": "current",
        }

    def action_open_approval(self):
        self.ensure_one()
        if not self.approval_request_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": "Approval Request",
            "res_model": "zegal.approval.request",
            "view_mode": "form",
            "res_id": self.approval_request_id.id,
            "target": "current",
        }

    @classmethod
    def _create_from_source(cls, source, document_type="handover"):
        vals = {
            "name": source.display_name,
            "reference": source.name if hasattr(source, "name") else False,
            "company_id": source.company_id.id if getattr(source, "company_id", False) else source.env.company.id,
            "owner_id": source.env.user.id,
            "document_type": document_type,
        }
        if source._name == "sale.order":
            vals.update({"sale_order_id": source.id, "project_id": False})
        elif source._name == "purchase.order":
            vals.update({"purchase_order_id": source.id, "project_id": source.project_id.id if source.project_id else False})
        return cls.create(vals)

    def _compute_attachment_count(self):
        Attachment = self.env["ir.attachment"]
        for rec in self:
            rec.attachment_count = Attachment.search_count(
                [
                    ("res_model", "=", "zegal.project.document"),
                    ("res_id", "=", rec.id),
                ]
            )

    def _compute_attachment_domain(self):
        for rec in self:
            rec.attachment_domain = "[('res_model','=','zegal.project.document'),('res_id','=',%s)]" % rec.id
