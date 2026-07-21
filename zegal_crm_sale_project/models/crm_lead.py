# -*- coding: utf-8 -*-
from odoo import fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    zegal_lead_type = fields.Selection(
        [
            ("commercial", "Commercial"),
            ("project", "Project"),
            ("warranty", "Warranty"),
            ("variation", "Variation / Change request"),
        ],
        string="Lead Type",
        default="commercial",
        tracking=True,
    )
    zegal_requirement_type = fields.Selection(
        [
            ("new_build", "New build"),
            ("small_item", "Small item"),
            ("completion", "Completion stage (50/60/80%)"),
            ("sqm", "Priced by m²"),
            ("hour", "Priced by hour"),
            ("block", "Priced by block"),
            ("package", "Package"),
        ],
        string="Requirement Type",
        tracking=True,
    )
    zegal_scope_summary = fields.Html(string="Initial Scope")
    zegal_site_address = fields.Char(string="Site / Project Address")
    zegal_required_completion_date = fields.Date(string="Customer Required Completion")
