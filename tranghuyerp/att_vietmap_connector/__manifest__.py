# -*- coding: utf-8 -*-
{
    "name": "ATT VietMap Connector",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "summary": "Kết nối VietMap: tìm địa chỉ chuẩn + toạ độ cho báo giá/lệnh vận chuyển",
    "description": """
ATT VietMap Connector
======================
Module kỹ thuật kết nối Odoo với VietMap Maps API.
    """,
    "author": "Hoa.Luu ATT SYSTEM VIET NAM",
    "license": "LGPL-3",
    # sale_management/purchase: chỉ để đảm bảo model sale.order/purchase.order
    # tồn tại cho RPC từ route_finder.js (createQuotationFromSearch). Method
    # thật (action_new_quotation_for_route/action_new_rfq_for_route) nằm ở
    # att_transport_orders — KHÔNG thêm module đó vào depends ở đây để tránh
    # vòng lặp (att_transport_orders đã depends att_vietmap_connector).
    "depends": ["base", "mail", "sale_management", "purchase"],
    "data": [
        "security/ir.model.access.csv",
        "views/vietmap_config_views.xml",
        "views/vietmap_request_log_views.xml",
        "wizard/att_vietmap_test_wizard_views.xml",
        "views/vietmap_menu.xml",
        "views/route_finder_views.xml",
        "data/ir_cron.xml",

    ],
    "assets": {
        "web.assets_backend": [
            "att_vietmap_connector/static/lib/vietmap-gl/vietmap-gl.css",
            "att_vietmap_connector/static/lib/vietmap-gl/vietmap-gl.js",
            "att_vietmap_connector/static/src/js/vietmap_widget.js",
            "att_vietmap_connector/static/src/xml/vietmap_widget.xml",
            "att_vietmap_connector/static/src/js/address_autocomplete.js",
            "att_vietmap_connector/static/src/xml/address_autocomplete.xml",
            "att_vietmap_connector/static/src/js/route_finder.js",
            "att_vietmap_connector/static/src/xml/route_finder.xml",
            "att_vietmap_connector/static/src/scss/route_finder.scss",
        ],
    },
    "installable": True,
    "application": False,
}