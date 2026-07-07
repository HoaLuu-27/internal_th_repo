import base64
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AttqcSendQuotationWizard(models.TransientModel):
    """Popup chọn kênh gửi — dùng chung cho BÁO GIÁ, HĐNT và PHỤ LỤC.

    Kênh theo chiều nghiệp vụ (không theo model):
    - Chiều BÁN  (gửi khách hàng) : Email / Zalo
    - Chiều MUA  (gửi NCC)        : Email / Zalo / Gọi điện
    Nút mở wizard truyền cờ attqc_allow_call trong context để bật kênh gọi.

    Zalo: tích hợp qua module att_zalo_connector — render PDF chứng từ,
    upload lấy file token rồi gửi tin kèm file tới zalo_user_id của đối tác.
    """
    _name = 'attqc.send.quotation.wizard'
    _description = 'Chọn kênh gửi chứng từ'

    res_model = fields.Char('Model nguồn', required=True)
    res_id = fields.Integer('ID chứng từ', required=True)
    channel = fields.Selection(
        selection='_get_channel_selection',
        string='Gửi qua', required=True, default='email',
    )

    # Cấu hình theo model: report để render PDF gửi Zalo + mô tả trong tin nhắn
    _MODEL_CONFIG = {
        'sale.order': {
            'report': 'att_quotations_contracts.report_attqc_sale_quotation',
            'label': 'báo giá vận chuyển',
        },
        'purchase.order': {
            'report': 'att_quotations_contracts.report_attqc_purchase_quotation',
            'label': 'yêu cầu báo giá',
        },
        'att.contract': {
            'report': 'att_quotations_contracts.report_att_contract',
            'label': 'bản nháp hợp đồng nguyên tắc',
        },
        'att.contract.appendix': {
            'report': 'att_quotations_contracts.report_att_appendix',
            'label': 'bản nháp phụ lục hợp đồng',
        },
    }

    @api.model
    def _get_channel_selection(self):
        channels = [('email', 'Email'), ('zalo', 'Zalo')]
        if self.env.context.get('attqc_allow_call'):
            channels.append(('call', 'Gọi điện'))
        return channels

    # ------------------------------------------------------------------
    # Gửi
    # ------------------------------------------------------------------
    def action_send(self):
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise UserError(_('Chứng từ không còn tồn tại.'))
        self._check_sale_quote_gate(record)
        # Bỏ các key default_* của wizard chọn kênh khỏi context trước khi
        # ủy quyền cho flow gửi của record: action_rfq_send native copy nguyên
        # env.context sang mail.compose.message, mà compose v19 raise ValueError
        # khi thấy default_res_id (bắt dùng default_res_ids).
        record = record.with_context({
            k: v for k, v in self.env.context.items()
            if k not in ('default_res_model', 'default_res_id', 'default_channel')
        })

        if self.channel == 'email':
            return self._send_email(record)
        if self.channel == 'zalo':
            return self._send_zalo(record)
        return self._send_call(record)

    def _check_sale_quote_gate(self, record):
        """Báo giá BÁN chưa duyệt giá thì kênh nào cũng không được gửi —
        Zalo/gọi điện không phải cửa lách để lộ giá chưa kiểm soát."""
        if (self.res_model == 'sale.order' and not record.att_is_execution
                and record.att_quote_state not in ('approved', 'won', 'contracted')):
            raise UserError(_(
                'Báo giá %s chưa được duyệt giá nội bộ — dùng nút '
                '"Yêu cầu duyệt giá" trước khi gửi khách hàng.') % record.name)

    def _send_email(self, record):
        """Email → tái dùng flow gửi mail sẵn có của từng model."""
        if self.res_model == 'sale.order':
            return record.action_quotation_send()
        if self.res_model == 'purchase.order':
            return record.action_rfq_send()
        if self.res_model == 'att.contract':
            return record.action_send_draft_to_partner()
        return record.action_send_draft()  # appendix

    def _send_zalo(self, record):
        """Gửi Zalo QUA DISCUSS — không gọi thẳng att.zalo.oa.api.

        Post 2 message vào channel Zalo của đối tác; override message_post
        của discuss.channel (att_zalo_connector) tự bắn sang Zalo:
        - Tin 1: text ngữ cảnh (body → send_text)
        - Tin 2: file PDF   (attachment → upload_file + send_message_with_file)
        Tách 2 tin vì Zalo API bỏ text khi message có attachment. Nhờ đi qua
        Discuss, nhân viên thấy được lịch sử gửi ngay trong channel chat với KH.
        """
        if 'att.zalo.oa.api' not in self.env:
            raise UserError(_('Chưa cài module att_zalo_connector.'))
        # sudo cho phần hạ tầng Zalo: user gửi báo giá là sales/purchase thường,
        # KHÔNG thuộc group Zalo OA Agent nên không phải member channel Zalo và
        # không có quyền đọc config — nhưng nghiệp vụ cho phép gửi (đã qua gate
        # duyệt giá + quyền mở chứng từ). sudo chỉ nâng quyền, author message
        # vẫn là user hiện tại.
        config = self.env['att.zalo.service.config'].sudo()._get_active_oa_config()
        if not config:
            raise UserError(_('Chưa có cấu hình Zalo OA đang hoạt động.'))
        partner = record.partner_id
        if not partner.zalo_user_id:
            raise UserError(_(
                'Đối tác %s chưa liên kết Zalo (thiếu Zalo User ID) — '
                'đối tác cần nhắn tin cho OA Trang Huy trước.') % partner.name)

        conf = self._MODEL_CONFIG[self.res_model]
        pdf_content, _dummy = self.env['ir.actions.report']._render_qweb_pdf(
            conf['report'], res_ids=[record.id])
        filename = '%s.pdf' % (record.name or 'document').replace('/', '_')
        text = self._get_zalo_message(record)

        channel = self.env['discuss.channel'].sudo().zalo_get_or_create_channel(
            config, partner, partner.zalo_user_id)

        marker_base = 'attqc_zalo:%s:%s' % (self.res_model, self.res_id)

        # Tin 1 — text (không attachment → override gọi send_text)
        def _post_text():
            channel.message_post(
                body=text,
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

        # Tin 2 — file PDF (có attachment → override upload + gửi file)
        def _post_file():
            attachment = self.env['ir.attachment'].sudo().create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'mimetype': 'application/pdf',
                'res_model': 'discuss.channel',
                'res_id': channel.id,
            })
            channel.message_post(
                attachment_ids=[attachment.id],
                message_type='comment',
                subtype_xmlid='mail.mt_comment',
            )

        self._zalo_send_once(config, '%s:text' % marker_base, _post_text)
        self._zalo_send_once(config, '%s:file' % marker_base, _post_file)

        self._apply_sent_side_effects(record)
        record.message_post(
            body=Markup('Đã gửi %s <b>%s</b> qua <b>Zalo</b> đến <b>%s</b>.') % (
                conf['label'], record.name, partner.name),
            message_type='notification', subtype_xmlid='mail.mt_note')
        return {'type': 'ir.actions.act_window_close'}

    def _zalo_send_once(self, config, marker_key, send_func):
        """Chống gửi trùng sang Zalo khi request bị chạy lại.

        Odoo auto-retry cả request khi dính serialization failure: DB rollback
        được nhưng TIN ĐÃ SANG ZALO thì không rút lại được → khách nhận N tin
        trùng. Cách chặn: gửi xong là ghi marker vào att.zalo.request.log và
        COMMIT NGAY (sống sót qua rollback). Lần chạy lại (auto-retry hoặc user
        bấm gửi lại) trong cửa sổ 5 phút thấy marker → bỏ qua tin đã đi, chỉ
        gửi phần chưa gửi. Quá 5 phút coi như lượt gửi mới (gửi lại có chủ đích).
        """
        Log = self.env['att.zalo.request.log'].sudo()
        window_start = fields.Datetime.now() - timedelta(minutes=5)
        if Log.search_count([
            ('name', '=', marker_key),
            ('create_date', '>=', window_start),
        ]):
            return False  # đã gửi trong lượt này (request retry) — bỏ qua
        send_func()
        Log.create({
            'name': marker_key,
            'config_id': config.id,
            'service_type': 'oa',
            'direction': 'outbound',
            'endpoint': 'attqc_send_once_marker',
            'state': 'done',
        })
        # Commit để marker (và tin vừa post) không bị rollback nếu phần sau
        # của request lỗi — đây là điểm mấu chốt chặn duplicate
        self.env.cr.commit()
        return True

    def _get_zalo_message(self, record):
        """Tin nhắn Zalo theo ngữ cảnh từng loại chứng từ — không dùng câu
        chung chung; nêu rõ gửi gì, cho yêu cầu nào, cần đối tác làm gì."""
        name = record.name
        if self.res_model == 'sale.order':
            routes = ', '.join(
                '%s → %s' % (l.pickup_location, l.delivery_location)
                for l in record.order_line
                if not l.display_type and l.pickup_location and l.delivery_location)
            msg = _('Trang Huy Logistics kính gửi anh/chị báo giá %s cho yêu cầu '
                    'vận chuyển của Quý khách') % name
            if routes:
                msg += _(' (tuyến: %s)') % routes
            msg += _('. Tổng giá trị: %s.') % record.currency_id.format(record.amount_total)
            if record.validity_date:
                msg += _(' Báo giá có hiệu lực đến %s.') % record.validity_date.strftime('%d/%m/%Y')
            msg += _(' Chi tiết trong file đính kèm, anh/chị xem và phản hồi giúp bên em nhé.')
            return msg
        if self.res_model == 'purchase.order':
            routes = ', '.join(
                '%s → %s' % (l.pickup_location, l.delivery_location)
                for l in record.order_line
                if not l.display_type and l.pickup_location and l.delivery_location)
            msg = _('Trang Huy Logistics gửi anh/chị yêu cầu báo giá %s cho nhu cầu '
                    'thuê vận chuyển') % name
            if routes:
                msg += _(' (tuyến: %s)') % routes
            msg += _('. Nhờ anh/chị xem file đính kèm và báo giá giúp bên em sớm nhé.')
            return msg
        if self.res_model == 'att.contract':
            return _('Trang Huy Logistics gửi anh/chị bản nháp hợp đồng nguyên tắc %s '
                     'để Quý công ty xem xét. Anh/chị xem file đính kèm và phản hồi '
                     'giúp bên em nếu cần điều chỉnh nhé.') % name
        # att.contract.appendix
        return _('Trang Huy Logistics gửi anh/chị bản nháp phụ lục %(pl)s thuộc hợp đồng '
                 '%(hd)s. Anh/chị xem file đính kèm và phản hồi giúp bên em nếu cần '
                 'điều chỉnh nhé.') % {'pl': name, 'hd': record.contract_id.name}

    def _apply_sent_side_effects(self, record):
        """Gửi Zalo cũng phải chuyển trạng thái y như gửi email —
        không để chứng từ 'đã đến tay đối tác' mà vẫn nằm ở Nháp."""
        if self.res_model == 'sale.order' and record.state == 'draft':
            record.write({'state': 'sent'})
        elif self.res_model == 'purchase.order' and record.state == 'draft':
            record.write({'state': 'sent'})
        elif self.res_model == 'att.contract.appendix' and record.state == 'draft':
            record.write({'state': 'sent_draft'})
        # att.contract: gửi nháp không đổi state (vẫn Nháp chờ đối tác góp ý)

    def _send_call(self, record):
        """Kênh gọi điện — chỉ chiều mua (RFQ / HĐ mua / phụ lục mua)."""
        if self.res_model == 'purchase.order':
            return record._action_call_ncc()
        # HĐ/phụ lục: tạo cuộc gọi VoIP (hoặc activity nếu chưa cài voip)
        partner = record.partner_id
        if 'voip.call' in self.env:
            self.env['voip.call'].create({
                'partner_id': partner.id,
                'user_id': record.user_id.id or self.env.user.id,
                'phone_number': partner.phone or '',
                'direction': 'outgoing',
            })
        else:
            record.activity_schedule(
                'mail.mail_activity_data_call',
                user_id=record.user_id.id or self.env.user.id,
                summary=_('Gọi %s trao đổi %s') % (partner.name, record.name),
            )
        record.message_post(
            body=Markup('Đã tạo cuộc gọi trao đổi với <b>%s</b> (%s).') % (
                partner.name, partner.phone or 'chưa có SĐT'),
            message_type='notification', subtype_xmlid='mail.mt_note')
        return {'type': 'ir.actions.act_window_close'}
