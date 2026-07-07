# -*- coding: utf-8 -*-

import logging
import base64
import requests
from odoo import fields, models, api

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    """
    Mở rộng Contact để lưu định danh khách hàng Zalo.

    Mục đích:
    - Webhook nhận user_id từ Zalo.
    - Odoo dùng user_id này để tìm/tạo Contact.
    - Khi nhân viên trả lời trong Discuss, hệ thống biết gửi lại cho user Zalo nào.
    """

    _inherit = "res.partner"

    zalo_user_id = fields.Char(
        string="Zalo User ID",
        index=True,
        copy=False,
        help="ID người dùng Zalo theo Official Account. Đây là định danh dùng để gửi/nhận tin nhắn OA.",
    )

    zalo_display_name = fields.Char(
        string="Zalo Display Name",
        copy=False,
        help="Tên hiển thị lấy từ Zalo nếu API/webhook trả về.",
    )

    zalo_avatar_url = fields.Char(
        string="Zalo Avatar URL",
        copy=False,
        help="Link avatar của người dùng Zalo nếu có.",
    )

    zalo_followed = fields.Boolean(
        string="Đang follow OA",
        default=False,
        copy=False,
        help="Đánh dấu khách hàng hiện đang follow Official Account hay không.",
    )

    zalo_last_interaction = fields.Datetime(
        string="Zalo Last Interaction",
        copy=False,
        help="Thời điểm gần nhất khách hàng tương tác qua Zalo OA.",
    )

    @api.model
    def zalo_get_or_create_from_user_id(self, config, zalo_user_id):
        """
         Tìm hoặc tạo Contact từ Zalo User ID.

         Flow:
         1. Search partner theo zalo_user_id.
         2. Gọi Zalo API get_user_detail để lấy tên/avatar.
         3. Update partner nếu đã có.
         4. Create partner nếu chưa có.
         """
        Partner = self.sudo()
        detail = {}
        try:
            response = self.env["att.zalo.oa.api"].sudo().get_user_detail(
                config=config,
                zalo_user_id=zalo_user_id,
            )
            detail = response.get("data") or {}
        except Exception as e:
            _logger.warning(
                "[ZALO OA] Cannot get user detail for %s: %s",
                zalo_user_id,
                e,
            )
        partner = Partner.search([("zalo_user_id", "=", zalo_user_id)], limit=1)
        vals = self._zalo_prepare_partner_vals(
            zalo_user_id=zalo_user_id,
            detail=detail,
        )
        if partner:
            partner.write(vals)
            return partner
        return Partner.create(vals)

    @api.model
    def _zalo_prepare_partner_vals(self, zalo_user_id, detail=None):
        """
        Chuẩn hóa dữ liệu từ Zalo user detail sang res.partner vals.
        """
        detail = detail or {}
        avatars = detail.get("avatars") or {}

        avatar_url = (
                detail.get("avatar")
                or avatars.get("240")
                or avatars.get("120")
                or ""
        )

        display_name = (
                detail.get("display_name")
                or detail.get("user_alias")
                or "Zalo User %s" % zalo_user_id
        )

        vals = {
            "name": display_name,
            "zalo_user_id": zalo_user_id,
            "zalo_display_name": detail.get("display_name") or "",
            "zalo_avatar_url": avatar_url,
            "zalo_followed": bool(detail.get("user_is_follower")),
        }

        image_binary = self._zalo_download_avatar_as_base64(avatar_url)
        if image_binary:
            vals["image_1920"] = image_binary
            vals["image_1920"] = image_binary

        return vals

    @api.model
    def _zalo_download_avatar_as_base64(self, avatar_url):
        """
        Download avatar Zalo và convert sang base64 để ghi vào image_1920.

        Odoo Contact không hiển thị avatar từ URL trực tiếp.
        """
        if not avatar_url:
            return False

        try:
            response = requests.get(avatar_url, timeout=10)
            if response.status_code != 200:
                _logger.warning(
                    "[ZALO OA] Cannot download avatar. url=%s status=%s",
                    avatar_url,
                    response.status_code,
                )
                return False

            content_type = response.headers.get("Content-Type", "")
            if content_type and "image" not in content_type:
                _logger.warning(
                    "[ZALO OA] Avatar URL is not image. url=%s content_type=%s",
                    avatar_url,
                    content_type,
                )
                return False

            return base64.b64encode(response.content)

        except Exception as e:
            _logger.warning(
                "[ZALO OA] Cannot download avatar from %s: %s",
                avatar_url,
                e,
            )
            return False
