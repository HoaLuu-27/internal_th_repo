# -*- coding: utf-8 -*-
{
    "name": "Zegal Project BoQ & Budget",
    "summary": "Project work breakdown, estimate and budget control",
    "version": "19.0.1.0.0",
    "category": "Project",
    "author": "Trang Huy ERP",
    "license": "LGPL-3",
    "depends": ["project", "product", "uom", "zegal_crm_sale_project"],
    "data": [
        "security/ir.model.access.csv",
        "views/project_project_views.xml",
        "views/boq_views.xml",
    ],
    "installable": True,
    "application": False,
}
