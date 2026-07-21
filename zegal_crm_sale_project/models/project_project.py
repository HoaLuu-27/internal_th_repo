# -*- coding: utf-8 -*-
from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    zegal_sale_order_id = fields.Many2one("sale.order", string="Source Sales Order", readonly=True, copy=False)
    zegal_opportunity_id = fields.Many2one("crm.lead", string="Source Opportunity", readonly=True, copy=False)
    zegal_scope_summary = fields.Html(string="Contracted Scope")
    zegal_customer_timeline = fields.Text(string="Committed Customer Timeline")
    zegal_payment_terms_summary = fields.Text(string="Payment Terms / Milestones")
    zegal_document_folder_id = fields.Many2one("documents.folder", string="Project Dossier Folder", copy=False)

    def action_zegal_create_dossier_folder(self):
        for project in self:
            if not project.zegal_document_folder_id:
                project.zegal_document_folder_id = self.env["documents.folder"].create({
                    "name": "[%s] %s" % (project.zegal_sale_order_id.name or "PROJECT", project.name),
                })
        return True
