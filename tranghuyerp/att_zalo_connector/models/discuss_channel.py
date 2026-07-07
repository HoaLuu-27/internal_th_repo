# -*- coding: utf-8 -*-

import base64
import logging
import re

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    channel_type = fields.Selection(
        selection_add=[("zalo", "Zalo")],
        ondelete={"zalo": "cascade"},
    )

    zalo_user_id = fields.Char("Zalo User ID", index=True, copy=False)
    zalo_partner_id = fields.Many2one("res.partner", string="Zalo Partner", index=True, copy=False)
    zalo_config_id = fields.Many2one("att.zalo.service.config", string="Zalo Config", copy=False)

    @api.model
    def zalo_get_or_create_channel(self, config, partner, zalo_user_id):
        """
        Tìm/tạo Zalo discuss channel theo Zalo User ID.
        Đồng thời đồng bộ member theo group Zalo OA Agent.
        """
        channel = self.sudo().search([
            ("zalo_user_id", "=", zalo_user_id),
            ("channel_type", "=", "zalo"),
        ], limit=1)

        vals = {
            "name": "Zalo - %s" % partner.name,
            "zalo_partner_id": partner.id,
            "zalo_config_id": config.id,
        }

        if channel:
            channel.write(vals)
        else:
            vals.update({
                "channel_type": "zalo",
                "zalo_user_id": zalo_user_id,
            })
            channel = self.sudo().create(vals)

        channel._zalo_sync_channel_members()
        return channel

    def _zalo_sync_channel_members(self):
        """
        Chỉ user thuộc group Zalo OA Agent mới được add vào channel.
        User không còn thuộc group sẽ bị remove khỏi channel.
        """
        self.ensure_one()

        group = self.env.ref(
            "att_zalo_connector.group_zalo_oa_agent",
            raise_if_not_found=False,
        )
        if group:
            users = self.env["res.users"].sudo().search([
                ("group_ids", "in", [group.id]),
                ("active", "=", True),
                ("share", "=", False),
            ])
        else:
            users = self.env["res.users"].sudo().browse()

        allowed_partner_ids = set(users.mapped("partner_id").ids)

        old_members = self.channel_member_ids.filtered(
            lambda m: m.partner_id.id not in allowed_partner_ids
        )
        if old_members:
            old_members.unlink()

        existing_partner_ids = set(self.channel_member_ids.mapped("partner_id").ids)
        commands = []
        for partner in users.mapped("partner_id"):
            if partner.id not in existing_partner_ids:
                commands.append((0, 0, {"partner_id": partner.id}))

        if commands:
            self.write({"channel_member_ids": commands})

    def zalo_post_inbound_message(self, partner, message):
        """
        Post message inbound từ Zalo vào Discuss.

        Xử lý:
        - Text
        - Image attachment từ webhook user_send_image

        Args:
            partner: res.partner khách Zalo
            message: dict payload message từ webhook Zalo
        """
        self.ensure_one()

        text = message.get("text") or message.get("content") or ""
        attachment_ids = self._zalo_create_attachments_from_message(message)

        body = text
        if not body and attachment_ids:
            body = _("Khách đã gửi hình ảnh")

        if not body and not attachment_ids:
            return False

        msg = self.with_user(self.env.ref("base.user_admin")).with_context(
            zalo_receive_text=True,
            zalo_skip_send_api=True,
            mail_create_nosubscribe=False,
            mail_notify_force_send=True,
        ).message_post(
            body=body,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            author_id=partner.id,
            attachment_ids=attachment_ids,
        )

        # Link attachment vào mail.message để preview hiển thị đúng
        if attachment_ids:
            self.env["ir.attachment"].sudo().browse(attachment_ids).write({
                "res_model": "mail.message",
                "res_id": msg.id,
            })

        return msg

    def _zalo_create_attachments_from_message(self, message):
        """
        Tạo ir.attachment từ Zalo message.attachments.

        Hiện xử lý:
        - image

        Trả về list IDs cho message_post.
        """
        self.ensure_one()

        attachment_ids = []

        for attachment in message.get("attachments") or []:
            attachment_type = attachment.get("type")
            payload = attachment.get("payload") or {}

            if attachment_type != "image":
                continue

            image_url = payload.get("url") or payload.get("thumbnail")
            if not image_url:
                continue

            att = self._zalo_download_url_to_attachment(
                url=image_url,
                filename="zalo_image_%s.jpg" % (message.get("msg_id") or "unknown"),
                mimetype="image/jpg",
            )
            if att:
                attachment_ids.append(att.id)

        return attachment_ids

    def _zalo_download_url_to_attachment(self, url, filename, mimetype):
        """
        Download URL media từ Zalo và tạo attachment tạm.

        Attachment để res_model/res_id rỗng trước để generate access_token đúng.
        Sau khi message_post tạo mail.message xong sẽ write lại:
        - res_model = mail.message
        - res_id = message.id
        """
        self.ensure_one()

        if not url:
            return False

        try:
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                _logger.warning(
                    "[ZALO OA] Cannot download media. url=%s status=%s",
                    url,
                    response.status_code,
                )
                return False

            content_type = response.headers.get("Content-Type") or mimetype

            att = self.env["ir.attachment"].sudo().create({
                "name": filename,
                "type": "binary",
                "datas": base64.b64encode(response.content),
                "mimetype": content_type,
                "res_model": False,
                "res_id": False,
                "public": False,
            })

            # Generate access_token để Discuss có URL preview tốt hơn
            if hasattr(att, "_generate_access_token"):
                att._generate_access_token()

            _logger.info(
                "[ZALO OA IMAGE] id=%s name=%s mimetype=%s size=%s access_token=%s",
                att.id,
                att.name,
                att.mimetype,
                att.file_size,
                bool(getattr(att, "access_token", False)),
            )

            return att

        except Exception as e:
            _logger.warning("[ZALO OA] Cannot download Zalo media from %s: %s", url, e)
            return False

    def message_post(self, *, message_type="notification", **kwargs):
        self.ensure_one()

        if self.channel_type != "zalo":
            return super().message_post(message_type=message_type, **kwargs)

        is_webhook = self.env.context.get("zalo_receive_text", False)
        skip_send_api = self.env.context.get("zalo_skip_send_api", False)
        has_attachment = bool(kwargs.get("attachment_ids"))
        body = kwargs.get("body") or ""

        if not is_webhook and not skip_send_api and not has_attachment:
            if not self.zalo_user_id:
                raise UserError(_("Channel Zalo chưa có Zalo User ID."))

            try:
                res = self.env["att.zalo.oa.api"].sudo().send_text(
                    config=self.zalo_config_id,
                    zalo_user_id=self.zalo_user_id,
                    text=self._zalo_html_to_text(body),
                )
                if not res:
                    _logger.error("[ZALO OA] send_text empty response")
            except Exception as e:
                raise UserError(str(e))

        if not is_webhook and not skip_send_api and has_attachment:
            if not self.zalo_user_id:
                raise UserError(_("Channel Zalo chưa có Zalo User ID."))

            try:
                attachment_ids = kwargs.get("attachment_ids", [])
                attachments = self.env["ir.attachment"].browse(attachment_ids)
                zalo_api = self.env["att.zalo.oa.api"].sudo()

                text = self._zalo_html_to_text(body) if body else ""
                # Zalo API: message IMAGE cho phép kèm text, message FILE thì
                # KHÔNG (text bị bỏ qua) → có text + có file thì bắn text
                # thành tin riêng trước, rồi gửi file sau
                has_file = any(
                    "image" not in (att.mimetype or "") for att in attachments)
                if text and has_file:
                    zalo_api.send_text(
                        config=self.zalo_config_id,
                        zalo_user_id=self.zalo_user_id,
                        text=text,
                    )
                    text = ""

                for attachment in attachments:
                    if "image" in (attachment.mimetype or ""):
                        # Upload image & send — dùng .raw (bytes gốc), KHÔNG dùng
                        # .datas (base64) — Zalo check magic bytes nên nhận base64
                        # sẽ trả -201 "file is invalid"
                        attachment_id = zalo_api.upload_image(
                            config=self.zalo_config_id,
                            file_data=attachment.raw,
                            filename=attachment.name,
                        )
                        zalo_api.send_message_with_image(
                            config=self.zalo_config_id,
                            zalo_user_id=self.zalo_user_id,
                            text=text,
                            attachment_id=attachment_id,
                        )
                        text = ""  # text chỉ đi kèm tin đầu, tránh lặp caption
                    else:
                        # Upload file & send (PDF/DOC/CSV) — .raw, không phải .datas
                        file_token = zalo_api.upload_file(
                            config=self.zalo_config_id,
                            file_data=attachment.raw,
                            filename=attachment.name,
                        )
                        zalo_api.send_message_with_file(
                            config=self.zalo_config_id,
                            zalo_user_id=self.zalo_user_id,
                            text="",  # Zalo bỏ text ở message file — đã gửi tin text riêng ở trên
                            file_token=file_token,
                        )
            except Exception as e:
                raise UserError(str(e))

        return super(DiscussChannel, self).message_post(
            message_type="zalo_chat",
            **kwargs
        )

    def _zalo_html_to_text(self, html):
        text = re.sub(r"<br\s*/?>", "\n", html or "", flags=re.I)
        text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()


class MailMessage(models.Model):
    _inherit = "mail.message"

    message_type = fields.Selection(
        selection_add=[("zalo_chat", "Zalo")],
        ondelete={"zalo_chat": "cascade"},
    )