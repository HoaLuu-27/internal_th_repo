# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class ZegalApprovalRule(models.Model):
    _name = "zegal.approval.rule"
    _description = "Zegal Approval Rule"
    _order = "document_type, minimum_amount, id"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    document_type = fields.Selection([("sale", "Sales Order"), ("purchase", "Purchase Order")], required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    minimum_amount = fields.Monetary(required=True, default=0.0)
    maximum_amount = fields.Monetary(help="Leave zero to apply without an upper limit.")
    approver_group_id = fields.Many2one("res.groups", required=True, string="Approver Group")

    def matches_amount(self, amount):
        self.ensure_one()
        return amount >= self.minimum_amount and (not self.maximum_amount or amount <= self.maximum_amount)


class ZegalApprovalRequest(models.Model):
    _name = "zegal.approval.request"
    _description = "Zegal Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, readonly=True, default=lambda self: _("New"), copy=False)
    state = fields.Selection(
        [("draft", "Draft"), ("pending", "Pending Approval"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="draft", tracking=True, required=True,
    )
    document_type = fields.Selection([("sale", "Sales Order"), ("purchase", "Purchase Order")], required=True, readonly=True)
    sale_order_id = fields.Many2one("sale.order", ondelete="cascade", copy=False)
    purchase_order_id = fields.Many2one("purchase.order", ondelete="cascade", copy=False)
    amount = fields.Monetary(required=True, readonly=True)
    currency_id = fields.Many2one("res.currency", required=True, readonly=True)
    rule_id = fields.Many2one("zegal.approval.rule", required=True, readonly=True)
    approver_group_id = fields.Many2one(related="rule_id.approver_group_id", readonly=True)
    requester_id = fields.Many2one("res.users", required=True, readonly=True, default=lambda self: self.env.user)
    approver_id = fields.Many2one("res.users", readonly=True, copy=False)
    reason = fields.Text()
    decision_note = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("zegal.approval.request") or _("New")
        return super().create(vals_list)

    def action_submit(self):
        for request in self:
            if request.state != "draft":
                continue
            request.state = "pending"
            request.message_post(body=_("Approval request submitted to group: %s") % request.approver_group_id.display_name)

    def _check_approver(self):
        self.ensure_one()
        if self.env.user not in self.approver_group_id.users:
            raise AccessError(_("Only members of %s can decide this request.") % self.approver_group_id.display_name)

    def action_approve(self):
        for request in self:
            request._check_approver()
            if request.state == "pending":
                request.write({"state": "approved", "approver_id": self.env.user.id})

    def action_reject(self):
        for request in self:
            request._check_approver()
            if request.state == "pending":
                request.write({"state": "rejected", "approver_id": self.env.user.id})
