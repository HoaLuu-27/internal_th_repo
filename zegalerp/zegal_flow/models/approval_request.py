from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ZegalApprovalRequest(models.Model):
    _name = "zegal.approval.request"
    _description = "Zegal Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default=lambda self: _("New"), required=True, tracking=True)
    request_type = fields.Selection(
        [
            ("sale_quote", "Sales Quote"),
            ("purchase_po", "Purchase Order"),
            ("stock_out", "Stock Out"),
            ("project_cost", "Project Cost"),
            ("document", "Document"),
            ("expense", "Expense"),
            ("handover", "Handover"),
        ],
        required=True,
        default="sale_quote",
        tracking=True,
    )
    department_code = fields.Selection(
        [
            ("sales", "Sales"),
            ("purchase", "Purchase"),
            ("warehouse", "Warehouse"),
            ("accounting", "Accounting"),
            ("project", "Project"),
            ("document", "Document"),
        ],
        tracking=True,
    )
    approval_scope = fields.Selection(
        [("internal", "Internal Approval"), ("quote", "Quote Approval"), ("purchase", "Purchase Approval"), ("expense", "Expense Approval"), ("handover", "Handover Approval")],
        default="internal",
        tracking=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("to_approve", "Waiting Approval"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="draft",
        tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, tracking=True)
    approver_id = fields.Many2one("res.users", tracking=True)
    matrix_id = fields.Many2one("zegal.approval.matrix")
    sale_order_id = fields.Many2one("sale.order")
    purchase_order_id = fields.Many2one("purchase.order")
    project_id = fields.Many2one("project.project")
    document_id = fields.Many2one("documents.document")
    amount_total = fields.Monetary(currency_field="currency_id", tracking=True)
    margin_percent = fields.Float(tracking=True)
    partner_id = fields.Many2one("res.partner")
    source_ref = fields.Char(tracking=True)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    note = fields.Html()
    approval_message = fields.Text()
    log_ids = fields.One2many("zegal.approval.log", "request_id", string="Audit Trail")
    next_approver_id = fields.Many2one("res.users", compute="_compute_next_approver_id")
    step_ids = fields.One2many("zegal.approval.step", "request_id", string="Approval Steps")
    current_step_id = fields.Many2one("zegal.approval.step", compute="_compute_current_step_id")
    checklist_scope = fields.Boolean(string="Scope Confirmed")
    checklist_margin = fields.Boolean(string="Margin Checked")
    checklist_budget = fields.Boolean(string="Budget Checked")
    checklist_timeline = fields.Boolean(string="Timeline Checked")
    checklist_attachment = fields.Boolean(string="Attachments Ready")
    checklist_terms = fields.Boolean(string="Terms Confirmed")
    checklist_handover = fields.Boolean(string="Handover Ready")
    checklist_required_ok = fields.Boolean(compute="_compute_checklist_required_ok")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name") in (False, _("New")):
                vals["name"] = self.env["ir.sequence"].next_by_code("zegal.approval.request") or _("New")
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                continue
            rec._check_required_checklist()
            rec._build_steps()
            rec.approver_id = rec.current_step_id.approver_id if rec.current_step_id else rec._get_approver()
            rec.state = "to_approve"
            rec._log_action("submit", _("Submitted for approval"))
            if rec.approver_id:
                rec.activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=rec.approver_id.id,
                    summary=_("Approval needed"),
                )

    def action_approve(self):
        for rec in self:
            step = rec.current_step_id
            if step and step.state == "pending":
                step.state = "approved"
                step.note = _("Approved by %s") % self.env.user.display_name
                next_step = rec._get_next_pending_step()
                if next_step:
                    rec.approver_id = next_step.approver_id
                    rec.state = "to_approve"
                    rec._log_action("approve", _("Approved step %s") % step.name)
                    rec.activity_schedule(
                        "mail.mail_activity_data_todo",
                        user_id=next_step.approver_id.id,
                        summary=_("Approval needed"),
                    )
                else:
                    rec.state = "approved"
                    rec.approval_message = _("Approved by %s") % self.env.user.display_name
                    rec._sync_documents("approved")
                    rec._log_action("approve", _("Approved final"))
            else:
                rec.state = "approved"
                rec.approval_message = _("Approved by %s") % self.env.user.display_name
                rec._sync_documents("approved")
                rec._log_action("approve", _("Approved"))

    def action_reject(self):
        for rec in self:
            step = rec.current_step_id
            if step and step.state == "pending":
                step.state = "rejected"
                step.note = _("Rejected by %s") % self.env.user.display_name
            rec.state = "rejected"
            rec.approval_message = _("Rejected by %s") % self.env.user.display_name
            rec._sync_documents("rejected")
            rec._log_action("reject", _("Rejected"))

    def action_reset(self):
        for rec in self:
            old_state = rec.state
            rec.write({"state": "draft", "approval_message": False})
            rec._log_action("reset", _("Reset to draft"), old_state=old_state, new_state="draft")

    def _get_approver(self):
        self.ensure_one()
        domain = [
            ("active", "=", True),
            ("company_id", "in", [False, self.company_id.id]),
            ("request_type", "=", self.request_type),
            "|",
            ("approval_scope", "=", False),
            ("approval_scope", "=", self.approval_scope),
        ]
        if self.amount_total:
            domain += ["|", ("min_amount", "=", False), ("min_amount", "<=", self.amount_total)]
            domain += ["|", ("max_amount", "=", False), ("max_amount", ">=", self.amount_total)]
        if self.margin_percent:
            domain += ["|", ("min_margin", "=", False), ("min_margin", "<=", self.margin_percent)]
        rule = self.env["zegal.approval.matrix"].search(domain, order="sequence,id", limit=1)
        self.matrix_id = rule[:1]
        return rule.approver_id if rule else False

    def _compute_next_approver_id(self):
        for rec in self:
            rec.next_approver_id = rec.current_step_id.approver_id if rec.current_step_id else (rec._get_approver() if rec.state == "draft" else False)

    def _compute_current_step_id(self):
        for rec in self:
            rec.current_step_id = rec.step_ids.filtered(lambda s: s.state == "pending")[:1]

    def _build_steps(self):
        for rec in self:
            if rec.step_ids:
                continue
            rules = self.env["zegal.approval.matrix"].search(
                [
                    ("active", "=", True),
                    ("company_id", "in", [False, rec.company_id.id]),
                    ("request_type", "=", rec.request_type),
                    "|",
                    ("approval_scope", "=", False),
                    ("approval_scope", "=", rec.approval_scope),
                ],
                order="sequence,id",
            )
            if not rules:
                approver = rec._get_approver()
                if approver:
                    self.env["zegal.approval.step"].create(
                        {"request_id": rec.id, "sequence": 10, "name": _("Approval"), "approver_id": approver.id}
                    )
            else:
                for rule in rules:
                    self.env["zegal.approval.step"].create(
                        {"request_id": rec.id, "sequence": rule.sequence, "name": rule.name, "approver_id": rule.approver_id.id}
                    )

    def _get_next_pending_step(self):
        self.ensure_one()
        return self.step_ids.filtered(lambda s: s.state == "pending").sorted("sequence")[1:2]

    def _compute_checklist_required_ok(self):
        for rec in self:
            required = [
                rec.checklist_scope,
                rec.checklist_attachment,
            ]
            if rec.approval_scope in ("quote", "purchase", "expense", "handover"):
                required.append(rec.checklist_terms)
            if rec.approval_scope in ("quote", "purchase"):
                required.append(rec.checklist_budget)
            if rec.approval_scope == "quote":
                required.append(rec.checklist_margin)
            if rec.approval_scope == "handover":
                required.append(rec.checklist_handover)
            rec.checklist_required_ok = all(bool(x) for x in required)

    def _check_required_checklist(self):
        for rec in self:
            if not rec.checklist_required_ok:
                raise UserError(_("Checklist is not complete for this approval flow."))

    def _log_action(self, action, note, old_state=False, new_state=False):
        for rec in self:
            self.env["zegal.approval.log"].create(
                {
                    "request_id": rec.id,
                    "action": action,
                    "state_from": old_state or rec.state,
                    "state_to": new_state or rec.state,
                    "note": note,
                }
            )

    def _sync_documents(self, state):
        self.ensure_one()
        if self.sale_order_id:
            self.sale_order_id.zegal_approval_state = state
        if self.purchase_order_id:
            self.purchase_order_id.zegal_approval_state = state
        if self.project_id:
            self.project_id.zegal_approval_state = state
        if self.document_id:
            self.document_id.zegal_approval_state = state

    @api.constrains("sale_order_id", "purchase_order_id", "project_id", "document_id")
    def _check_link(self):
        for rec in self:
            if not any([rec.sale_order_id, rec.purchase_order_id, rec.project_id, rec.document_id]):
                raise UserError(_("Approval request must be linked to at least one document."))
