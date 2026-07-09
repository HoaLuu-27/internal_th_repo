{
    'name': 'ATT Fleet Extend',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Fleet',
    'summary': 'Mở rộng đội xe Trang Huy: trạng thái điều vận, giấy tờ xe, '
               'bảo dưỡng theo km, bàn giao xe/vật tư, loại xe vận chuyển.',
    'author': 'Hoa.Luu ATT system Viet Nam',
    'depends': [
        'fleet',
        'hr',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/cron.xml',
        'data/vehicle_type_data.xml',
        'views/att_vehicle_type_views.xml',
        'views/vehicle_document_views.xml',
        'views/vehicle_handover_views.xml',
        'views/fleet_vehicle_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
