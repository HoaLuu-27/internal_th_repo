import logging
import re
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class Contract(models.Model):
    """Hợp đồng nguyên tắc (HĐK) — KHÔNG chứa giá, giá nằm ở phụ lục.

    Dùng chung cho cả 2 phía:
    - Bán : tạo từ SO báo giá đã được KH chốt (source_sale_order_id)
    - Mua : tạo từ RFQ thắng thầu (source_purchase_order_id) — phải đủ
            số lượng RFQ tối thiểu trong nhóm alternatives (xem purchase_order.py)
    """
    _name = 'att.contract'
    _description = 'Hợp đồng nguyên tắc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char('Số hợp đồng', required=True, copy=False, readonly=True,
                       default='New', tracking=True, index=True)
    contract_type = fields.Selection([
        ('sale', 'Hợp đồng bán'),
        ('purchase', 'Hợp đồng mua'),
    ], string='Loại hợp đồng', required=True, tracking=True, index=True)

    # ---- Điểm nối với báo giá native (thay cho att.quotation.request ở module cũ) ----
    source_sale_order_id = fields.Many2one(
        'sale.order', 'Báo giá gốc (SO)', copy=False, tracking=True,
        domain="[('partner_id', '=', partner_id)]",
        help='SO báo giá (draft/sent) mà KH đã chốt — căn cứ tạo HĐ bán.',
    )
    source_purchase_order_id = fields.Many2one(
        'purchase.order', 'RFQ thắng thầu', copy=False, tracking=True,
        domain="[('partner_id', '=', partner_id)]",
        help='RFQ của NCC được chọn sau khi so sánh alternatives — căn cứ tạo HĐ mua.',
    )

    partner_id = fields.Many2one('res.partner', 'Đối tác', required=True, tracking=True)
    user_id = fields.Many2one('res.users', 'Người phụ trách',
                              default=lambda self: self.env.user, tracking=True)
    company_id = fields.Many2one('res.company', 'Công ty', required=True, tracking=True,
                                 default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one('res.currency', 'Tiền tệ',
                                  default=lambda self: self.env.company.currency_id)

    # Hiệu lực — readonly theo state xử lý ở view (Odoo 19 không còn states= trên field)
    effective_date = fields.Date('Ngày hiệu lực', tracking=True,
                                 help='Tự điền khi xác nhận HĐ nếu để trống')
    expired_date = fields.Date('Ngày hết hạn', tracking=True)

    # ---- Snapshot thông tin đối tác tại thời điểm ký (không đổi theo partner sau này) ----
    partner_address = fields.Char('Địa chỉ đối tác', tracking=True)
    partner_phone = fields.Char('SĐT đối tác', tracking=True)
    partner_email = fields.Char('Email đối tác', tracking=True)
    partner_tax_code = fields.Char('Mã số thuế đối tác', tracking=True)
    partner_bank_account = fields.Char('Tài khoản ngân hàng đối tác', tracking=True)
    # Người đại diện ký = M2M tới CONTACT của đối tác — một HĐ có thể nhiều
    # người ký, tên + chức vụ lấy từ chính contact (không gõ tay text nữa)
    partner_representative_ids = fields.Many2many(
        'res.partner', 'att_contract_representative_rel', 'contract_id', 'partner_id',
        string='Người đại diện ký',
        domain="[('id', 'child_of', partner_id)]", tracking=True)
    # 2 field text giữ lại dạng COMPUTED (ghép từ M2M) để report/template cũ
    # dùng doc.partner_representative / doc.partner_position không phải sửa
    partner_representative = fields.Char(
        'Người đại diện đối tác', compute='_compute_representative_display', store=True)
    partner_position = fields.Char(
        'Chức vụ người đại diện', compute='_compute_representative_display', store=True)

    # ---- Thanh toán ----
    payment_term_id = fields.Many2one('account.payment.term', 'Điều khoản thanh toán', tracking=True)
    payment_method = fields.Selection([
        ('bank_transfer', 'Chuyển khoản'),
        ('cash', 'Tiền mặt'),
        ('other', 'Khác'),
    ], 'Hình thức thanh toán', default='bank_transfer', tracking=True)
    payment_deadline_days = fields.Integer('Thời hạn thanh toán (ngày)', default=15, tracking=True)
    payment_document_note = fields.Text(
        'Hồ sơ thanh toán hợp lệ',
        default='Bảng kê cước vận chuyển; Hóa đơn tài chính hợp lệ.')
    payment_note = fields.Text('Ghi chú thanh toán')
    late_payment_penalty_note = fields.Text('Phạt chậm thanh toán')
    waiting_fee_note = fields.Text('Phí lưu ca/chờ hàng')

    # ---- Điều khoản ----
    term_line_ids = fields.One2many('att.contract.term.line', 'contract_id',
                                    'Điều khoản hợp đồng', copy=True)

    # ---- Thanh lý ----
    liquidation_reason_id = fields.Many2one('att.contract.liquidation.reason',
                                            string='Lý do thanh lý', tracking=True)
    liquidation_note = fields.Text('Ghi chú thanh lý', tracking=True)
    liquidation_requested_by = fields.Many2one('res.users', 'Người yêu cầu thanh lý', readonly=True)
    liquidation_requested_date = fields.Datetime('Ngày yêu cầu thanh lý', readonly=True)

    # ---- Phụ lục & chứng từ thực thi ----
    appendix_ids = fields.One2many('att.contract.appendix', 'contract_id', 'Phụ lục', readonly=True)
    appendix_count = fields.Integer('Số phụ lục', compute='_compute_appendix_count')
    # Phụ lục đang áp = phụ lục confirmed/done mới nhất chưa bị thay thế —
    # đây là nguồn giá duy nhất cho SO/PO thực thi
    active_appendix_id = fields.Many2one('att.contract.appendix', 'Phụ lục đang áp',
                                         compute='_compute_active_appendix_id', store=True)
    # QUAN HỆ CHUẨN (không nhầm lẫn lại):
    # - BÁN : HĐNT ↔ N báo giá (SO draft, att_contract_id). SO THỰC THI chỉ link
    #         PHỤ LỤC (att_appendix_id), KHÔNG link HĐNT — truy vết qua phụ lục.
    # - MUA : HĐNT ↔ N báo giá (RFQ, att_is_execution=False). PO thực thi
    #         (att_is_execution=True) ĐƯỢC link HĐNT vì cho phép tạo PO
    #         trực tiếp từ HĐNT lẫn từ phụ lục.
    sale_order_ids = fields.One2many('sale.order', 'att_contract_id',
                                     'Báo giá (SO)', readonly=True)
    purchase_order_ids = fields.One2many('purchase.order', 'att_contract_id',
                                         'Chứng từ mua', readonly=True)
    quotation_count = fields.Integer('Số báo giá', compute='_compute_doc_counts')
    order_count = fields.Integer('Số PO thực thi', compute='_compute_doc_counts')

    state = fields.Selection([
        ('draft', 'Nháp'),
        ('confirm_requested', 'Chờ duyệt'),
        ('running', 'Đang hiệu lực'),
        ('liquidation_requested', 'Chờ duyệt thanh lý'),
        ('liquidated', 'Đã thanh lý'),
        ('cancelled', 'Đã hủy'),
    ], 'Trạng thái', default='draft', tracking=True)

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.depends('appendix_ids')
    def _compute_appendix_count(self):
        for rec in self:
            rec.appendix_count = len(rec.appendix_ids)

    @api.depends('partner_representative_ids', 'partner_representative_ids.function')
    def _compute_representative_display(self):
        for rec in self:
            reps = rec.partner_representative_ids
            rec.partner_representative = ', '.join(reps.mapped('name')) or False
            # Chức vụ lấy từ field function của contact, ghép theo cùng thứ tự
            rec.partner_position = ', '.join(
                r.function for r in reps if r.function) or False

    @api.depends('sale_order_ids', 'purchase_order_ids',
                 'purchase_order_ids.att_is_execution', 'contract_type')
    def _compute_doc_counts(self):
        for rec in self:
            if rec.contract_type == 'sale':
                # Bán: mọi SO gắn HĐ đều là báo giá (SO thực thi không gắn HĐ)
                rec.quotation_count = len(rec.sale_order_ids)
                rec.order_count = 0
            else:
                # Mua: tách báo giá / PO thực thi bằng cờ att_is_execution
                rec.quotation_count = len(rec.purchase_order_ids.filtered(
                    lambda p: not p.att_is_execution))
                rec.order_count = len(rec.purchase_order_ids.filtered(
                    lambda p: p.att_is_execution))

    @api.depends('appendix_ids.state', 'appendix_ids.effective_date')
    def _compute_active_appendix_id(self):
        for rec in self:
            # Phụ lục đang áp: đã confirm/done, không bị thay thế; ưu tiên
            # ngày hiệu lực mới nhất, cùng ngày thì lấy phụ lục tạo sau
            candidates = rec.appendix_ids.filtered(
                lambda a: a.state in ('confirmed', 'done')
            )
            rec.active_appendix_id = (
                max(candidates, key=lambda a: (a.effective_date or a.create_date.date(), a.id))
                if candidates else False
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _get_partner_short_name(self, partner):
        """Lấy chữ cái đầu mỗi từ của tên đối tác cho số HĐ, bỏ các từ thông dụng."""
        skip_words = {'công', 'ty', 'tnhh', 'cp', 'cổ', 'phần', 'mtv', 'một',
                      'thành', 'viên', 'và', 'the', 'co', 'ltd', 'group'}
        words = (partner.name or '').lower().split()
        initials = ''.join(w[0].upper() for w in words if w not in skip_words)
        return initials[:4] or 'KH'

    def _get_ceo_partners(self):
        ceo_group = self.env.ref('att_quotations_contracts.group_att_contract_ceo',
                                 raise_if_not_found=False)
        if not ceo_group:
            return self.env['res.partner']
        users = self.env['res.users'].search([
            ('group_ids', 'in', [ceo_group.id]),
            ('active', '=', True),
        ])
        return users.mapped('partner_id')

    def _check_ceo_rights(self):
        """Chặn ở tầng server — ẩn nút theo group trong view là chưa đủ (RPC vẫn gọi được)."""
        if not self.env.user.has_group('att_quotations_contracts.group_att_contract_ceo'):
            raise UserError(_('Chỉ Giám đốc mới được thực hiện thao tác này.'))

    def _fill_partner_snapshot(self):
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

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            term_lines = vals.get('term_line_ids') or []
            if not any(cmd[0] in (0, 1, 4) for cmd in term_lines):
                raise UserError(_('Vui lòng thêm ít nhất một điều khoản trước khi tạo hợp đồng.'))

            # CHỐT CHẶN Ở TẦNG CREATE: đối tác đã có HĐNT cùng loại đang hiệu lực
            # → không tạo HĐ mới, chỉ tạo PHỤ LỤC trên HĐ sẵn có. Đặt ở create
            # (không chỉ ở nút) để mọi đường tạo HĐ đều bị kiểm.
            # Trường hợp gia hạn hợp đồng sau này: truyền context
            # attqc_force_new_contract=True để bỏ qua chốt chặn.
            if not self.env.context.get('attqc_force_new_contract'):
                existing = self.search([
                    ('contract_type', '=', vals.get('contract_type')),
                    ('partner_id', '=', vals.get('partner_id')),
                    ('company_id', '=', vals.get('company_id') or self.env.company.id),
                    ('state', '=', 'running'),
                ], limit=1)
                if existing:
                    raise UserError(_(
                        'Đối tác này đã có hợp đồng nguyên tắc đang hiệu lực: %s.\n'
                        'Không tạo hợp đồng mới — hãy tạo PHỤ LỤC giá mới trên '
                        'hợp đồng đó (gắn báo giá vào hợp đồng rồi bấm "Tạo phụ lục").'
                    ) % existing.name)

            if vals.get('name', 'New') == 'New':
                today = fields.Date.context_today(self)
                partner = self.env['res.partner'].browse(vals.get('partner_id'))
                partner_short = self._get_partner_short_name(partner) if partner else 'KH'
                contract_type = vals.get('contract_type', 'sale')
                seq_code = ('attqc.contract.sale' if contract_type == 'sale'
                            else 'attqc.contract.purchase')
                seq_num = self.env['ir.sequence'].next_by_code(seq_code) or '001'
                vals['name'] = (
                    f"{seq_num}/{today.strftime('%d%m%Y')}/HĐNT/TH-{partner_short}/{today.year}"
                )

        records = super().create(vals_list)
        for rec in records:
            rec._fill_partner_snapshot()
            # Gắn ngược HĐ vào chứng từ báo giá gốc để truy vết 2 chiều,
            # và đóng vòng đời báo giá bán: won → contracted
            if rec.source_sale_order_id and not rec.source_sale_order_id.att_contract_id:
                rec.source_sale_order_id.write({
                    'att_contract_id': rec.id,
                    'att_quote_state': 'contracted',
                })
            if rec.source_purchase_order_id and not rec.source_purchase_order_id.att_contract_id:
                winner = rec.source_purchase_order_id
                winner.write({
                    'att_contract_id': rec.id,
                    'att_quote_state': 'contracted',
                })
                # RFQ thắng tạo HĐNT → các báo giá NCC còn lại của CÙNG SO nguồn
                # bị hủy + đánh "Không chọn" (rule nghiệp vụ mua hàng)
                losers = (winner._get_sibling_rfqs() - winner).filtered(
                    lambda r: r.state in ('draft', 'sent'))
                if losers:
                    losers.button_cancel()
                    losers.write({'att_quote_state': 'lost'})
                    for loser in losers:
                        loser.message_post(
                            body=Markup(
                                'Không được chọn — NCC <b>%s</b> đã thắng thầu, '
                                'hợp đồng <b>%s</b>.'
                            ) % (rec.partner_id.name, rec.name),
                            message_type='notification', subtype_xmlid='mail.mt_note')
        return records

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        self._fill_partner_snapshot()

    @api.constrains('effective_date', 'expired_date')
    def _check_dates(self):
        for rec in self:
            if rec.effective_date and rec.expired_date and rec.expired_date <= rec.effective_date:
                raise UserError(_('Ngày hết hạn phải sau ngày hiệu lực.'))

    # ------------------------------------------------------------------
    # Actions — vòng đời hợp đồng
    # ------------------------------------------------------------------
    def action_send_quotation(self):
        """Nút "Gửi bản nháp" — mở popup chọn kênh gửi HĐ cho đối tác.

        Email → mail template kèm PDF; Zalo → gửi file qua att_zalo_connector;
        HĐ mua có thêm kênh Gọi điện trao đổi với NCC.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Gửi bản nháp hợp đồng'),
            'res_model': 'attqc.send.quotation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
                'attqc_allow_call': self.contract_type == 'purchase',
            },
        }

    def action_send_draft_to_partner(self):
        self.ensure_one()
        template = self.env.ref('att_quotations_contracts.email_template_contract_draft',
                                raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=True)
            self.message_post(
                body=Markup('Đã gửi bản nháp hợp đồng <b>%s</b> đến <b>%s</b>.') % (
                    self.name, self.partner_id.name),
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_request_confirm(self):
        """User thường gọi — chuyển chờ duyệt và notify nhóm CEO."""
        for rec in self:
            rec.state = 'confirm_requested'
            rec.message_post(
                body=Markup(
                    '<b>%s</b> yêu cầu xác nhận hiệu lực hợp đồng <b>%s</b> '
                    'với đối tác <b>%s</b>.<br/>Vui lòng xem xét và ký duyệt.'
                ) % (self.env.user.name, rec.name, rec.partner_id.name),
                partner_ids=rec._get_ceo_partners().ids,
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_validate(self):
        """Chỉ CEO — xác nhận hiệu lực, gửi HĐ đã ký cho đối tác."""
        self._check_ceo_rights()
        for rec in self:
            if not rec.effective_date:
                rec.effective_date = fields.Date.today()
            if rec.expired_date and rec.expired_date <= rec.effective_date:
                raise UserError(_('Ngày hết hạn phải sau ngày hiệu lực.'))
            rec.state = 'running'
            # Template tự đính PDF qua report_template_ids — không render tay
            # tránh tạo attachment mồ côi
            template = self.env.ref(
                'att_quotations_contracts.email_template_contract_validated',
                raise_if_not_found=False)
            if template:
                template.send_mail(rec.id, force_send=True)
            rec.message_post(
                body=Markup('<b>%s</b> đã xác nhận hiệu lực hợp đồng <b>%s</b>.') % (
                    self.env.user.name, rec.name),
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_request_liquidation(self):
        for rec in self:
            if not rec.liquidation_reason_id:
                raise UserError(_('Vui lòng chọn lý do thanh lý trước.'))
            rec.liquidation_requested_by = self.env.user.id
            rec.liquidation_requested_date = fields.Datetime.now()
            rec.state = 'liquidation_requested'
            rec.message_post(
                body=Markup(
                    '<b>%s</b> yêu cầu thanh lý hợp đồng <b>%s</b>.<br/>Lý do: %s'
                ) % (self.env.user.name, rec.name, rec.liquidation_reason_id.name),
                partner_ids=rec._get_ceo_partners().ids,
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_approve_liquidation(self):
        self._check_ceo_rights()
        for rec in self:
            rec.state = 'liquidated'
            rec.message_post(
                body=Markup('<b>%s</b> đã duyệt thanh lý hợp đồng <b>%s</b>.') % (
                    self.env.user.name, rec.name),
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_cancel(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Chỉ hủy được hợp đồng ở trạng thái Nháp.'))
        self.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    # ------------------------------------------------------------------
    # Smart buttons
    # ------------------------------------------------------------------
    def action_view_appendix(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Phụ lục hợp đồng'),
            'res_model': 'att.contract.appendix',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {
                'default_contract_id': self.id,
                'default_appendix_type': self.contract_type,
                'default_partner_id': self.partner_id.id,
            },
        }

    def action_create_purchase_order(self):
        """Tạo PO trực tiếp từ HĐNT mua — không bắt buộc đi qua phụ lục.

        KHÔNG đụng state machine native: chỉ prefill một RFQ draft chuẩn,
        user vẫn confirm bằng nút native của purchase.
        - HĐ có phụ lục đang áp → đổ sẵn dòng + giá từ phụ lục (giá bị guard
          cảnh báo nếu sửa lệch — xem purchase_order.py)
        - HĐ chưa có phụ lục → PO trống, user tự nhập dòng; khuyến nghị
          bổ sung phụ lục sau để chốt giá chính thức.
        """
        self.ensure_one()
        if self.contract_type != 'purchase':
            raise UserError(_('Chỉ hợp đồng mua mới tạo PO trực tiếp.'))
        if self.state != 'running':
            raise UserError(_('Chỉ hợp đồng đang hiệu lực mới được tạo PO.'))
        appendix = self.active_appendix_id
        order_lines = []
        if appendix:
            order_lines = [(0, 0, line._prepare_purchase_order_line_vals())
                           for line in appendix._get_mapping_lines()]
        purchase_order = self.env['purchase.order'].create({
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'att_contract_id': self.id,
            'att_appendix_id': appendix.id if appendix else False,
            # Đánh dấu đơn thực thi để không lẫn vào màn RFQ mời thầu native
            'att_is_execution': True,
            'order_line': order_lines,
        })
        if not appendix:
            purchase_order.message_post(
                body=Markup(
                    'PO tạo trực tiếp từ HĐ <b>%s</b> (chưa có phụ lục giá — '
                    'giá nhập tay, nên bổ sung phụ lục để chốt giá chính thức).'
                ) % self.name,
                message_type='notification', subtype_xmlid='mail.mt_note')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'res_id': purchase_order.id,
        }

    def action_view_quotations(self):
        """Xem các BÁO GIÁ thuộc HĐ này (SO draft phía bán / RFQ phía mua)."""
        self.ensure_one()
        if self.contract_type == 'sale':
            return {
                'type': 'ir.actions.act_window',
                'name': _('Báo giá của %s') % self.name,
                'res_model': 'sale.order',
                'view_mode': 'list,form',
                'domain': [('att_contract_id', '=', self.id)],
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Báo giá NCC của %s') % self.name,
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('att_contract_id', '=', self.id),
                       ('att_is_execution', '=', False)],
        }

    def action_view_orders(self):
        """Xem PO thực thi — CHỈ có nghĩa với HĐ mua (PO tạo được từ HĐNT/phụ lục).
        HĐ bán không có đơn thực thi trực tiếp: SO thực thi thuộc phụ lục."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('PO thực thi của %s') % self.name,
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('att_contract_id', '=', self.id),
                       ('att_is_execution', '=', True)],
        }

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_notify_expiring_contracts(self, days=30):
        """Chạy hàng ngày: nhắc các HĐ đang hiệu lực sẽ hết hạn trong `days` ngày tới."""
        template = self.env.ref(
            'att_quotations_contracts.email_template_contract_expiring',
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
                    rec.name, rec.expired_date),
                message_type='notification', subtype_xmlid='mail.mt_note')


class ContractTermLine(models.Model):
    """Điều khoản trong hợp đồng — số 'Điều X' tự đánh theo vị trí dòng."""
    _name = 'att.contract.term.line'
    _description = 'Điều khoản hợp đồng'
    _order = 'sequence, id'

    contract_id = fields.Many2one('att.contract', required=True, ondelete='cascade')
    sequence = fields.Integer('Thứ tự', default=10)
    term_type = fields.Selection([
        ('sale', 'Bán'),
        ('purchase', 'Mua'),
        ('both', 'Chung'),
    ], string='Loại', default='both')
    title = fields.Char('Tiêu đề điều', required=True)
    # Số điều tự đánh theo vị trí — kéo thả đổi thứ tự là số cập nhật, PDF in theo số này
    display_title = fields.Char('Số điều', compute='_compute_display_title')
    content = fields.Html('Nội dung')
    note = fields.Text('Ghi chú')
    is_fixed = fields.Boolean('Cố định', default=False)
    clause_id = fields.Many2one('att.contract.clause', string='Điều khoản', ondelete='set null')

    @api.model
    def _strip_dieu_prefix(self, title):
        """Bỏ tiền tố 'Điều <số>:' nếu user/dữ liệu cũ vẫn gõ kèm số."""
        if not title:
            return title
        return re.sub(r'^\s*điều\s*\d+\s*[:.\-–]?\s*', '', title, flags=re.IGNORECASE).strip()

    @api.depends('title', 'sequence', 'contract_id.term_line_ids',
                 'contract_id.term_line_ids.sequence')
    def _compute_display_title(self):
        for line in self:
            # Vị trí dòng trong danh sách (đã sắp theo sequence, id nhờ _order)
            # chính là số điều
            number = 1
            for idx, sibling in enumerate(line.contract_id.term_line_ids, start=1):
                if sibling == line:
                    number = idx
                    break
            clean_title = self._strip_dieu_prefix(line.title)
            if clean_title:
                line.display_title = _('Điều %(num)d: %(title)s', num=number, title=clean_title)
            else:
                line.display_title = _('Điều %d') % number

    @api.onchange('clause_id')
    def _onchange_clause_id(self):
        if not self.clause_id:
            return
        clause = self.clause_id
        existing = self.contract_id.term_line_ids.filtered(
            lambda l: l.clause_id == clause and l != self)
        if existing:
            self.clause_id = False
            return {
                'warning': {
                    'title': _('Trùng điều khoản'),
                    'message': _('Điều khoản "%s" đã được thêm rồi.') % clause.name,
                }
            }
        self.title = self._strip_dieu_prefix(clause.title)
        self.content = clause.content
        self.is_fixed = clause.is_fixed
        self.term_type = clause.clause_type

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('clause_id') and not vals.get('title'):
                clause = self.env['att.contract.clause'].browse(vals['clause_id'])
                vals['title'] = self._strip_dieu_prefix(clause.title)
                if not vals.get('content'):
                    vals['content'] = clause.content
                if 'is_fixed' not in vals:
                    vals['is_fixed'] = clause.is_fixed
            elif vals.get('title'):
                # User gõ tay "Điều 5: ..." cũng bỏ số để không lệch số tự động
                vals['title'] = self._strip_dieu_prefix(vals['title'])
        return super().create(vals_list)

    def write(self, vals):
        for rec in self:
            if rec.is_fixed and not self.env.context.get('skip_fixed_check'):
                # Chặn cả việc tắt cờ is_fixed — không cho bỏ tick rồi sửa (lách luật)
                blocked = {'title', 'content', 'is_fixed'}
                if blocked.intersection(vals.keys()):
                    raise UserError(_('Không được sửa điều khoản cố định.'))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.is_fixed and not self.env.context.get('skip_fixed_check'):
                raise UserError(_('Không được xóa điều khoản cố định.'))
        return super().unlink()
