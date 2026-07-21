# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    zegal_boq_line_ids = fields.One2many("zegal.project.boq.line", "project_id", string="BoQ / Budget")
    zegal_budget_amount = fields.Monetary(string="Budget", compute="_compute_zegal_budget_totals", store=True)
    zegal_expected_revenue = fields.Monetary(string="Expected Revenue", compute="_compute_zegal_budget_totals", store=True)
    zegal_expected_margin = fields.Monetary(string="Expected Margin", compute="_compute_zegal_budget_totals", store=True)
    zegal_expected_margin_rate = fields.Float(string="Expected Margin %", compute="_compute_zegal_budget_totals", store=True)
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)

    @api.depends("zegal_boq_line_ids.budget_amount", "zegal_boq_line_ids.sale_amount")
    def _compute_zegal_budget_totals(self):
        for project in self:
            budget = sum(project.zegal_boq_line_ids.mapped("budget_amount"))
            revenue = sum(project.zegal_boq_line_ids.mapped("sale_amount"))
            project.zegal_budget_amount = budget
            project.zegal_expected_revenue = revenue
            project.zegal_expected_margin = revenue - budget
            project.zegal_expected_margin_rate = (revenue - budget) / revenue * 100 if revenue else 0
