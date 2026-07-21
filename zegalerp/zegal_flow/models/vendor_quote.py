from odoo import fields, models, _


class ZegalVendorQuoteComparison(models.Model):
    _name = "zegal.vendor.quote.comparison"
    _description = "Zegal Vendor Quote Comparison"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default=lambda self: _("New"), required=True, tracking=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    project_id = fields.Many2one("project.project", tracking=True)
    material_request_id = fields.Many2one("zegal.project.material.request", tracking=True)
    currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    state = fields.Selection(
        [("draft", "Draft"), ("sent", "Sent"), ("quoted", "Quoted"), ("approved", "Approved"), ("ordered", "Ordered"), ("cancel", "Cancelled")],
        default="draft",
        tracking=True,
    )
    line_ids = fields.One2many("zegal.vendor.quote.comparison.line", "comparison_id", string="Vendor Lines")
    best_vendor_id = fields.Many2one("res.partner", compute="_compute_best_vendor", store=True)
    best_amount = fields.Monetary(compute="_compute_best_vendor", store=True, currency_field="currency_id")
    best_lead_days = fields.Integer(compute="_compute_best_vendor", store=True)
    note = fields.Text()

    def action_mark_sent(self):
        self.write({"state": "sent"})

    def action_mark_quoted(self):
        self.write({"state": "quoted"})

    def action_approve(self):
        self.write({"state": "approved"})

    def action_ordered(self):
        self.write({"state": "ordered"})

    def action_cancel(self):
        self.write({"state": "cancel"})

    def _compute_best_vendor(self):
        for rec in self:
            best = False
            for line in rec.line_ids.filtered(lambda l: l.is_selected):
                best = line
                break
            if not best and rec.line_ids:
                best = sorted(rec.line_ids, key=lambda l: (l.unit_price or 0.0, l.lead_time_days or 0))[0]
            rec.best_vendor_id = best.partner_id if best else False
            rec.best_amount = best.total_amount if best else 0.0
            rec.best_lead_days = best.lead_time_days if best else 0


class ZegalVendorQuoteComparisonLine(models.Model):
    _name = "zegal.vendor.quote.comparison.line"
    _description = "Zegal Vendor Quote Comparison Line"

    comparison_id = fields.Many2one("zegal.vendor.quote.comparison", required=True, ondelete="cascade")
    partner_id = fields.Many2one("res.partner", required=True)
    product_id = fields.Many2one("product.product")
    description = fields.Char()
    unit_price = fields.Monetary(currency_field="currency_id")
    quantity = fields.Float(default=1.0)
    lead_time_days = fields.Integer()
    quality_score = fields.Float()
    note = fields.Text()
    is_selected = fields.Boolean()
    currency_id = fields.Many2one(related="comparison_id.currency_id", readonly=True)
    total_amount = fields.Monetary(compute="_compute_total_amount", store=True, currency_field="currency_id")

    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = (rec.unit_price or 0.0) * (rec.quantity or 0.0)
