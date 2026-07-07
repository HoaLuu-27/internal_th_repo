import json
import hmac
import hashlib
import logging
from datetime import datetime, timedelta

import requests
from odoo import api, fields, models, exceptions, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ZaloOAApi(models.AbstractModel):
    """
    Service class gọi API Zalo OA.

    Không tạo record trong database.
    Chỉ đóng vai trò helper/service:
    - exchange code lấy token
    - refresh token
    - generate appssecret_proof
    """
    _name = "att.zalo.oa.api"
    _description = "Zalo OA API Service"

    #để constant ở một chỗ cho dễ đổi khi Zalo update version.
    TOKEN_URL = "https://oauth.zaloapp.com/v4/oa/access_token"
    REFRESH_TOKEN_URL = "https://oauth.zaloapp.com/v4/oa/access_token"
    SEND_TEXT_URL = "https://openapi.zalo.me/v3.0/oa/message/cs"
    USER_DETAIL_URL = "https://openapi.zalo.me/v3.0/oa/user/detail"
    UPLOAD_IMAGE_URL = "https://openapi.zalo.me/v2.0/oa/upload/image"
    UPLOAD_FILE_URL = "https://openapi.zalo.me/v2.0/oa/upload/file"

    def exchange_code_for_token(self, config, code):
        """
        Doi authorization_code lay access_token va refresh_token.
        Input:
        - config: att.zalo.service.config
        - code: authorization_code tu Zalo callback.
        Output:
        - Ghi access_token , refresh_token vao configid.
        """
        if not config.app_id or not config.app_secret:
            raise UserError(_("Thieu App ID hoac App secret."))
        payload = {
            "app_id":config.app_id,
            "code": code,
            "grant_type": "authorization_code",
        }
        headers = {
            "Content-Type" :"application/x-www-form-urlencoded",
            "secret_key": config.app_secret,
        }
        log = self._create_outbound_log(
            config=config,
            name="[ZALO OA] Exchange Token",
            endpoint=self.TOKEN_URL,
            payload=payload,
            headers=headers,
        )
        try:
            response = requests.post(self.TOKEN_URL, data=payload, headers=headers,timeout=30)
            data = self._safe_json(response)
            log.write({
                "response_code": response.status_code,
                "response_body": json.dumps(data, ensure_ascii=False, indent=2),
            })
            if response.status_code >= 400 or data.get("error"):
                raise UserError(_("Lay token that bai: %s") % data )
            config.sudo().write({
                "authorization_code": code,
                "access_token": data.get("access_token"),
                "refresh_token": data.get("refresh_token"),
                "token_expire_at": self._compute_expire_at(data),
                "state": "connected",
                "last_error": False
            })
            log.action_mark_done(response.status_code, data)
            return data
        except Exception as e:
            log.action_mark_error(e)
            config._set_error(e)
            raise


    def refresh_access_token(self, config):
        """
        Refresh access token bang refresh_token.

        Dung cho:
        - Nut Refresh Token
        - Cron tu dong
        """
        if not config.refresh_token:
            raise UserError(_("Chua co Refresh Token"))
        payload = {
            "app_id":config.app_id,
            "grant_type": "refresh_token",
            "refresh_token": config.refresh_token,
        }
        headers = {
            "Content-Type" :"application/x-www-form-urlencoded",
            "secret_key": config.app_secret,
        }
        log = self._create_outbound_log(
            config=config,
            name="[ZALO OA] Refresh Token",
            endpoint=self.REFRESH_TOKEN_URL,
            payload=payload,
            headers=headers,
        )
        try:
            response = requests.post(
                self.REFRESH_TOKEN_URL,
                data=payload,
                headers=headers,
                timeout=30,
            )
            data = self._safe_json(response)
            log.write({
                "response_code": response.status_code,
                "response_body": json.dumps(data, ensure_ascii=False, indent=2),
            })
            if response.status_code >= 400 or data.get("error"):
                raise UserError(_("Refresh token thất bại: %s") % data)
            config.sudo().write({
                "access_token": data.get("access_token"),
                "refresh_token": data.get("refresh_token") or config.refresh_token,
                "token_expire_at": self._compute_expire_at(data),
                "state": "connected",
                "last_error": False,
            })
            log.action_mark_done(response.status_code, data)
            return data
        except Exception as e:
            log.action_mark_error(e)
            config._set_error(e)
            raise

    def _ensure_token_valid(self, config):
        """
        Check & auto-refresh token nếu hết hạn.
        Return: config (token đã valid).
        """
        if not config.access_token:
            raise UserError(_("Chưa có Access Token"))

        if config.token_expire_at and config.token_expire_at <= datetime.now():
            _logger.info("[ZALO OA] Token expired, auto-refreshing...")
            self.refresh_access_token(config)
            config = self.env['att.zalo.service.config'].browse(config.id)

        return config

    def send_text(self, config, zalo_user_id, text):
        """
        Gui text tu odoo sang Zalo.
        Day la outbound REST API don gian.
        Batch sau:
        - Ham nay se duoc goi tu Discuss khi nhan vien reply trong channel Zalo.
        """
        if not config.access_token:
            raise UserError(_("Chua co Access Token"))
        if not zalo_user_id:
            raise UserError(_("Chua co Zalo User ID"))
        payload = {
            "recipient": {
                "user_id": zalo_user_id,
            },
            "message": {
                "text": text,
            }
        }
        headers = {
            "Content-Type": "application/json",
            "access_token": config.access_token,
            "appsecret_proof": self._generate_appsecret_proof(
                access_token=config.access_token,
                app_secret=config.app_secret,
            ),
        }
        log = self._create_outbound_log(
            config=config,
            name="[ZALO OA] Send text",
            endpoint=self.SEND_TEXT_URL,
            payload=payload,
            headers=headers,
            zalo_user_id=zalo_user_id,
        )
        try:
            response = requests.post(
                self.SEND_TEXT_URL,
                json=payload,
                headers=headers,
                timeout=30,
            )
            data = self._safe_json(response)
            log.write({
                "response_code": response.status_code,
                "response_body": json.dumps(data, ensure_ascii=False, indent=2),
            })
            if response.status_code >= 400 or data.get("error"):
                raise UserError(_("Gui tin nhan Zalo that bai: %s") % data )
            log.action_mark_done(response.status_code, data)
            return data
        except Exception as e:
            log.action_mark_error(e)
            raise

    def upload_image(self, config, file_data, filename):
        """
        Upload hình ảnh lên Zalo OA.
        Args:
            config: att.zalo.service.config
            file_data: binary file data
            filename: tên file
        Return: attachment_id
        """
        config = self._ensure_token_valid(config)

        headers = {
            "access_token": config.access_token,
            "appsecret_proof": self._generate_appsecret_proof(
                access_token=config.access_token,
                app_secret=config.app_secret,
            ),
        }
        files = {
            "file": (filename, file_data, "image/jpeg"),
        }
        log = self._create_outbound_log(
            config=config,
            name="[ZALO OA] Upload Image",
            endpoint=self.UPLOAD_IMAGE_URL,
            headers=headers,
        )
        try:
            response = requests.post(
                self.UPLOAD_IMAGE_URL,
                headers=headers,
                files=files,
                timeout=30,
            )
            data = self._safe_json(response)
            log.write({
                "response_code": response.status_code,
                "response_body": json.dumps(data, ensure_ascii=False, indent=2),
            })
            if response.status_code >= 400 or data.get("error"):
                raise UserError(_("Upload hình ảnh Zalo thất bại: %s") % data)
            log.action_mark_done(response.status_code, data)
            return data.get("data", {}).get("attachment_id")
        except Exception as e:
            log.action_mark_error(e)
            raise

    def upload_file(self, config, file_data, filename):
        """
        Upload file lên Zalo OA (PDF/DOC/DOCX/CSV).
        Args:
            config: att.zalo.service.config
            file_data: binary file data
            filename: tên file
        Return: file token
        """
        config = self._ensure_token_valid(config)

        headers = {
            "access_token": config.access_token,
            "appsecret_proof": self._generate_appsecret_proof(
                access_token=config.access_token,
                app_secret=config.app_secret,
            ),
        }
        files = {
            "file": (filename, file_data),
        }
        log = self._create_outbound_log(
            config=config,
            name="[ZALO OA] Upload File",
            endpoint=self.UPLOAD_FILE_URL,
            headers=headers,
        )
        try:
            response = requests.post(
                self.UPLOAD_FILE_URL,
                headers=headers,
                files=files,
                timeout=30,
            )
            data = self._safe_json(response)
            log.write({
                "response_code": response.status_code,
                "response_body": json.dumps(data, ensure_ascii=False, indent=2),
            })
            if response.status_code >= 400 or data.get("error"):
                raise UserError(_("Upload file Zalo thất bại: %s") % data)
            log.action_mark_done(response.status_code, data)
            return data.get("data", {}).get("token")
        except Exception as e:
            log.action_mark_error(e)
            raise

    def send_message_with_image(self, config, zalo_user_id, text, attachment_id):
        """
        Gửi tin nhắn với hình ảnh đến Zalo user.
        Args:
            config: att.zalo.service.config
            zalo_user_id: ID của Zalo user
            text: nội dung text
            attachment_id: ID của hình ảnh từ upload
        """
        config = self._ensure_token_valid(config)
        if not zalo_user_id:
            raise UserError(_("Chưa có Zalo User ID"))
        if not attachment_id:
            raise UserError(_("Chưa có Attachment ID"))

        payload = {
            "recipient": {"user_id": zalo_user_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "media",
                        "elements": [{
                            "media_type": "image",
                            "attachment_id": attachment_id,
                        }],
                    },
                },
            },
        }
        if text:
            payload["message"]["text"] = text

        headers = {
            "Content-Type": "application/json",
            "access_token": config.access_token,
            "appsecret_proof": self._generate_appsecret_proof(
                access_token=config.access_token,
                app_secret=config.app_secret,
            ),
        }
        log = self._create_outbound_log(
            config=config,
            name="[ZALO OA] Send Image",
            endpoint=self.SEND_TEXT_URL,
            payload=payload,
            headers=headers,
            zalo_user_id=zalo_user_id,
        )
        try:
            response = requests.post(
                self.SEND_TEXT_URL,
                json=payload,
                headers=headers,
                timeout=30,
            )
            data = self._safe_json(response)
            log.write({
                "response_code": response.status_code,
                "response_body": json.dumps(data, ensure_ascii=False, indent=2),
            })
            if response.status_code >= 400 or data.get("error"):
                raise UserError(_("Gửi hình ảnh Zalo thất bại: %s") % data)
            log.action_mark_done(response.status_code, data)
            return data
        except Exception as e:
            log.action_mark_error(e)
            raise

    def send_message_with_file(self, config, zalo_user_id, text, file_token):
        """
        Gửi tin nhắn với file đến Zalo user.
        Args:
            config: att.zalo.service.config
            zalo_user_id: ID của Zalo user
            text: nội dung text
            file_token: token của file từ upload
        """
        config = self._ensure_token_valid(config)
        if not zalo_user_id:
            raise UserError(_("Chưa có Zalo User ID"))
        if not file_token:
            raise UserError(_("Chưa có File Token"))

        payload = {
            "recipient": {"user_id": zalo_user_id},
            "message": {
                "attachment": {
                    "type": "file",
                    "payload": {
                        "token": file_token,
                    },
                },
            },
        }
        if text:
            payload["message"]["text"] = text

        headers = {
            "Content-Type": "application/json",
            "access_token": config.access_token,
            "appsecret_proof": self._generate_appsecret_proof(
                access_token=config.access_token,
                app_secret=config.app_secret,
            ),
        }
        log = self._create_outbound_log(
            config=config,
            name="[ZALO OA] Send File",
            endpoint=self.SEND_TEXT_URL,
            payload=payload,
            headers=headers,
            zalo_user_id=zalo_user_id,
        )
        try:
            response = requests.post(
                self.SEND_TEXT_URL,
                json=payload,
                headers=headers,
                timeout=30,
            )
            data = self._safe_json(response)
            log.write({
                "response_code": response.status_code,
                "response_body": json.dumps(data, ensure_ascii=False, indent=2),
            })
            if response.status_code >= 400 or data.get("error"):
                raise UserError(_("Gửi file Zalo thất bại: %s") % data)
            log.action_mark_done(response.status_code, data)
            return data
        except Exception as e:
            log.action_mark_error(e)
            raise

    def get_user_detail(self, config, zalo_user_id):
        """
        Lay thong tin chi tiet 1 user tu Zalo OA.
        Chi goi Open API.
        Khong tao/update Partner tai day.
        Args:
             config (att.zalo.service.config):
             zalo_oa_id(str):
              User ID cua khach tren Zalo laf recipient trong payload webhook nhan ve ay.
        """
        if not config.access_token:
            raise UserError(_("Chưa có Access Token"))
        if not zalo_user_id:
            raise UserError(_("Chưa có Zalo User ID"))
        proof = self._generate_appsecret_proof(
                access_token=config.access_token,
                app_secret=config.app_secret,
        )
        params = {
            "data" : json.dumps(
                {"user_id": str(zalo_user_id)},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "appsecret_proof": proof,
        }
        headers = {
             "Content-Type": "application/json",
            "access_token": config.access_token,
            "appsecret_proof": proof,
        }
        log = self._create_outbound_log(
            config=config,
            name="[ZALO OA] Get user detail",
            endpoint=self.USER_DETAIL_URL,
            payload=params,
            headers=headers,
            zalo_user_id=zalo_user_id,
            http_method="GET",
        )
        try:
            response = requests.get(
                self.USER_DETAIL_URL,
                params=params,
                headers=headers,
                timeout=30,
            )
            data = self._safe_json(response)
            log.write({
                "response_code": response.status_code,
                "response_body": json.dumps(data, ensure_ascii=False, indent=2),
            })
            if response.status_code >= 400 or data.get("error"):
                raise UserError(_("Lấy thông tin User thất bại: %s") % data)
            log.action_mark_done(
                response.status_code,
                data,
            )
            return data
        except Exception as e:
            log.action_mark_error(e)
            raise

    def _generate_appsecret_proof(self, access_token, app_secret):
        """
        Sinh appsecret_proof cho outbound API

        """
        if not access_token or not app_secret:
            return ""
        return hmac.new(
            app_secret.encode("utf-8"),
            access_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


    def _compute_expire_at(self, data):
        seconds = (
            data.get("expires_at")
            or data.get("expires_in_second")
            or data.get("expires")
            or 8640
        )
        try:
            seconds = int(seconds)
        except Exception:
            seconds = 8640
        return datetime.now() + timedelta(seconds=seconds)


    def _safe_json(self, response):
        """
        Parse response JSON an toan.
        """
        try:
            return response.json()
        except Exception:
            return {
                "raw_response": response.text,
            }


    def _create_outbound_log(self, config, name, endpoint, payload=None, headers=None, zalo_user_id=False,http_method="POST"):
        """
        Tạo log outbound trước khi gọi API.
        Không log full token nếu không cần.
        Nhưng trong môi trường dev có thể giữ để debug.
        Sau này nếu cần có thể mask token.
        """
        return self.env["att.zalo.request.log"].sudo().create({
            "name": name,
            "config_id": config.id,
            "service_type": "oa",
            "direction": "outbound",
            "is_webhook": False,
            "endpoint": endpoint,
            "http_method": http_method,
            "request_headers": json.dumps(headers or {}, ensure_ascii=False, indent=2),
            "request_body": json.dumps(payload or {}, ensure_ascii=False, indent=2),
            "zalo_user_id": zalo_user_id,
        })