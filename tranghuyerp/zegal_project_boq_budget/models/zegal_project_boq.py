# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ZegalProjectBoqLine(models.Model):
    _name = "zegal.project.boq.line"
    _description = "Zegal Project BoQ and Budget Line"
    _order = "project_id, sequence, id"

    project_id = fields.Many2one("project.project", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    parent_id = fields.Many2one("zegal.project.boq.line", string="Parent Work Item", ondelete="cascade", index=True)
    child_ids = fields.One2many("zegal.project.boq.line", "parent_id", string="Child Work Items")
    active = fields.Boolean(default=True)
    code = fields.Char(string="WBS Code")
    name = fields.Char(string="Work Item", required=True)
    line_type = fields.Selection(
        [("section", "Section"), ("material", "Material"), ("labor", "Labor"), ("equipment", "Equipment"), ("subcontract", "Subcontract"), ("misc", "Miscellaneous")],
        string="Cost Category",
        default="material",
        required=True,
    )
    product_id = fields.Many2one("product.product", string="Product / Service")
    product_uom_id = fields.Many2one("uom.uom", string="Unit")
    quantity = fields.Float(default=1.0)
    budget_unit_price = fields.Monetary(string="Budget Unit Cost")
    budget_amount = fields.Monetary(string="Budget Cost", compute="_compute_amounts", store=True)
    sale_unit_price = fields.Monetary(string="Sale Unit Price")
    sale_amount = fields.Monetary(string="Sale Amount", compute="_compute_amounts", store=True)
    margin_amount = fields.Monetary(string="Expected Margin", compute="_compute_amounts", store=True)
    margin_rate = fields.Float(string="Margin %", compute="_compute_amounts", store=True)
    note = fields.Text()
    currency_id = fields.Many2one(related="project_id.currency_id", readonly=True)

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.name or self.product_id.display_name
            self.product_uom_id = self.product_id.uom_id
            self.budget_unit_price = self.budget_unit_price or self.product_id.standard_price
            self.sale_unit_price = self.sale_unit_price or self.product_id.lst_price

    @api.depends("quantity", "budget_unit_price", "sale_unit_price")
    def _compute_amounts(self):
        for line in self:
            line.budget_amount = line.quantity * line.budget_unit_price
            line.sale_amount = line.quantity * line.sale_unit_price
            line.margin_amount = line.sale_amount - line.budget_amount
            line.margin_rate = line.margin_amount / line.sale_amount * 100 if line.sale_amount else 0
