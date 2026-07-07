{
    'name': 'MeInvoice',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Invoicing',
    'summary': 'Tích hợp hóa đơn điện tử MISA MeInvoice',
    'description': """
ATT Systems Viet Nam - MeInvoice Connector
========================================
- Kết nối Odoo 19 với MISA MeInvoice API
- Hỗ trợ cả V1 (Production) và V2 (Sandbox)
- Logging toàn bộ request/response
- Mapping 2 chiều: Odoo ↔ MeInvoice
    """,
    'author': 'Hoa.Luu ATT Systems Viet Nam',
    'website': 'https://www.odoo.com/vi_VN/partners/att-vietnam-23646330',
    'depends': ['account', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/meinvoice_config_views.xml',
        'views/meinvoice_request_log_views.xml',
        'views/meinvoice_invoice_views.xml',
        'views/account_move_views.xml',
        'views/meinvoice_menus.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}