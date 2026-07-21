# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    zegal_approval_request_id = fields.Many2one("zegal.approval.request", string="Approval Request", copy=False, readonly=True)

    def _zegal_approval_rule(self):
        self.ensure_one()
        rules = self.env["zegal.approval.rule"].search([
            ("active", "=", True), ("document_type", "=", "purchase"), ("company_id", "=", self.company_id.id),
        ], order="minimum_amount desc, id")
        return rules.filtered(lambda rule: rule.matches_amount(self.amount_total))[:1]

    def action_zegal_request_approval(self):
        for order in self:
            rule = order._zegal_approval_rule()
            if not rule:
                raise UserError(_("No active Purchase Order approval rule matches this order."))
            request = self.env["zegal.approval.request"].create({
                "document_type": "purchase", "purchase_order_id": order.id, "amount": order.amount_total,
                "currency_id": order.currency_id.id, "rule_id": rule.id, "reason": order.notes,
            })
            order.zegal_approval_request_id = request.id
            request.action_submit()

    def button_confirm(self):
        for order in self:
            rule = order._zegal_approval_rule()
            if rule and order.zegal_approval_request_id.state != "approved":
                raise UserError(_("This Purchase Order requires an approved internal request before confirmation."))
        return super().button_confirm()
