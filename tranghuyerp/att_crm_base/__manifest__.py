# -*- coding: utf-8 -*-
{
    "name": "ATT CRM Base",
    "summary": "Base extensions for CRM and Customer Management",
    "description": """
ATT CRM Base

This module provides common CRM extensions and shared features for
customer management, including:
- Customer information enhancements
- Contact data management
- Phone number masking
- Common security and access rules
- Shared CRM utilities
""",
    "version": "19.0.1.0.0",
    "category": "Customer Relationship Management",
    "author": "Hoa.Luu",
    "company": "ATT System Vietnam",
    # "website": "https://www.attsystem.com.vn",
    "license": "LGPL-3",
    "depends": [
        "base",
        "contacts",
        "crm",
        "web",
    ],
    "data": [
        "security/security.xml",
        "views/res_partner_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}