import base64
import logging
from odoo.tools import html_escape
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)

class Contract(models.Model):
    _name = 'att.contract'
    _description = 'Hợp đồng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char('Số hợp đồng', required=True, copy=False, readonly=True, default='New', tracking=True, index=True)
    contract_type = fields.Selection([
        ('sale','Hợp đồng bán'),
        ('purchase', 'Hợp đồng mua')
    ],string='Loại hợp đồng', required=True, tracking=True, index=True)
    source_quotation_id = fields.Many2one('att.quotation.request', 'Yêu cầu báo giá gốc', readonly=True, copy=False, tracking=True, ondelete='restrict')
    sale_order_id = fields.Many2one('sale.order', 'Chứng từ gốc', readonly=True, copy=False, tracking=True, help='Dùng khi hợp đồng mua phát sinh từ một SO đã xác nhận.')
    partner_id = fields.Many2one('res.partner','Đối tác', required=True, copy=True, tracking=True,)
    user_id = fields.Many2one('res.users', 'Người phụ trách', default=lambda self: self.env.user, tracking=True)
    company_id = fields.Many2one('res.company', 'Công ty', required=True, tracking=True, default=lambda self: self.env.company , index=True)
    currency_id = fields.Many2one('res.currency','Tiền tệ',default=lambda self: self.env.company.currency_id,)
    #tg hd
    # date_signed = fields.Date('Ngày ký', tracking=True)
    effective_date = fields.Date('Ngày hiệu lực',tracking=True,readonly=True,states={'draft': [('readonly', False)]},help='Tự điền khi xác nhận HĐ nếu để trống',)
    expired_date = fields.Date('Ngày hết hạn', tracking=True)
    #snapshot tt khách
    partner_address = fields.Char('Địa chỉ đối tác', tracking=True)
    partner_phone = fields.Char('SĐT đối tác', tracking=True)
    partner_email = fields.Char('Email đối tác', tracking=True)
    partner_tax_code = fields.Char('Mã số thuế đối tác', tracking=True)
    partner_bank_account = fields.Char('Tài khoản ngân hàng đối tác', tracking=True)
    partner_representative = fields.Char('Người đại diện đối tác',tracking=True)
    partner_position = fields.Char('Chức vụ người đại diện', tracking=True)
    #payment terms
    payment_term_id = fields.Many2one('account.payment.term','Điều khoản thanh toán', tracking=True,)
    payment_method = fields.Selection([
        ('bank_transfer','Chuyển khoản'),
        ('cash','Tiền mặt'),
        ('other','Khác')
    ],'Hình thức thanh toán', default='bank_transfer', tracking=True)
    payment_deadline_days = fields.Integer(string='Thời hạn thanh toán (ngày)',default=15,tracking=True,)
    payment_document_note = fields.Text('Hồ sơ thanh toán hợp lệ', default='Bảng kê cước vận chuyển; Hóa đơn tài chính hợp lệ.')
    payment_note = fields.Text('Ghi chú thanh toán')
    late_payment_penalty_note = fields.Text('Phạt chậm thanh toán')
    waiting_fee_note = fields.Text('Phí lưu ca/chờ hàng')
    #terms flexible
    term_line_ids = fields.One2many('att.contract.term.line', 'contract_id', 'Điều khoản hợp đồng', copy=True)
    #thanh ly
    liquidation_reason_id = fields.Many2one(
        'att.contract.liquidation.reason',
        string='Lý do thanh lý',
        tracking=True,
    )
    liquidation_note = fields.Text('Ghi chú thanh lý', tracking=True)
    liquidation_requested_by = fields.Many2one(
        'res.users',
        string='Người yêu cầu thanh lý',
        readonly=True,
    )
    liquidation_requested_date = fields.Datetime(
        string='Ngày yêu cầu thanh lý',
        readonly=True,
    )
    #appendix
    appendix_ids = fields.One2many('att.contract.appendix', 'contract_id','Phụ lục', readonly=True)
    appendix_count = fields.Integer('Số phụ lục',compute='_compute_appendix_count',)
    #states
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('confirm_requested', 'Chờ duyệt'),
        ('running', 'Đang hiệu lực'),
        ('liquidation_requested', 'Chờ duyệt thanh lý'),
        ('liquidated', 'Đã thanh lý'),
        ('cancelled', 'Đã hủy'),
    ], 'Trạng thái', default='draft', tracking=True)



    #compute
    @api.depends('appendix_ids')
    def _compute_appendix_count(self):
        for rec in self:
            rec.appendix_count = len(rec.appendix_ids)


    def _get_partner_short_name(self, partner):
        """Lấy chữ cái đầu mỗi từ của tên đối tác, bỏ các từ thông thường"""
        skip_words = {'công', 'ty', 'tnhh', 'cp', 'cổ', 'phần', 'mtv', 'một', 'thành', 'viên', 'và', 'the', 'co', 'ltd',
                      'group'}
        words = partner.name.lower().split()
        initials = ''.join(w[0].upper() for w in words if w not in skip_words)
        return initials[:4] or 'KH'


    @api.model
    def create(self, vals_list):
        for vals in vals_list:
            term_lines = vals.get('term_line_ids', [])
            if not any(cmd[0] in (0, 1, 4) for cmd in term_lines):
                raise UserError(_('Vui lòng thêm ít nhất một điều khoản trước khi tạo hợp đồng.'))

            if vals.get('name', 'New') == 'New':
                from datetime import date
                today = date.today()
                dd = today.strftime('%d')
                mm = today.strftime('%m')
                yyyy = today.strftime('%Y')

                partner = self.env['res.partner'].browse(vals.get('partner_id'))
                partner_short = self._get_partner_short_name(partner) if partner else 'KH'

                contract_type = vals.get('contract_type', 'sale')
                seq_code = 'att.contract.sale' if contract_type == 'sale' else 'att.contract.purchase'
                seq_num = self.env['ir.sequence'].next_by_code(seq_code) or '001'

                vals['name'] = f"{seq_num}/{dd}{mm}{yyyy}/HĐNT/TH-{partner_short}/{yyyy}"

        records = super().create(vals_list)
        for rec in records:
            rec._fill_partner_snapshot()
            if rec.source_quotation_id and not rec.source_quotation_id.contract_id:
                rec.source_quotation_id.sudo().write({'contract_id': rec.id})
        return records

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        for rec in self:
            rec._fill_partner_snapshot()


    def _fill_partner_snapshot(self):
        for rec in self:
            partner = rec.partner_id
            if not partner:
                continue
            address_parts = [
                partner.street,
                partner.street2,
                partner.city,
                partner.state_id.name if partner.state_id else False,
                partner.country_id.name if partner.country_id else False,
            ]
            rec.partner_address = ', '.join([p for p in address_parts if p])
            rec.partner_phone = partner.phone
            rec.partner_email = partner.email
            rec.partner_tax_code = partner.vat
            bank = partner.bank_ids[:1]
            rec.partner_bank_account = bank.acc_number if bank else False


    #action button
    @api.constrains('effective_date', 'expired_date')
    def _check_dates(self):
        for rec in self:
            if rec.effective_date and rec.expired_date:
                if rec.expired_date <= rec.effective_date:
                    raise UserError(_('Ngày hết hạn phải sau ngày hiệu lực.'))

    def action_send_draft_to_partner(self):
        self.ensure_one()
        template = self.env.ref(
            'att_quotation_contract.email_template_contract_draft',
            raise_if_not_found=False,
        )
        if template:
            template.send_mail(self.id, force_send=True)
        else:
            ctx = {
                'default_model': 'att.contract',
                'default_res_ids': [self.id],
                'default_composition_mode': 'comment',
                'default_partner_ids': [self.partner_id.id],
            }
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'mail.compose.message',
                'view_mode': 'form',
                'target': 'new',
                'context': ctx,
            }

    def _get_ceo_partners(self):
        ceo_group = self.env.ref(
            'att_quotation_contract.group_att_contract_ceo',
            raise_if_not_found=False,
        )
        if not ceo_group:
            return self.env['res.partner']
        users = self.env['res.users'].search([
            ('group_ids', 'in', [ceo_group.id]),
            ('active', '=', True),
        ])
        return users.mapped('partner_id')


    def action_request_confirm(self):
        """User thường gọi — gửi mail CEO."""
        for rec in self:
            if rec.expired_date and rec.effective_date and rec.expired_date <= rec.effective_date:
                raise UserError(_('Ngày hết hạn phải sau ngày hiệu lực.'))
            rec.state = 'confirm_requested'
            partner_ids = self._get_ceo_partners().ids
            rec.message_post(
                body=Markup(
                    '<b>%s</b> yêu cầu xác nhận hiệu lực hợp đồng <b>%s</b> với đối tác <b>%s</b>.<br/>'
                    'Vui lòng vào xem xét và ký duyệt.'
                ) % (
                         self.env.user.name,
                         rec.name,
                         rec.partner_id.name,
                     ),
                partner_ids=partner_ids,
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )

    def action_validate(self):
        for rec in self:
            if not rec.effective_date:
                rec.effective_date = fields.Date.today()
            if rec.expired_date and rec.effective_date and rec.expired_date <= rec.effective_date:
                raise UserError(_('Ngày hết hạn phải sau ngày hiệu lực.'))
            rec.state = 'running'

            pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(
                'att_quotation_contract.report_att_contract',
                res_ids=[rec.id],
            )
            attachment = self.env['ir.attachment'].create({
                'name': f'HDDT_{rec.name}.pdf',
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': rec._name,
                'res_id': rec.id,
                'mimetype': 'application/pdf',
            })

            template = self.env.ref(
                'att_quotation_contract.email_template_contract_validated',
                raise_if_not_found=False,
            )
            if template:
                template.send_mail(rec.id, force_send=True)

            # Chỉ log nội bộ kèm file PDF có chữ ký — không duplicate với email
            # rec.message_post(
            #     body=Markup(
            #         '<b>%s</b> đã xác nhận hiệu lực hợp đồng <b>%s</b>.<br/>'
            #         'File HĐĐT đính kèm bên dưới.'
            #     ) % (self.env.user.name, rec.name),
            #     attachment_ids=[attachment.id],
            #     message_type='notification',
            #     subtype_xmlid='mail.mt_note',
            # )


    def action_request_liquidation(self):
        for rec in self:
            if not rec.liquidation_reason_id:
                raise UserError(_('Vui lòng chọn lý do thanh lý trước.'))
            rec.liquidation_requested_by = self.env.user.id
            rec.liquidation_requested_date = fields.Datetime.now()
            rec.state = 'liquidation_requested'
            # Notify CEO qua chatter
            partner_ids = self._get_ceo_partners().ids
            rec.message_post(
                body=Markup(
                    '<b>%s</b> yêu cầu thanh lý hợp đồng <b>%s</b>.<br/>'
                    'Lý do: %s<br/>'
                    '<a href="/odoo/att-contract/%s">Xem hợp đồng</a>'
                ) % (
                         self.env.user.name,
                         rec.name,
                         rec.liquidation_reason_id.name,
                         rec.id,
                     ),
                partner_ids=partner_ids,
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )


    def action_approve_liquidation(self):
        """Chỉ CEO mới được gọi."""
        ceo_group = self.env.ref(
            'att_quotation_contract.group_att_contract_ceo',
            raise_if_not_found=False,
        )
        if ceo_group and self.env.user not in ceo_group.users:
            raise UserError(_('Chỉ Giám đốc mới được duyệt thanh lý.'))

        for rec in self:
            rec.state = 'liquidated'
            rec.message_post(
                body=Markup(
                    '<b>%s</b> đã duyệt thanh lý hợp đồng <b>%s</b>.'
                ) % (self.env.user.name, rec.name),
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )


    def action_cancel(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Chỉ hủy được hợp đồng ở trạng thái Nháp.'))
        self.write({'state': 'cancelled'})


    def action_reset_to_draft(self):
        self.write({'state': 'draft'})


    def action_view_appendix(self):
        self.ensure_one()

        return{
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




class ContractTermLine(models.Model):
    _name = 'att.contract.term.line'
    _description = 'Điều khoản hợp đồng'
    _order = 'sequence, id'

    contract_id = fields.Many2one('att.contract', required=True, ondelete='cascade')
    source_clause_id = fields.Many2one(
        'att.contract.clause',
        string='Từ thư viện',
        ondelete='set null',
        copy=False,
    )
    sequence = fields.Integer('Thứ tự', default=10)
    term_type = fields.Selection([
        ('sale', 'Bán'),
        ('purchase', 'Mua'),
        ('both', 'Chung'),
    ], string='Loại', default='both')
    title = fields.Char('Tiêu đề điều', required=True)
    content = fields.Html('Nội dung')
    note = fields.Text('Ghi chú')
    is_fixed = fields.Boolean('Cố định', default=False)
    clause_id = fields.Many2one(
        'att.contract.clause',
        string='Điều khoản',
        ondelete='set null',
    )


    @api.onchange('clause_id')
    def _onchange_clause_id(self):
        if not self.clause_id:
            return
        clause = self.clause_id
        existing = self.contract_id.term_line_ids.filtered(
            lambda l: l.clause_id == clause and l != self
        )
        if existing:
            self.clause_id = False
            return {
                'warning': {
                    'title': 'Trùng điều khoản',
                    'message': f'Điều khoản "{clause.name}" đã được thêm rồi.',
                }
            }
        self.title = clause.title
        self.content = clause.content
        self.is_fixed = clause.is_fixed
        self.term_type = clause.clause_type

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('clause_id') and not vals.get('title'):
                clause = self.env['att.contract.clause'].browse(vals['clause_id'])
                vals['title'] = clause.title
                if not vals.get('content'):
                    vals['content'] = clause.content
                if 'is_fixed' not in vals:
                    vals['is_fixed'] = clause.is_fixed
        return super().create(vals_list)


    def write(self, vals):
        for rec in self:
            if rec.is_fixed and not self.env.context.get('skip_fixed_check'):
                block = {'title', 'content'}
                if block.intersection(vals.keys()):
                    raise UserError(_('Không được sửa điều khoản cố định.'))
        return super().write(vals)


    def unlink(self):
        for rec in self:
            if rec.is_fixed:
                raise UserError(_('Không được xóa điều khoản cố định.'))
        return super().unlink()