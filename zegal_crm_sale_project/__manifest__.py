# -*- coding: utf-8 -*-
{
    "name": "Zegal CRM to Project Flow",
    "summary": "Project intake, quotation handover and project dossier",
    "version": "19.0.1.0.0",
    "category": "Sales/Project",
    "author": "Trang Huy ERP",
    "license": "LGPL-3",
    "depends": ["crm", "sale_management", "project", "documents"],
    "data": [
        "security/ir.model.access.csv",
        "views/crm_lead_views.xml",
        "views/sale_order_views.xml",
        "views/project_project_views.xml",
    ],
    "installable": True,
    "application": False,
}
