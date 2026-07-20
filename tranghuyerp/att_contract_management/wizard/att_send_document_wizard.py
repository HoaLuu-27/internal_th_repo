# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AttSendDocumentWizard(models.TransientModel):
    """Popup chọn kênh gửi HĐNT / Phụ lục cho đối tác.

    v1: chỉ có kênh Email. Kênh 'zalo' KHÔNG cài ở đây — module att_zalo
    inherit wizard này, override _get_channel_selection() để thêm option
    'zalo' + override action_send()/_send_zalo() riêng. Không baked Zalo
    logic vào module contract để giữ module này gọn, không phụ thuộc
    tích hợp Zalo.

    Báo giá (sale.order/purchase.order) không cần khai báo trong
    _get_model_config() cho kênh Email — dùng thẳng luồng gửi native của
    Odoo (xem _send_email). Model khác chỉ cần khai báo 'template' trong
    _get_model_config() nếu muốn hỗ trợ kênh Email qua popup soạn thư riêng.
    """
    _name = 'att.send.document.wizard'
    _description = 'Chọn kênh gửi HĐNT / Phụ lục cho đối tác'

    res_model = fields.Char('Model nguồn', required=True)
    res_id = fields.Integer('ID chứng từ', required=True)
    channel = fields.Selection(
        selection='_get_channel_selection',
        string='Gửi qua', required=True, default='email',
    )

    @api.model
    def _get_model_config(self):
        """Cấu hình theo model — HÀM chứ không phải dict class-level, để
        module Zalo (hoặc module khác) inherit + gọi super() rồi bổ sung
        model mới (sale.order, purchase.order...) mà không mất config gốc."""
        return {
            'att.contract': {
                'template': 'att_contract_management.email_template_contract_draft',
                'label': 'bản nháp hợp đồng nguyên tắc',
            },
            'att.contract.appendix': {
                'template': 'att_contract_management.email_template_appendix_draft',
                'label': 'bản nháp phụ lục hợp đồng',
            },
        }

    @api.model
    def _get_channel_selection(self):
        channels = [('email', 'Email')]
        # 'call' CHỈ hiện khi nút mở wizard tự truyền context att_allow_call
        # (chỉ chiều mua — RFQ NCC — mới có nút gọi điện hỏi giá).
        if self.env.context.get('att_allow_call'):
            channels.append(('call', 'Gọi điện'))
        return channels

    def action_send(self):
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise UserError(_('Chứng từ không còn tồn tại.'))
        if self.channel == 'email':
            return self._send_email(record)
        if self.channel == 'call':
            return self._send_call(record)
        raise UserError(_('Kênh gửi "%s" chưa được hỗ trợ.') % self.channel)

    def _send_email(self, record):
        """Email — báo giá (sale.order/purchase.order) TÁI DÙNG đúng luồng
        gửi mail native của Odoo (nút "Send" gốc): đã có sẵn mẫu, tự điền
        người nhận theo đối tác, tự đính kèm đúng report PDF chuẩn — không
        tự dựng lại. HĐNT/Phụ lục (att.contract/att.contract.appendix)
        không có luồng gửi native (model tự viết) nên mới tự mở popup soạn
        thư kèm mẫu riêng của module này."""
        if self.res_model == 'sale.order':
            return record.action_quotation_send()
        if self.res_model == 'purchase.order':
            return record.action_rfq_send()
        # conf.get('template') — không dùng conf['template'] vì module khác
        # (VD Zalo) có thể chỉ khai báo 'report' (dùng cho kênh Zalo) mà
        # không có 'template' (dùng cho kênh Email) khi bổ sung model mới.
        conf = self._get_model_config()[self.res_model]
        template_xmlid = conf.get('template')
        template = (self.env.ref(template_xmlid, raise_if_not_found=False)
                    if template_xmlid else False)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': self.res_model,
                'default_res_ids': [record.id],
                'default_use_template': bool(template),
                'default_template_id': template.id if template else False,
                'default_composition_mode': 'comment',
            },
        }

    def _send_call(self, record):
        """Kênh gọi điện — tạo cuộc gọi VoIP nếu có cài module voip, không
        thì fallback activity "Gọi điện" gán người phụ trách. Không phụ
        thuộc Zalo — dùng module voip có sẵn của Odoo (nếu có cài)."""
        partner = record.partner_id
        user = record.user_id or self.env.user
        if 'voip.call' in self.env:
            self.env['voip.call'].create({
                'partner_id': partner.id,
                'user_id': user.id,
                'phone_number': partner.phone or '',
                'direction': 'outgoing',
            })
        else:
            record.activity_schedule(
                'mail.mail_activity_data_call',
                user_id=user.id,
                summary=_('Gọi %s trao đổi %s') % (partner.name, record.name),
            )
        # Đã liên hệ NCC → chuyển RFQ sang "Đã gửi" như đường email
        if self.res_model == 'purchase.order' and record.state == 'draft':
            record.write({'state': 'sent'})
        record.message_post(
            body=_('Đã tạo cuộc gọi trao đổi với %(doi_tac)s (%(sdt)s).',
                   doi_tac=partner.name, sdt=partner.phone or 'chưa có SĐT'),
            message_type='notification', subtype_xmlid='mail.mt_note')
        return {'type': 'ir.actions.act_window_close'}
