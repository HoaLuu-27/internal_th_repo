# -*- coding: utf-8 -*-

import time
from markupsafe import Markup

from odoo import http, fields
from odoo.http import request


class WebsiteTransportService(http.Controller):

    def _get_remote_ip(self):
        return request.httprequest.headers.get(
            "X-Forwarded-For",
            request.httprequest.remote_addr or ""
        ).split(",")[0].strip()

    def _check_honeypot(self, post):
        return not post.get("website_url")

    def _rate_limit_ok(self):
        ip = self._get_remote_ip() or "unknown"
        key = "att_quotations_contracts.website_quote.%s" % ip
        icp = request.env["ir.config_parameter"].sudo()

        now = int(time.time())
        raw = icp.get_param(key)

        window = 10 * 60
        max_submit = 5

        if raw:
            try:
                first_ts, count = [int(x) for x in raw.split(":")]
            except Exception:
                first_ts, count = now, 0

            if now - first_ts <= window:
                if count >= max_submit:
                    return False
                icp.set_param(key, "%s:%s" % (first_ts, count + 1))
                return True

        icp.set_param(key, "%s:1" % now)
        return True

    def _validate_required(self, post):
        required = {
            "name": "Họ tên",
            "phone": "Số điện thoại",
            "email": "Email",
            "pickup_location": "Điểm đi",
            "delivery_location": "Điểm đến",
            "cargo_description": "Mô tả hàng hóa",
        }

        errors = []
        for field_name, label in required.items():
            if not (post.get(field_name) or "").strip():
                errors.append("Vui lòng nhập %s." % label)

        return errors

    def _find_or_create_customer(self, post):
        Partner = request.env["res.partner"].sudo()

        name = (post.get("name") or "").strip()
        phone = (post.get("phone") or "").strip()
        email = (post.get("email") or "").strip()

        partner = Partner.browse()

        if email:
            partner = Partner.search([("email", "=", email)], limit=1)

        if not partner and phone:
            partner = Partner.search([("phone", "=", phone)], limit=1)

        vals = {
            "name": name or phone or email or "Khách hàng website",
            "email": email,
            "phone": phone,
            "company_type": "person",
            "customer_rank": 1,
        }

        vals = {
            key: value
            for key, value in vals.items()
            if key in Partner._fields and value not in (False, None, "")
        }

        if partner:
            write_vals = {}

            if name and "name" in Partner._fields:
                write_vals["name"] = name

            if email and "email" in Partner._fields:
                write_vals["email"] = email

            if phone and "phone" in Partner._fields:
                write_vals["phone"] = phone

            if "customer_rank" in Partner._fields:
                write_vals["customer_rank"] = max(partner.customer_rank, 1)

            if write_vals:
                partner.write(write_vals)

            return partner

        return Partner.create(vals)

    def _get_sales_team(self):
        Team = request.env["crm.team"].sudo()

        team = Team.search([
            "|",
            ("name", "ilike", "Kinh doanh"),
            ("name", "ilike", "Sales"),
        ], limit=1)

        if not team:
            team = Team.search([], limit=1)

        return team

    def _get_team_sales_users(self, team):
        Users = request.env["res.users"].sudo()
        users = Users.browse()

        if team:
            if "member_ids" in team._fields:
                users |= team.member_ids
            if "user_id" in team._fields and team.user_id:
                users |= team.user_id

            TeamMember = request.env.get("crm.team.member")
            if TeamMember:
                members = TeamMember.sudo().search([("crm_team_id", "=", team.id)])
                if "user_id" in TeamMember._fields:
                    users |= members.mapped("user_id")

        if not users:
            sales_group = request.env.ref("sales_team.group_sale_salesman", raise_if_not_found=False)
            domain = [("active", "=", True)]
            if sales_group:
                domain.append(("groups_id", "in", [sales_group.id]))
            users = Users.search(domain)

        users = users.filtered(lambda u: u.active and not u.share)

        if not users:
            users = request.env.ref("base.user_admin").sudo()

        return users.sorted("id")

    def _get_next_salesperson(self, team):
        users = self._get_team_sales_users(team)

        key = "att_quotations_contracts.website_quote.last_user_id"
        icp = request.env["ir.config_parameter"].sudo()
        last_id = int(icp.get_param(key, "0") or 0)

        next_user = users[0]
        for idx, user in enumerate(users):
            if user.id == last_id:
                next_user = users[(idx + 1) % len(users)]
                break

        icp.set_param(key, str(next_user.id))
        return next_user

    def _create_service_product_from_request(self, mode, post):
        Product = request.env["product.product"].sudo()

        pickup = (post.get("pickup_location") or "").strip()
        delivery = (post.get("delivery_location") or "").strip()
        cargo_description = (post.get("cargo_description") or "").strip()
        cargo_weight = (post.get("cargo_weight") or "").strip()
        expected_date = (post.get("expected_date") or "").strip()
        note = (post.get("note") or "").strip()

        product_name = "%s - %s" % (pickup, delivery)

        description_lines = [
            "Hình thức vận chuyển: %s" % mode.name,
            "Điểm đi: %s" % pickup,
            "Điểm đến: %s" % delivery,
            "Mô tả hàng hóa: %s" % cargo_description,
        ]

        if cargo_weight:
            description_lines.append("Khối lượng: %s" % cargo_weight)
        if expected_date:
            description_lines.append("Ngày dự kiến: %s" % expected_date)
        if note:
            description_lines.append("Ghi chú: %s" % note)

        product_vals = {
            "name": product_name,
            "sale_ok": True,
            "purchase_ok": False,
            "list_price": 0.0,
            "description_sale": "\n".join(description_lines),
        }

        if "type" in Product._fields:
            product_vals["type"] = "service"
        elif "detailed_type" in Product._fields:
            product_vals["detailed_type"] = "service"

        return Product.create(product_vals)

    def _format_body(self, mode, post, order=False, product=False):
        return Markup("""
            <p><b>Báo giá yêu cầu từ website</b></p>
            <ul>
                <li><b>Mã báo giá:</b> %s</li>
                <li><b>Khách hàng:</b> %s</li>
                <li><b>Số điện thoại:</b> %s</li>
                <li><b>Email:</b> %s</li>
                <li><b>Sản phẩm dịch vụ:</b> %s</li>
                <li><b>Hình thức vận chuyển:</b> %s</li>
                <li><b>Điểm đi:</b> %s</li>
                <li><b>Điểm đến:</b> %s</li>
                <li><b>Mô tả hàng hóa:</b> %s</li>
                <li><b>Khối lượng:</b> %s</li>
                <li><b>Ngày dự kiến:</b> %s</li>
                <li><b>Ghi chú:</b> %s</li>
            </ul>
        """) % (
            order.name if order else "",
            post.get("name") or "",
            post.get("phone") or "",
            post.get("email") or "",
            product.name if product else "",
            mode.name,
            post.get("pickup_location") or "",
            post.get("delivery_location") or "",
            post.get("cargo_description") or "",
            post.get("cargo_weight") or "",
            post.get("expected_date") or "",
            post.get("note") or "",
        )

    @http.route("/dich-vu", type="http", auth="public", website=True, sitemap=True)
    def service_list(self, **kw):
        modes = request.env["att.transport.mode"].sudo().search([
            ("active", "=", True),
            ("website_published", "=", True),
        ], order="sequence, name")

        return request.render("att_quotations_contracts.website_service_list", {
            "modes": modes,
        })

    @http.route("/shop", type="http", auth="public", website=True, sitemap=False)
    def redirect_shop(self, **kw):
        return request.redirect("/dich-vu", code=301)

    @http.route(
        "/dich-vu/<model('att.transport.mode'):mode>/bao-gia",
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def quote_form(self, mode, **kw):
        mode = mode.sudo()
        if not mode.active or not mode.website_published:
            return request.not_found()

        return request.render("att_quotations_contracts.website_quote_form", {
            "mode": mode,
            "errors": [],
            "values": {},
        })

    @http.route(
        "/dich-vu/<model('att.transport.mode'):mode>/bao-gia/submit",
        type="http",
        auth="public",
        website=True,
        methods=["POST"],
        csrf=True,
        sitemap=False,
    )
    def quote_submit(self, mode, **post):
        mode = mode.sudo()

        if not mode.active or not mode.website_published:
            return request.not_found()

        errors = self._validate_required(post)

        if not self._check_honeypot(post):
            errors.append("Dữ liệu không hợp lệ.")

        if not self._rate_limit_ok():
            errors.append("Bạn gửi quá nhiều yêu cầu. Vui lòng thử lại sau.")

        if errors:
            return request.render("att_quotations_contracts.website_quote_form", {
                "mode": mode,
                "errors": errors,
                "values": post,
            })

        partner = self._find_or_create_customer(post)
        product = self._create_service_product_from_request(mode, post)

        team = self._get_sales_team()
        salesperson = self._get_next_salesperson(team)

        line_note_parts = []
        if post.get("cargo_weight"):
            line_note_parts.append("Khối lượng: %s" % post.get("cargo_weight"))
        if post.get("note"):
            line_note_parts.append("Ghi chú: %s" % post.get("note"))

        expected_date = post.get("expected_date")
        expected_datetime = "%s 00:00:00" % expected_date if expected_date else False

        order_line_vals = {
            "product_id": product.id,
            "name": product.name,
            "product_uom_qty": 1.0,
            "price_unit": 0.0,
        }

        SaleOrderLine = request.env["sale.order.line"].sudo()

        optional_line_vals = {
            "transport_mode_id": mode.id,
            "pickup_location": post.get("pickup_location"),
            "delivery_location": post.get("delivery_location"),
            "cargo_description": post.get("cargo_description"),
            "cargo_weight": post.get("cargo_weight") or False,
            "expected_date": expected_datetime,
            "att_line_note": "\n".join(line_note_parts) if line_note_parts else False,
        }

        for field_name, field_value in optional_line_vals.items():
            if field_name in SaleOrderLine._fields:
                order_line_vals[field_name] = field_value

        SaleOrder = request.env["sale.order"].sudo()

        order_vals = {
            "partner_id": partner.id,
            "user_id": salesperson.id,
            "origin": "Website - %s" % mode.name,
            "note": post.get("note") or "",
            "order_line": [(0, 0, order_line_vals)],
        }

        if "att_quote_state" in SaleOrder._fields:
            order_vals["att_quote_state"] = "draft"

        if team and "team_id" in SaleOrder._fields:
            order_vals["team_id"] = team.id

        order = SaleOrder.create(order_vals)

        body = self._format_body(mode, post, order=order, product=product)

        order.message_post(
            body=body,
            partner_ids=[salesperson.partner_id.id] if salesperson.partner_id else [],
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )

        activity_type = request.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        if activity_type:
            order.activity_schedule(
                activity_type_id=activity_type.id,
                summary="Báo giá yêu cầu từ website",
                note=body,
                user_id=salesperson.id,
                date_deadline=fields.Date.context_today(order),
            )

        return request.redirect("/dich-vu/bao-gia/thank-you?so=%s" % order.id)

    @http.route("/dich-vu/bao-gia/thank-you", type="http", auth="public", website=True, sitemap=False)
    def quote_thank_you(self, so=None, **kw):
        order = request.env["sale.order"].sudo().browse(int(so)) if so else False
        if not order or not order.exists():
            order = False

        return request.render("att_quotations_contracts.website_quote_thank_you", {
            "order": order,
        })