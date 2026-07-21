# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    zegal_sale_type = fields.Selection(
        [
            ("commercial", "Commercial"),
            ("project", "Project"),
            ("warranty", "Warranty"),
            ("internal", "Internal"),
        ],
        string="Sale Type",
        default="commercial",
        required=True,
        tracking=True,
    )
    zegal_quotation_type = fields.Selection(
        [
            ("sqm", "By m²"),
            ("hour", "By hour"),
            ("block", "By block"),
            ("package", "Package"),
            ("product", "Product"),
            ("milestone", "Milestone"),
        ],
        string="Quotation Type",
        tracking=True,
    )
    zegal_revision = fields.Integer(string="Revision", default=1, readonly=True, copy=False)
    zegal_scope_summary = fields.Html(string="Approved Scope")
    zegal_customer_timeline = fields.Text(string="Committed Customer Timeline")
    zegal_payment_terms_summary = fields.Text(string="Payment Terms / Milestones")
    zegal_handover_line_ids = fields.One2many(
        "zegal.project.handover.line", "sale_order_id", string="Handover Checklist", copy=True
    )
    zegal_project_id = fields.Many2one("project.project", string="Project", copy=False, readonly=True)

    def action_new_revision(self):
        for order in self:
            if order.state not in ("draft", "sent"):
                raise UserError(_("A revision can only be made from a quotation."))
            order.zegal_revision += 1
            order.message_post(body=_("Quotation revision changed to R%s.") % order.zegal_revision)

    def _zegal_validate_handover(self):
        missing = self.zegal_handover_line_ids.filtered(lambda line: line.required and not line.completed)
        if missing:
            raise UserError(_("Complete required handover items before creating the project:\n%s") % "\n".join(missing.mapped("name")))
        if not self.zegal_scope_summary:
            raise UserError(_("Approved Scope is required before creating a project."))

    def action_zegal_create_project(self):
        self.ensure_one()
        if self.zegal_sale_type != "project":
            raise UserError(_("Only a Project sale type can create a project."))
        if self.state not in ("sale", "done"):
            raise UserError(_("Confirm the sales order before creating the project."))
        if self.zegal_project_id:
            return self.action_zegal_open_project()
        self._zegal_validate_handover()
        project = self.env["project.project"].create({
            "name": "%s - %s" % (self.name, self.partner_id.name),
            "partner_id": self.partner_id.id,
            "user_id": self.user_id.id,
            "zegal_sale_order_id": self.id,
            "zegal_opportunity_id": self.opportunity_id.id,
            "zegal_scope_summary": self.zegal_scope_summary,
            "zegal_customer_timeline": self.zegal_customer_timeline,
            "zegal_payment_terms_summary": self.zegal_payment_terms_summary,
        })
        self.zegal_project_id = project.id
        self.message_post(body=_("Project <a href=# data-oe-model='project.project' data-oe-id='%s'>%s</a> created from this order.") % (project.id, project.display_name))
        return self.action_zegal_open_project()

    def action_zegal_open_project(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Project"),
            "res_model": "project.project",
            "res_id": self.zegal_project_id.id,
            "view_mode": "form",
        }


class ZegalProjectHandoverLine(models.Model):
    _name = "zegal.project.handover.line"
    _description = "Zegal Project Handover Checklist"
    _order = "sequence, id"

    sale_order_id = fields.Many2one("sale.order", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    required = fields.Boolean(default=True)
    completed = fields.Boolean(tracking=True)
    note = fields.Text()
