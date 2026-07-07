# -*- coding: utf-8 -*-
import json
import hmac
import hashlib
import logging
import base64
import requests

from odoo import http, SUPERUSER_ID
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class ZaloOAController(http.Controller):
    """
    Controller riêng cho Zalo Official Account.

    Chủ đích thiết kế:
    - Không gom verify/oauth/webhook vào một route.
    - Mỗi route có đúng một nhiệm vụ.
    - Log inbound request trước khi xử lý để debug được mọi lỗi.
    """

    # -------------------------------------------------------------------------
    # 1. Verify URL/domain
    # -------------------------------------------------------------------------

    @http.route(
        [
            "/zalo_services/wh/<string:filename>",
            "/att_connector/zalo/<string:filename>",
        ],
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def verify_file(self, filename, **kwargs):
        """
        Zalo gọi route này khi verify URL Prefix.

        Ví dụ:
            /zalo_services/oa/webhook/zalo_verifierXXX.html

        Nhiệm vụ:
        - Tách token từ filename.
        - Trả meta tag cho Zalo.
        - Lưu meta tag vào config.
        """
        env = request.env(user=SUPERUSER_ID)
        config = env["att.zalo.service.config"]._get_active_oa_config()

        if not config:
            return Response("No active Zalo OA config", status=404)

        if not filename.endswith(".html"):
            return Response("Not Found", status=404)

        token = filename.replace(".html", "")
        if token.startswith("zalo_verifier"):
            token = token.replace("zalo_verifier", "", 1)

        if not token:
            return Response("Invalid verifier file", status=400)

        meta_tag = (
                "<meta name='zalo-platform-site-verification' "
                "content='%s' />" % token
        )

        config.sudo().write({
            "meta_tag": meta_tag,
            "register_mode": False,
            "state": "verified",
        })

        self._create_inbound_log(
            config=config,
            name="Zalo OA - Verify URL",
            endpoint=request.httprequest.path,
            method="GET",
            headers=dict(request.httprequest.headers),
            body=kwargs,
            response_code=200,
            response_body=meta_tag,
            state="done",
        )

        return Response(meta_tag, content_type="text/html; charset=utf-8", status=200)

    # -------------------------------------------------------------------------
    # 2. OAuth callback
    # -------------------------------------------------------------------------

    @http.route(
        "/zalo_services/oa/oauth/callback",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def oauth_callback(self, **kwargs):
        """
        Callback nhận authorization_code từ Zalo.

        Flow:
        - Admin bấm Connect OA trên Odoo.
        - Odoo redirect sang Zalo OAuth.
        - Zalo redirect về đây với ?code=...&state=...
        - Controller check state.
        - Controller đổi code lấy access_token/refresh_token.
        """
        env = request.env(user=SUPERUSER_ID)
        config = env["att.zalo.service.config"]._get_active_oa_config()

        code = kwargs.get("code") or request.httprequest.args.get("code")
        state = kwargs.get("state") or request.httprequest.args.get("state")
        error = kwargs.get("error") or request.httprequest.args.get("error")

        log = self._create_inbound_log(
            config=config,
            name="Zalo OA - OAuth Callback",
            endpoint=request.httprequest.path,
            method="GET",
            headers=dict(request.httprequest.headers),
            body=dict(request.httprequest.args),
            state="new",
        )

        if not config:
            log.action_mark_error("No active Zalo OA config")
            return Response("No active Zalo OA config", status=404)

        if error:
            config._set_error(error)
            log.action_mark_error(error)
            return Response("Zalo OAuth Error: %s" % error, status=400)

        if not code:
            log.action_mark_error("Missing authorization code")
            return Response("Missing authorization code", status=400)

        if config.oauth_state and state != config.oauth_state:
            log.action_mark_error("Invalid OAuth state")
            return Response("Invalid OAuth state", status=401)

        try:
            env["att.zalo.oa.api"].exchange_code_for_token(config, code)
            log.action_mark_done(200, {"message": "Token exchanged successfully"})

            # Redirect về form config nếu muốn đẹp hơn.
            return Response(
                """
                <html>
                    <body>
                        <h2>Zalo OA connected successfully.</h2>
                        <p>Bạn có thể quay lại Odoo để tiếp tục cấu hình.</p>
                    </body>
                </html>
                """,
                status=200,
                content_type="text/html; charset=utf-8",
            )

        except Exception as e:
            log.action_mark_error(e)
            return Response("Token exchange failed: %s" % e, status=500)

    # -------------------------------------------------------------------------
    # 3. Webhook
    # -------------------------------------------------------------------------

    @http.route(
        [
            "/zalo_services/wh",
            "/zalo_services/wh/",
            "/att_connector/zalo",
            "/att_connector/zalo/",
        ],
        type="http",
        auth="none",
        methods=["GET", "POST"],
        csrf=False,
    )
    def webhook(self, **kwargs):
        """
        Webhook nhận event từ Zalo OA.

        GET:
        - Trả OK để Zalo check endpoint.

        POST:
        - Log request trước.
        - Verify signature.
        - Parse body.
        - Route theo event_name.
        - Batch này chỉ log và parse.
        - Batch sau sẽ tạo Discuss channel và post message.
        """
        env = request.env(user=SUPERUSER_ID)
        config = env["att.zalo.service.config"]._get_active_oa_config()

        if not config:
            return Response("No active Zalo OA config", status=404)

        if request.httprequest.method == "GET":
            return Response("OK", status=200, content_type="text/plain; charset=utf-8")

        raw_body = request.httprequest.get_data(as_text=True)
        headers = dict(request.httprequest.headers)

        log = self._create_inbound_log(
            config=config,
            name="Zalo OA - Webhook",
            endpoint=request.httprequest.path,
            method="POST",
            headers=headers,
            body=raw_body,
            is_webhook=True,
            state="new",
        )

        try:
            data = json.loads(raw_body or "{}")
        except Exception as e:
            log.action_mark_error("Invalid JSON: %s" % e)
            # Vẫn trả 200 để Zalo không retry quá nhiều trong lúc dev.
            return Response("OK", status=200, content_type="text/plain; charset=utf-8")

        event_name = data.get("event_name")
        zalo_user_id = self._extract_zalo_user_id(data)
        message_id = self._extract_message_id(data)

        log.write({
            "zalo_event_name": event_name,
            "zalo_user_id": zalo_user_id,
            "message_id": message_id,
        })

        # Verify signature cho event thật.
        # Lưu ý: khi Zalo bấm Check webhook, signature có thể không đúng format.
        # Nếu muốn strict production, có thể bật bắt buộc signature sau khi setup ổn định.
        if config.oa_secret_key:
            is_valid = self._verify_webhook_signature(
                raw_body=raw_body,
                headers=headers,
                oa_secret_key=config.oa_secret_key,
            )
            if not is_valid:
                log.action_mark_error("Invalid X-ZEvent-Signature")
                _logger.warning("[ZALO OA] Invalid webhook signature")
                return Response("Unauthorized", status=401)

        try:
            self._process_webhook_event(config, data, log)
            log.action_mark_done(200, {"message": "Webhook processed"})
        except Exception as e:
            log.action_mark_error(e)
            _logger.exception("[ZALO OA] Webhook process failed: %s", e)
            # Vẫn trả 200 để tránh retry loop.
            return Response("OK", status=200, content_type="text/plain; charset=utf-8")

        return Response("OK", status=200, content_type="text/plain; charset=utf-8")

    # -------------------------------------------------------------------------
    # Webhook process
    # -------------------------------------------------------------------------
    def _process_webhook_event(self, config, data, log):
        """
        Xử lý event webhook từ Zalo OA.
        Controller chỉ điều phối:
        - Check event
        - Lấy user_id
        - Tạo/update partner
        - Tạo/update discuss channel
        - Gọi channel xử lý post message/media
        """
        event_name = data.get("event_name")
        if event_name.startswith("oa_send_"):
            log.write({"state": "ignored"})
            _logger.debug("[ZALO OA] Ignore OA outbound echo event=%s", event_name)
            return False
        # CHỈ xử lý event KHÁCH GỬI NỘI DUNG. Tuyệt đối không đưa
        # user_received_message / user_seen_message vào đây: đó là DELIVERY
        # RECEIPT bắn về mỗi khi OA gửi tin đi, và sender của nó là chính OA —
        # xử lý sẽ tạo/update partner từ OA ID (get_user_detail fail
        # "user_id is not valid") + 2 receipt về song song write cùng partner
        # gây serialization failure lặp vô hạn.
        message_events = {
            "user_send_text",
            "user_send_image",
            "user_send_file",
            "user_send_audio",
            "user_send_video",
            # Sau này sync tin OA gửi từ OA Manager/Open API
            # "oa_send_text",
            # "oa_send_image",
            # "oa_send_gif",
            # "oa_send_file",
            # "oa_send_sticker",
            # "oa_send_list",
        }
        if event_name not in message_events:
            log.write({"state": "ignored"})
            return False
        env = request.env(user=SUPERUSER_ID)
        zalo_user_id = self._extract_zalo_user_id(data)
        message = data.get("message") or {}
        if not zalo_user_id:
            log.action_mark_error("Missing Zalo user id")
            return False
        partner = env["res.partner"].sudo().zalo_get_or_create_from_user_id(
            config=config,
            zalo_user_id=zalo_user_id,
        )
        channel = env["discuss.channel"].sudo().zalo_get_or_create_channel(
            config=config,
            partner=partner,
            zalo_user_id=zalo_user_id,
        )
        channel.zalo_post_inbound_message(
            partner=partner,
            message=message,
        )
        _logger.debug(
            "[ZALO OA] event=%s attachments=%s", event_name,
            json.dumps(message.get("attachments", []), ensure_ascii=False),
        )
        return True


    def _get_or_create_zalo_channel(self, env, config, partner, zalo_user_id):
        Channel = env["discuss.channel"].sudo()

        channel = Channel.search([
            ("zalo_user_id", "=", zalo_user_id)
        ], limit=1)

        if not channel:
            channel = Channel.create({
                "name": "Zalo - %s" % partner.name,
                "channel_type": "zalo",
                "zalo_user_id": zalo_user_id,
                "zalo_partner_id": partner.id,
                "zalo_config_id": config.id,
            })
        group = env.ref("att_zalo_connector.group_zalo_oa_agent", raise_if_not_found=False)
        if group:
            users = env["res.users"].sudo().search([
                ("group_ids", "in", [group.id]),
                ("active", "=", True),
                ("share", "=", False),
            ])
            # _logger.error("users_groups: {users}")
        else:
            users = env["res.users"].browse()

        partners = users.mapped("partner_id")
        channel.channel_member_ids = [
            (0, 0, {"partner_id": p.id}) for p in partners
            if p.id not in channel.channel_member_ids.mapped("partner_id").ids
        ]

        return channel


    def _verify_webhook_signature(self, raw_body, headers, oa_secret_key):
        """
        Verify X-ZEvent-Signature.

        Theo Zalo:
            mac = sha256(app_id + data + timestamp + oa_secret_key)
        """
        received_signature = (
                headers.get("X-ZEvent-Signature")
                or headers.get("x-zevent-signature")
                or headers.get("X-Zevent-Signature")
        )

        if not received_signature:
            _logger.warning("[ZALO OA] Missing X-ZEvent-Signature")
            return False

        try:
            payload = json.loads(raw_body or "{}")
        except Exception as e:
            _logger.warning("[ZALO OA] Invalid JSON before signature verify: %s", e)
            return False

        app_id = str(payload.get("app_id") or "")
        timestamp = str(payload.get("timestamp") or "")

        if not app_id or not timestamp:
            _logger.warning(
                "[ZALO OA] Missing app_id/timestamp. app_id=%s timestamp=%s",
                app_id,
                timestamp,
            )
            return False

        raw = f"{app_id}{raw_body}{timestamp}{oa_secret_key}"
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        expected_signature = f"mac={digest}"

        # _logger.warning("[ZALO OA SIGNATURE DEBUG] received=%s", received_signature)
        # _logger.warning("[ZALO OA SIGNATURE DEBUG] expected=%s", expected_signature)
        # _logger.warning("[ZALO OA SIGNATURE DEBUG] app_id=%s", app_id)
        # _logger.warning("[ZALO OA SIGNATURE DEBUG] timestamp=%s", timestamp)
        # _logger.warning("[ZALO OA SIGNATURE DEBUG] raw_body=%s", raw_body)
        # _logger.warning("[ZALO OA SIGNATURE DEBUG] raw_string=%s", raw)

        return hmac.compare_digest(received_signature, expected_signature)

    # -------------------------------------------------------------------------
    # Extract helpers
    # -------------------------------------------------------------------------

    def _extract_zalo_user_id(self, data):

        event_name = data.get("event_name") or ""
        sender = data.get("sender") or {}
        recipient = data.get("recipient") or {}

        if event_name.startswith("user_"):
            return sender.get("id") or sender.get("user_id") or False

        if event_name.startswith("oa_send_"):
            return recipient.get("id") or recipient.get("user_id") or False

        return (
                data.get("user_id")
                or sender.get("id")
                or sender.get("user_id")
                or recipient.get("id")
                or recipient.get("user_id")
                or False
        )

    def _extract_message_id(self, data):
        """
        Lấy message id từ payload webhook.
        """
        message = data.get("message") or {}
        return message.get("msg_id") or message.get("message_id") or data.get("message_id") or False

    # -------------------------------------------------------------------------
    # Log helper
    # -------------------------------------------------------------------------

    def _create_inbound_log(
            self,
            config,
            name,
            endpoint,
            method,
            headers=None,
            body=None,
            is_webhook=False,
            response_code=False,
            response_body=False,
            state="new",
    ):
        """
        Tạo log inbound.

        Controller luôn gọi hàm này càng sớm càng tốt để không mất dữ liệu debug.
        """
        env = request.env(user=SUPERUSER_ID)

        def _dump(value):
            if isinstance(value, str):
                return value
            try:
                return json.dumps(value or {}, ensure_ascii=False, indent=2)
            except Exception:
                return str(value)

        return env["att.zalo.request.log"].sudo().create({
            "name": name,
            "config_id": config.id if config else False,
            "service_type": "oa",
            "direction": "inbound",
            "is_webhook": is_webhook,
            "endpoint": endpoint,
            "http_method": method,
            "request_headers": _dump(headers),
            "request_body": _dump(body),
            "response_code": response_code or 0,
            "response_body": _dump(response_body) if response_body else False,
            "state": state,
        })