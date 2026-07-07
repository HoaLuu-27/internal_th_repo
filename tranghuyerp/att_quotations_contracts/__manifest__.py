{
    'name': 'ATT Quotations & Contracts',
    'version': '19.0.1.0.0',
    'category': 'Sales/Purchase',
    'summary': 'HĐ nguyên tắc + Phụ lục trên nền báo giá native: SO (bán) và RFQ  (mua)',
    'description': """
ATT Quotations & Contracts — kiến trúc native-first cho Trang Huy Logistics
Flow bán : CRM → SO báo giá → duyệt giá → HĐK → Phụ lục (kéo dòng từ SO) → SO thực thi
Flow mua : SO confirm + hết xe TH → RFQ + alternatives (>= 5 NCC) → chốt NCC
           → HĐK NCC (nếu chưa có) → Phụ lục (kéo dòng từ RFQ thắng) → PO
    """,
    'author': 'Hoa.Luu ATT system Viet Nam',
    'website': '',
    'depends': [
        'base',
        'mail',
        'sale_management',
        'purchase',
        'account',
        'fleet',
        'website',
        'portal',
    ],
    'data': [
    'security/att_security.xml',
    'security/ir.model.access.csv',

    'data/ir_sequence.xml',
    'data/contract_clauses.xml',
    'data/mail_templates.xml',

    'views/res_company_views.xml',

    # PHẢI LOAD TRƯỚC menu_views.xml
    'views/att_transport_mode_views.xml',

    'views/menu_views.xml',
    'views/att_contract_views.xml',
    'views/att_contract_clause_views.xml',
    'views/att_liquidation_views.xml',
    'views/att_contract_appendix_views.xml',
    'views/sale_order_views.xml',
    'views/purchase_order_views.xml',
    'views/website_service_templates.xml',

    'wizard/attqc_send_quotation_wizard_views.xml',

    'reports/report_visibility.xml',
    'reports/attqc_sale_quotation_report.xml',
    'reports/attqc_sale_execution_order_report.xml',
    'reports/attqc_purchase_quotation_report.xml',
    'reports/att_contract_report.xml',
    'reports/att_appendix_report.xml',
],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
