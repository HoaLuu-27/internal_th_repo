{
    'name': 'ATT Quotation & Contract Management',
    'version': '19.0.1.0.0',
    'category': 'Sales/Purchase',
    'summary': 'Manage quotation requests, contracts, appendices, and SO/PO linkage',
    'description': """
ATT Quotation & Contract Management
===================================

This module manages the quotation and contract workflow for both Sales and Purchase:

Sales Flow:
Quotation Request -> Sales Contract -> Contract Appendix -> Sale Order

Purchase Flow:
Vendor Quotation -> Purchase Contract -> Contract Appendix -> Purchase Order
    """,
    'author': 'Hoa.Luu ATT system Viet Nam',
    'website': '',
    'depends': [
        'base',
        'mail',
        'sale_management',
        'purchase',
        'account',
        'fleet'
    ],
    'data': [
        'views/res_company_views.xml',
        'security/att_security.xml',
        'security/ir.model.access.csv',

        'data/ir_sequence.xml',
        'data/contract_clauses.xml',
        'views/att_quotation_request_views.xml',
        'views/att_contract_views.xml',
        'views/att_contract_clause_views.xml',
        'views/att_liquidation_views.xml',
        'views/att_contract_appendix_views.xml',
        'views/sale_order_views.xml',
        'views/purchase_order_views.xml',
        'views/sale_purchase_menu_views.xml',
        'views/att_transport_mode_views.xml',
        'wizard/att_quotation_print_wizard_views.xml',
        'reports/quotation_request_report.xml',
        'reports/report_quotation_request.xml',
        'reports/att_contract_report.xml',
        'reports/att_appendix_report.xml',
        'data/mail_templates.xml',

        # 'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}