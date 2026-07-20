# -*- coding: utf-8 -*-
"""
HỢP ĐỒNG NGUYÊN TẮC (HĐNT) — khung pháp lý ký 1 lần với đối tác. mục đích cốt lõi để lưu thông tin.
Nguyên tắc cốt lõi: GIÁ KHÔNG NẰM TRÊN HỢP ĐỒNG — giá nằm ở PHỤ LỤC.
Đổi giá/thêm tuyến = ký phụ lục mới, không ký lại HĐ.
State machine:
    draft ──(GĐ duyệt)──> running ──> expired | liquidated
      └──> cancelled (chỉ từ draft; HĐ đã hiệu lực phải đi đường thanh lý)
"""
import logging
from datetime import timedelta
from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

ATT_CONTRACT_LOCK_EXEMPT_FIELDS = {
    'state', 'message_follower_ids', 'message_ids', 'activity_ids',
    'source_sale_order_id',
    'liquidation_reason_id', 'liquidation_note',
    'liquidation_requested_by', 'liquidation_requested_date',
}


class AttContract(models.Model):
    _name = 'att.contract'
    _description = 'Hợp đồng nguyên tắc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'effective_date desc, id desc'


    name = fields.Char('Số Hợp Đồng', default='/', copy=False, readonly=True)
    contract_type = fields.Selection([
        ('sale','Bán (Khách hàng)'),
        ('purchase','Mua (NCC)')
    ], 'Loại hợp đồng', required=True, default='sale', index=True)
    partner_id = fields.Many2one('res.partner', 'Đối tác', required=True, tracking=True, index=True)
    company_id = fields.Many2one('res.company', 'res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', 'Tiền tệ', default=lambda self: self.env.company.currency_id, tracking=True)
    user_id = fields.Many2one('res.users', 'Người phụ trách chính', default=lambda self: self.env.user, tracking=True)
    sign_date = fields.Date('Ngày ký', tracking=True)
    effective_date = fields.Date('Hiệu lực từ', required=True, tracking=True, default=fields.Date.context_today)
    expired_date = fields.Date('Hết hạn', required=True, tracking=True)
    state = fields.Selection([
        ('draft','Nháp'),
        ('running','Đang hiệu lực'),
        ('expired','Hết hạn'),
        ('liquidation_requested', 'Chờ duyệt thanh lý'),
        ('liquidated', 'Đã thanh lý'),
        ('cancelled','Đã huỷ'),
    ], default='draft', tracking=True, index=True, copy=False)

    # Báo giá NGUỒN — LÀ báo giá đang căn cứ giá cho phụ lục mới, ĐỔI ĐƯỢC
    # khi KH tái đàm phán giá (xem _att_rebase_price_source): A01 tạo HĐ,
    # sau đó A02 chốt giá mới → field này chuyển thẳng sang A02.
    # readonly=True chỉ chặn sửa tay trên form — code (_att_rebase_price_source)
    # vẫn ghi được bình thường.
    source_sale_order_id = fields.Many2one('sale.order','Báo giá nguồn', copy=False, readonly=True,
                                           tracking=True)
    source_purchase_order_id = fields.Many2one('purchase.order','Báo giá NCC nguồn', copy=False, readonly=True)

    # Lịch sử báo giá ĐÃ BỊ THAY THẾ — KHÔNG gồm báo giá nguồn hiện tại
    # (source_sale_order_id đã hiện riêng ở field trên). Tách riêng 2 field
    # để không trùng lặp: 1 field = đang dùng, 1 field = đã từng dùng.
    att_quotation_ids = fields.Many2many(
        'sale.order', compute='_compute_att_quotation_ids',
        string='Lịch sử báo giá đã thay thế',
        help='Các báo giá TỪNG là nguồn giá của HĐ này nhưng đã bị thay thế '
             'bởi báo giá mới hơn — không gồm báo giá nguồn đang dùng hiện tại.')

    partner_signer_ids = fields.Many2many('res.partner', 'att_contract_partner_signer_rel', 'contract_id', 'partner_id', 'Người ký bên A',
                                                                                    domain="[('id','child_of',partner_id)]", help='Liên hệ thuộc đôi tác - chức vụ đọc từ liên hệ.')
    company_signer_ids = fields.Many2many('res.partner', 'att_contract_company_signer_rel', 'contract_id', 'partner_id', 'Người ký bên B',
                                                                                    domain="[('user_ids','!=',False)]", help='Người dùng đại diện TH ký.')
    responsible_user_ids = fields.Many2many('res.users', 'att_contract_responsible_user_rel', 'contract_id', 'user_id', 'Người phụ trach',
                                                                                    help='Phụ trách triển khai/đối soát — tự follow chatter, nhận notify '
                                                                                         'mọi diễn biến HĐ. Không khoá theo trạng thái (bàn giao được).')
    note = fields.Html('Ghi chú')
    term_line_ids = fields.One2many('att.contract.term.line', 'contract_id', 'Điều khoản')
    att_can_edit = fields.Boolean('Được sửa nội dung', compute='_compute_att_can_edit')

    # ---- Snapshot thông tin đối tác tại thời điểm ký (không đổi theo
    # partner sau này — HĐ đã ký là văn bản pháp lý, đối tác đổi địa chỉ/SĐT
    # sau này không được tự động đổi theo trên HĐ cũ) ----
    partner_address = fields.Char('Địa chỉ đối tác', tracking=True)
    partner_phone = fields.Char('SĐT đối tác', tracking=True)
    partner_email = fields.Char('Email đối tác', tracking=True)
    partner_tax_code = fields.Char('Mã số thuế đối tác', tracking=True)
    partner_bank_account = fields.Char('Tài khoản ngân hàng đối tác', tracking=True)
    # Tên/chức vụ người đại diện — ghép hiển thị từ partner_signer_ids (đã có
    # sẵn ở trên), không tạo thêm M2M "người đại diện" trùng vai trò.
    partner_representative = fields.Char(
        'Người đại diện đối tác', compute='_compute_representative_display', store=True)
    partner_position = fields.Char(
        'Chức vụ người đại diện', compute='_compute_representative_display', store=True)

    # ---- Thanh toán ----
    payment_term_id = fields.Many2one('account.payment.term', 'Điều khoản thanh toán',
                                      tracking=True)
    payment_method = fields.Selection([
        ('bank_transfer', 'Chuyển khoản'),
        ('cash', 'Tiền mặt'),
        ('other', 'Khác'),
    ], 'Hình thức thanh toán', default='bank_transfer', tracking=True)
    payment_deadline_days = fields.Integer('Thời hạn thanh toán (ngày)', default=15,
                                           tracking=True)
    payment_document_note = fields.Text(
        'Hồ sơ thanh toán hợp lệ',
        default='Bảng kê cước vận chuyển; Hóa đơn tài chính hợp lệ.')
    payment_note = fields.Text('Ghi chú thanh toán')
    late_payment_penalty_note = fields.Text('Phạt chậm thanh toán')
    waiting_fee_note = fields.Text('Phí lưu ca/chờ hàng')

    # ---- Thanh lý — 2 bước: ai đó yêu cầu (bắt buộc chọn lý do) → CEO duyệt ----
    liquidation_reason_id = fields.Many2one('att.contract.liquidation.reason',
                                            string='Lý do thanh lý', tracking=True)
    liquidation_note = fields.Text('Ghi chú thanh lý', tracking=True)
    liquidation_requested_by = fields.Many2one('res.users', 'Người yêu cầu thanh lý',
                                               readonly=True, copy=False)
    liquidation_requested_date = fields.Datetime('Ngày yêu cầu thanh lý',
                                                 readonly=True, copy=False)


    @api.depends('state')
    def _compute_att_can_edit(self):
        is_admin = self.env.user.has_group('base.group_system')
        for rec in self:
            rec.att_can_edit = True if rec.state == 'draft' else is_admin


    @api.depends('source_sale_order_id')
    def _compute_att_quotation_ids(self):
        """Lấy TOÀN BỘ báo giá từng gắn att_contract_id vào HĐ này — không
        chỉ suy ra qua phụ lục, vì nếu HĐ bị đổi nguồn giá (rebase) TRƯỚC KHI
        kịp tạo phụ lục nào, báo giá cũ sẽ mất dấu vết nếu chỉ tính qua
        appendix_ids.source_sale_order_id (không phụ lục nào từng dùng nó).
        TRỪ báo giá nguồn ĐANG DÙNG hiện tại — field này chỉ để xem lịch sử
        đã thay thế, báo giá đang dùng đã hiện riêng ở source_sale_order_id."""
        for rec in self:
            if isinstance(rec.id, api.NewId) or not rec.id:
                rec.att_quotation_ids = False
                continue
            rec.att_quotation_ids = self.env['sale.order'].search([
                ('att_contract_id', '=', rec.id),
            ]) - rec.source_sale_order_id


    @api.depends('partner_signer_ids', 'partner_signer_ids.function')
    def _compute_representative_display(self):
        for rec in self:
            reps = rec.partner_signer_ids
            rec.partner_representative = ', '.join(reps.mapped('name')) or False
            rec.partner_position = ', '.join(
                r.function for r in reps if r.function) or False


    def _fill_partner_snapshot(self):
        """Chụp lại thông tin đối tác tại thời điểm ký — không tự đổi theo
        partner sau này (bài học từ module cũ: HĐ đã ký là văn bản pháp lý)."""
        for rec in self:
            partner = rec.partner_id
            if not partner:
                continue
            address_parts = [
                partner.street, partner.street2, partner.city,
                partner.state_id.name if partner.state_id else False,
                partner.country_id.name if partner.country_id else False,
            ]
            rec.partner_address = ', '.join(p for p in address_parts if p)
            rec.partner_phone = partner.phone
            rec.partner_email = partner.email
            rec.partner_tax_code = partner.vat
            bank = partner.bank_ids[:1]
            rec.partner_bank_account = bank.acc_number if bank else False


    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        self._fill_partner_snapshot()


    @api.model
    def _get_partner_short_name(self, partner):
        """Viết tắt tên đối tác cho số HĐ — chữ cái đầu mỗi từ, bỏ từ đệm
        loại hình doanh nghiệp (công ty, tnhh, cổ phần...)."""
        skip_words = {'công', 'ty', 'tnhh', 'cp', 'cổ', 'phần', 'mtv', 'một',
                      'thành', 'viên', 'và', 'the', 'co', 'ltd', 'group'}
        words = (partner.name or '').lower().split()
        initials = ''.join(w[0].upper() for w in words if w not in skip_words)
        return initials[:4] or 'KH'


    def write(self, vals):
        if set(vals.keys()) - ATT_CONTRACT_LOCK_EXEMPT_FIELDS:
            for rec in self:
                if rec.state != 'draft' and not self.env.user.has_group('base.group_system'):
                    raise UserError(_(
                        'Hợp đồng %s không còn ở trạng thái Nháp — chỉ Admin hệ '
                        'thống mới sửa được nội dung.') % rec.name)

        res = super().write(vals)
        if 'responsible_user_ids' in vals:
            self._att_subscribe_responsible()
        return res


    #contrains
    @api.constrains('effective_date', 'expired_date')
    def _check_dates(self):
        for rec in self:
            if rec.expired_date <= rec.effective_date:
                raise UserError(_('Ngày hết hạn phải sau ngày hiệu lực.'))


    @api.constrains('effective_date')
    def _check_price_source_date(self):
        """HĐ không thể 'có hiệu lực' trước ngày báo giá làm căn cứ giá còn
        chưa tồn tại — bắt lỗi kiểu set effective_date lùi về trước báo giá gốc.

        CHỈ phụ thuộc 'effective_date' (không phụ thuộc source_sale_order_id)
        — vì rebase (_att_rebase_price_source) chỉ đổi source_sale_order_id,
        KHÔNG đổi effective_date, mà báo giá mới rebase vào luôn có ngày SAU
        ngày hiệu lực HĐ (đúng bản chất tái đàm phán giá sau khi đã ký HĐ).
        Nếu để source_sale_order_id trong danh sách phụ thuộc, mỗi lần rebase
        sẽ tự kích hoạt lại check này và luôn báo lỗi sai."""
        for rec in self:
            source = rec.source_sale_order_id
            if source and source.date_order and rec.effective_date < source.date_order.date():
                raise UserError(_(
                    'Ngày hiệu lực HĐ (%(hl)s) không được trước ngày báo giá '
                    'căn cứ %(bg)s (%(ngay)s).',
                    hl=rec.effective_date.strftime('%d/%m/%Y'),
                    bg=source.name,
                    ngay=source.date_order.date().strftime('%d/%m/%Y')))


    #create, write - sequence + quotations + follow chatter
    @api.model
    def create(self, vals_list):
        for vals in vals_list:
            term_lines = vals.get('term_line_ids') or []
            if not any(cmd[0] in (0, 1, 4) for cmd in term_lines):
                raise UserError(_('Vui lòng thêm ít nhất một điều khoản trước khi tạo hợp đồng.'))
            if vals.get('name','/') in ('/', False):
                # Format: {stt}/{ddmmyyyy}/HĐNT/TH-{viết tắt đối tác}/{yyyy}
                # Không còn phân biệt B/M trong chuỗi số — đã có contract_type
                # riêng để phân biệt; 2 sequence riêng (sale/purchase) chỉ để
                # đếm độc lập, không in chữ ra số hiển thị.
                today = fields.Date.context_today(self)
                partner = self.env['res.partner'].browse(vals.get('partner_id'))
                partner_short = self._get_partner_short_name(partner) if partner else 'KH'
                code = ('att.contract.sale' if vals.get('contract_type','sale') == 'sale' else 'att.contract.purchase')
                seq_num = self.env['ir.sequence'].next_by_code(code) or '001'
                vals['name'] = (
                    f"{seq_num}/{today.strftime('%d%m%Y')}/HĐNT/TH-{partner_short}"
                )
        records = super().create(vals_list)
        records._fill_partner_snapshot()
        for rec in records:
            if rec.source_sale_order_id:
                # Chặn NGAY ĐIỂM GỐC chuyển trạng thái 'contracted' — không
                # chỉ chặn ở nút bấm trên báo giá (action_create_att_contract),
                # vì HĐ vẫn tạo được nếu ai đó vào thẳng menu Hợp đồng > New
                # rồi gán tay "Báo giá nguồn" (né qua nút, né luôn chốt chặn
                # đặt ở đó).
                rec.source_sale_order_id._th_check_cost_lines_confirmed()
                rec.source_sale_order_id.write({
                    'att_contract_id': rec.id,
                    'att_quote_state': 'contracted',
            })
            if rec.source_purchase_order_id:
                rec.source_purchase_order_id.write({
                    'att_contract_id': rec.id,
                    'att_quote_state': 'contracted',
                })
        records._att_subscribe_responsible()
        return records



    def _att_subscribe_responsible(self):
        """
        Người phụ trách tự follow chatter
        """
        for rec in self:
            partners = rec.responsible_user_ids.mapped('partner_id')
            if partners:
                rec.message_subscribe(partner_ids=partners.ids)


    def _att_check_ceo(self):
        """
        Server-side gate - ẩn nút theo group là chưa đủ (RPC vẫn gọi được)
        """
        if not self.env.user.has_group('att_contract_management.group_att_qc_ceo'):
            raise UserError(_('Chỉ CEO mới được thao tác này.'))


    def action_confirm(self):
        self.ensure_one()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Chỉ xác nhận được hợp đồng ở trạng thái nháp.'))
            rec.state = 'running'
            rec.message_post(
                body=Markup('<b>%s</b> đưa hợp đồng <b>%s</b> vào hiệu lực '
                            '(%s → %s).') % (
                         self.env.user.name, rec.name,
                         rec.effective_date.strftime('%d/%m/%Y'),
                         rec.expired_date.strftime('%d/%m/%Y')),
                message_type='notification', subtype_xmlid='mail.mt_note'
            )


    def _get_ceo_partners(self):
        """Partner của các user thuộc nhóm CEO — để tag Notify khi có yêu cầu thanh lý."""
        group = self.env.ref('att_contract_management.group_att_qc_ceo',
                             raise_if_not_found=False)
        if not group:
            return self.env['res.partner']
        return self.env['res.users'].search([
            ('group_ids', 'in', [group.id]),
            ('active', '=', True),
        ]).mapped('partner_id')

    def action_request_liquidation(self):
        """Quản lý trở lên yêu cầu thanh lý — bắt buộc chọn lý do trước.
        CEO là người duyệt cuối (action_approve_liquidation), tách 2 bước
        để có dấu vết ai yêu cầu, ai duyệt, vì sao."""
        if not self.env.user.has_group('att_contract_management.group_att_qc_manager'):
            raise UserError(_('Chỉ Quản lý trở lên mới được yêu cầu thanh lý.'))
        for rec in self:
            if rec.state not in ('running', 'expired'):
                raise UserError(_(
                    'Chỉ yêu cầu thanh lý hợp đồng đang hiệu lực hoặc đã hết hạn.'))
            if not rec.liquidation_reason_id:
                raise UserError(_('Vui lòng chọn Lý do thanh lý trước.'))
            rec.write({
                'liquidation_requested_by': self.env.user.id,
                'liquidation_requested_date': fields.Datetime.now(),
                'state': 'liquidation_requested',
            })
            rec.message_post(
                body=Markup(
                    '<b>%s</b> yêu cầu thanh lý hợp đồng <b>%s</b>.<br/>Lý do: %s'
                ) % (self.env.user.name, rec.name, rec.liquidation_reason_id.name),
                partner_ids=rec._get_ceo_partners().ids,
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_approve_liquidation(self):
        self._att_check_ceo()
        for rec in self:
            if rec.state != 'liquidation_requested':
                raise UserError(_('Chỉ duyệt thanh lý hợp đồng đang Chờ duyệt thanh lý.'))
            rec.state = 'liquidated'
            rec.message_post(
                body=Markup('<b>%s</b> đã duyệt thanh lý hợp đồng <b>%s</b>.') % (
                    self.env.user.name, rec.name),
                message_type='notification', subtype_xmlid='mail.mt_note')


    def action_cancel(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Chỉ huỷ được hợp đồng Nháp — '
                                  'HĐ đã hiệu lực phải đi đường thanh lý.'))
            rec.state = 'cancelled'


    def action_reset_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('Chỉ khôi phục được hợp đồng Đã huỷ.'))
            rec.state = 'draft'


    @api.model
    def _get_running_contract(self, partner, contract_type, company=None):
        """HĐ đang hiệu lực của đối tác (nếu có) — dùng chặn ký trùng HĐ,
        điều hướng user sang đường 'tạo phụ lục giá mới'."""
        return self.search([
            ('contract_type', '=', contract_type),
            ('partner_id', '=', partner.id),
            ('company_id', '=', (company or self.env.company).id),
            ('state', '=', 'running'),
        ], limit=1)


    def _att_rebase_price_source(self, new_quotation):
        """KH tái đàm phán giá: A02 chốt giá mới → source_sale_order_id
        chuyển THẲNG từ A01 sang A02. HĐ vẫn giữ nguyên (đã ký 1 lần, không
        ký lại), chỉ đổi 'báo giá đang căn cứ'. Phụ lục MỚI tạo sau đó load
        giá từ A02; phụ lục/đơn ĐÃ TẠO trước đó (đã tự lưu source_sale_order_id
        = A01 ngay lúc tạo) không đụng tới, giữ nguyên giá cũ.
        A01 chuyển att_quote_state='expired' (không bị huỷ/xoá) — vẫn giữ
        att_contract_id nên vẫn hiện trong att_quotation_ids (lịch sử báo
        giá nguồn của HĐ) để tra cứu, chỉ không còn là nguồn giá ĐANG hiệu
        lực nữa.

        Tự động huỷ các báo giá KHÁC còn mở (draft/sent, chưa từng gắn vào
        HĐ nào) của cùng KH — khác bên mua (NCC được giữ nhiều báo giá song
        song để so giá), KH chỉ có ĐÚNG 1 báo giá đang hiệu lực tại 1 thời điểm.
        """
        self.ensure_one()
        if not self.env.user.has_group('att_contract_management.group_att_qc_manager'):
            raise UserError(_('Chỉ Quản lý trở lên mới đổi được báo giá căn cứ của hợp đồng.'))
        if self.state != 'running':
            raise UserError(_(
                'Hợp đồng %s không ở trạng thái Đang hiệu lực — không đổi '
                'báo giá căn cứ được.') % self.name)
        if new_quotation.partner_id != self.partner_id:
            raise UserError(_(
                'Báo giá %(bg)s không cùng đối tác với hợp đồng %(hd)s.',
                bg=new_quotation.name, hd=self.name))
        old_source = self.source_sale_order_id
        self.write({'source_sale_order_id': new_quotation.id})
        if old_source and old_source != new_quotation:
            old_source.write({'att_quote_state': 'expired'})
        new_quotation.write({
            'att_contract_id': self.id,
            'att_quote_state': 'contracted',
        })
        self.message_post(
            body=Markup(
                'Đổi báo giá nguồn (KH tái đàm phán giá): <b>%(old)s</b> → '
                '<b>%(new)s</b>. Phụ lục mới sẽ load giá theo báo giá mới; '
                'phụ lục/đơn đã tạo trước đó giữ nguyên giá cũ.') % {
                    'old': old_source.name if old_source else '(chưa có)',
                    'new': new_quotation.name,
                },
            message_type='notification', subtype_xmlid='mail.mt_note')
        siblings = self.env['sale.order'].search([
            ('partner_id', '=', self.partner_id.id),
            ('att_is_execution', '=', False),
            ('id', '!=', new_quotation.id),
            ('att_quote_state', 'not in', ('contracted', 'expired')),
            ('state', 'in', ('draft', 'sent')),
        ])
        for sibling in siblings:
            sibling.message_post(
                body=Markup('Tự động huỷ — KH đã chốt giá theo báo giá khác '
                            '(<b>%s</b>).') % new_quotation.name,
                message_type='notification', subtype_xmlid='mail.mt_note')
            sibling.action_cancel()

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_notify_expiring_contracts(self, days=30):
        """Chạy hàng ngày: nhắc các HĐ đang hiệu lực sẽ hết hạn trong `days` ngày tới."""
        template = self.env.ref(
            'att_contract_management.email_template_contract_expiring',
            raise_if_not_found=False)
        if not template:
            return
        deadline = fields.Date.today() + timedelta(days=days)
        contracts = self.search([
            ('state', '=', 'running'),
            ('expired_date', '!=', False),
            ('expired_date', '<=', deadline),
            ('expired_date', '>=', fields.Date.today()),
        ])
        for rec in contracts:
            # Chỉ gửi 1 lần / HĐ — check log chatter để tránh spam mỗi ngày
            already_sent = self.env['mail.message'].search_count([
                ('model', '=', self._name),
                ('res_id', '=', rec.id),
                ('body', 'like', 'sắp hết hạn'),
            ])
            if already_sent:
                continue
            template.send_mail(rec.id, force_send=False)
            rec.message_post(
                body=Markup('Đã gửi thông báo hợp đồng <b>%s</b> sắp hết hạn (%s).') % (
                    rec.name, rec.expired_date.strftime('%d/%m/%Y')),
                message_type='notification', subtype_xmlid='mail.mt_note')
