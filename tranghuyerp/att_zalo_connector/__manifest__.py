# -*- coding: utf-8 -*-
{
    "name": "ZaLo Services",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "summary": "Zalo OA, ZNS, Mini App services integration for Odoo",
    "description": """
ZaLo Services
=============
Module kỹ thuật dùng để kết nối Odoo với hệ sinh thái Zalo.

Giai đoạn hiện tại:
- Zalo Official Account Message
- OAuth lấy Access Token / Refresh Token
- Webhook nhận tin nhắn
- Log toàn bộ request inbound/outbound
- Chuẩn bị tích hợp Odoo Discuss

Giai đoạn sau:
- ZNS
- Mini App
- Các service Zalo khác
    """,
    "author": "Hoa.Luu ATT SYSTEM VIET NAM",
    "website": "https://www.odoo.com/vi_VN/partners/att-vietnam-23646330",
    "license": "LGPL-3",
    "depends": [
        "base",
        "contacts",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/groups_views.xml",
        "views/zalo_service_menu.xml",
        "views/zalo_service_config_views.xml",
        "views/zalo_request_log_views.xml",
        "views/discuss_channel_views.xml",
        "views/res_partner_views.xml",
    ],
    "assets": {
    "web.assets_backend": [
        "att_zalo_connector/static/src/core/common/thread_model_patch.js",
        "att_zalo_connector/static/src/core/common/thread_icon_patch.xml",
        "att_zalo_connector/static/src/core/common/im_status_patch.xml",
        "att_zalo_connector/static/src/core/common/message_patch.xml",
        "att_zalo_connector/static/src/core/public_web/discuss_app_model_patch.js",
        "att_zalo_connector/static/src/core/public_web/thread_model_patch.js",
        "att_zalo_connector/static/src/core/public_web/discuss_content_patch.js",
        "att_zalo_connector/static/src/discuss/core/common/thread_model_patch.js",
        "att_zalo_connector/static/src/discuss/core/web/channel_member_list_patch.js",
        "att_zalo_connector/static/src/scss/zalo.scss",
        'att_zalo_connector/static/src/scss/discuss.scss',
    ],
},
    "installable": True,
    "application": True,
}