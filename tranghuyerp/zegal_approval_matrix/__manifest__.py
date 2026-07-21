# -*- coding: utf-8 -*-
{
    "name": "Zegal Approval Matrix",
    "summary": "Shared amount-based approval controls for sales and purchasing",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "author": "Trang Huy ERP",
    "license": "LGPL-3",
    "depends": ["sale_management", "purchase", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/zegal_approval_views.xml",
        "views/sale_order_views.xml",
        "views/purchase_order_views.xml",
    ],
    "installable": True,
    "application": False,
}
