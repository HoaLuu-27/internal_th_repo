{
    'name': 'MeInvoice',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Invoicing',
    'summary': 'Tích hợp hóa đơn điện tử MISA MeInvoice (Đầu ra)',
    'author': 'ATT VIET NAM Systems Group',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/meinvoice_config_views.xml',
        'views/meinvoice_log_views.xml',
        'views/account_move_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}