"""FLOW BÁO GIÁ BÁN — vòng đời duyệt giá của Trang Huy trên sale.order.
    draft ─gủi duyệt─> pending ──duyệt──> approved ──KH chốt──> won ──HĐNT──> contracted
      ↑                 │
      └────trả về───────┘
"""


from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging


_logger = logging.getLogger(__name__)

APPROVAL_RANK = {'none': 0, 'manager': 1, 'ceo': 2 }
ATT_QUOTATION_MANAGER_STATES = ('pending', 'approved', 'won')
ATT_QUOTATION_ADMIN_STATES = ('contracted', 'expired')
ATT_QUOTATION_LOCK_EXEMPT_FIELDS = {
    'att_quote_state', 'att_contract_id',
    'message_follower_ids', 'message_ids', 'activity_ids',
}


class SaleOrder(models.Model):
    """
    File này kế thừa sale.order nhưng chỉ đê xử lý flow cho báo giá sale.
    """
    _inherit = 'sale.order'


    att_quote_state = fields.Selection([
        ('draft', 'Nháp'),
        ('pending', 'Chờ duyệt giá'),
        ('approved', 'Đã duyệt giá'),
        ('won', 'KH đã chốt'),
        ('contracted','Đã tạo HĐNT'),
        ('expired', 'Hết hạn'),
    ],'Trạng thái báo giá ', default='draft', tracking=True, index=True, copy=False)
    att_approval_level = fields.Selection([
        ('none', 'V tự duyệt'),
        ('manager','Quản lý duyệt'),
        ('ceo','Giám đốc duyệt'),
    ],'Cấp duyệt giá', readonly=True, tracking=True, index=True, copy=False)
    att_price_history_note = fields.Text('So sánh giá lịch sử', readonly=True, copy=False)
    # 1 field DUY NHẤT cho quan hệ báo giá <-> HĐNT — cho chọn tay (KH đã có
    # HĐNT đang chạy thì gán ngay từ đầu), gợi ý sẵn khi chọn đối tác qua
    # onchange (không phải compute — tránh field vừa compute vừa cho sửa tay).
    # Nếu để trống, khi báo giá được chốt thành HĐNT/rebase, code
    # (att.contract.create() / _att_rebase_price_source) tự ghi ngược field
    # này — không cần thêm field thứ 2 chỉ để hiển thị.
    att_contract_id = fields.Many2one(
        'att.contract', 'Hợp đồng nguyên tắc', copy=False, tracking=True,
        domain="[('partner_id', '=', partner_id), ('contract_type', '=', 'sale'), "
               "('state', '=', 'running')]")
    att_can_edit = fields.Boolean('Được sửa nội dung', compute='_compute_att_can_edit')

    @api.onchange('partner_id')
    def _onchange_partner_id_att_contract(self):
        """Gợi ý sẵn HĐNT đang chạy của đối tác vừa chọn — user vẫn sửa/xoá
        được tay nếu muốn tạo HĐ mới thay vì dùng HĐ gợi ý."""
        for rec in self:
            if rec.att_is_execution:
                continue
            rec.att_contract_id = self.env['att.contract']._get_running_contract(
                rec.partner_id, 'sale', rec.company_id) if rec.partner_id else False

    @api.depends('att_quote_state')
    def _compute_att_can_edit(self):
        is_manager = self.env.user.has_group('att_contract_management.group_att_qc_manager')
        is_admin = self.env.user.has_group('base.group_system')
        for rec in self:
            if rec.att_quote_state in ATT_QUOTATION_ADMIN_STATES:
                rec.att_can_edit = is_admin
            elif rec.att_quote_state in ATT_QUOTATION_MANAGER_STATES:
                rec.att_can_edit = is_manager
            else:
                rec.att_can_edit = True


    def write(self, vals):
        if set(vals.keys()) - ATT_QUOTATION_LOCK_EXEMPT_FIELDS:
            for rec in self.filtered( lambda r: not r.att_is_execution):
                if (rec.att_quote_state in ATT_QUOTATION_ADMIN_STATES and not self.env.user.has_group('base.group_system')):
                    raise UserError(_('Báo giá %s đã tạo HĐNT - chỉ Admin hệ thống mới sửa được nội dung.') % rec.name )
                if (rec.att_quote_state in ATT_QUOTATION_MANAGER_STATES and not self.env.user.has_group('att_contract_management.group_att_qc_manager') ):
                    raise UserError(_('Báo giá %s đang chờ/đã duyệt giá - chỉ quản lý trở lên mới sửa được nôi dung.') % rec.name)
        return super().write(vals)

    #actions
    @api.model
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name','/') in ('/', False) and not vals.get('att_appendix_id'):
                name = self.env['ir.sequence'].next_by_code('att.sale.quotation')
                if name:
                    vals['name'] = name
        return super().create(vals_list)

    def action_att_request_approval(self):
        for rec in self:
            if rec.att_quote_state != 'draft':
                raise UserError(_('Chỉ xin duyệt báo giá khi ở trạng thái nháp.'))
            if not rec.order_line.filtered(lambda l: not l.display_type and l.product_id):
                raise UserError(_('Vui lòng nhập ít nhất một dòng báo giá.'))

            rec.att_quote_state = 'pending'
            rec.message_post(
                body=Markup(
                '<b>%s</b> Gửi duyệt báo <b>%s</b> - KH - <b>%s</b>. '
                ': <b>%s %s </b>'
            ) % (self.env.user.name, rec.name, rec.partner_id.name, f'{rec.amount_total:,.0f}', rec.currency_id.name),
                partner_ids=rec._get_group_partners('att_contract_management.group_att_qc_manager').ids,
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )


    def _get_group_partners(self, group_xmlid):
        """Partner của các user trong group này - để tag Notify trong chatter"""

        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            return self.env['res.partner']
        return self.env['res.users'].search([
            ('group_ids','in',[group.id]),
            ('active','=', True),
        ]).mapped('partner_id')


    #Duyệt và trả về quản lý
    def _check_manager(self):
        if not self.env.user.has_group('att_contract_management.group_att_qc_manager'):
            raise UserError(_('Chỉ quản lý trở lên mới được thao tác này.'))


    def action_att_approve(self):
        self._check_manager()
        for rec in self:
            if rec.att_quote_state != 'pending':
                raise UserError(_('Chỉ duyệt báo giá đang chờ duyệt.'))
            rec.att_quote_state = 'approved'
            rec.message_post(
                body=Markup('<b>%s</b> đã duyệt báo giá <b>%s</b> - KH - <b>%s</b>. ') % (self.env.user.name, rec.name, rec.partner_id.name),
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )


    def action_att_refuse(self):
        self._check_manager()
        for rec in self:
            if rec.att_quote_state != 'pending':
                raise UserError(_('Chỉ trả về báo giá đang chờ duyệt.'))
            rec.att_quote_state = 'draft'
            rec.message_post(
                body=Markup('<b>%s</b> đã trả về báo giá <b>%s</b> - KH - <b>%s</b>. ') % (self.env.user.name, rec.name, rec.partner_id.name),
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )


    #KH chốt
    def action_att_mark_won(self):
        for rec in self:
            if rec.att_quote_state != 'approved':
                raise UserError(_('Báo giá đã duyệt mới ghi nhận KH chốt.'))
            rec.att_quote_state = 'won'
            rec.message_post(
                body=Markup('<b>%s</b> đã ghi nhận <b>%s</b> - KH - <b>%s</b> chốt. ') % (self.env.user.name, rec.name, rec.partner_id.name),
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )


    def _th_check_cost_lines_confirmed(self):
        """Hook — module này (core, không biết gì về vận tải/chi phí) mặc
        định không chặn gì. att_transport_orders override để bắt buộc mọi
        dòng chi phí (BOT...) của báo giá phải CHỐT xong bên chịu trước khi
        được tạo HĐNT — tránh phát sinh chi phí "trôi nổi" chưa ai quyết
        khách hay Trang Huy trả mà đã lên hợp đồng chính thức."""
        self.ensure_one()
        return True

    def action_create_att_contract(self):
        self.ensure_one()
        if self.att_quote_state != 'won':
            raise UserError(_('Chỉ báo giá "KH đã chổt" mới tạo được HĐNT.'))
        self._th_check_cost_lines_confirmed()
        # Ưu tiên HĐ đã chọn tay trên chính báo giá (field att_contract_id) —
        # fallback tự dò theo đối tác nếu người dùng để trống (VD tạo qua API).
        existing = self.att_contract_id or self.env['att.contract']._get_running_contract(
            self.partner_id, 'sale', self.company_id)
        if existing:
            # KH đã có HĐNT đang chạy — KHÔNG tạo HĐ mới (không ký lại HĐ mỗi
            # lần đổi giá). Tự động chuyển báo giá này thành căn cứ giá hiện
            # hành của HĐ đó (KH tái đàm phán giá) + huỷ báo giá cũ còn mở.
            existing._att_rebase_price_source(self)
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'att.contract',
                'view_mode': 'form',
                'res_id': existing.id,
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo hợp đồng nguyên tắc'),
            'res_model': 'att.contract',
            'view_mode': 'form',
            'context': {
                'default_contract_type': 'sale',
                'default_partner_id': self.partner_id.id,
                'default_source_sale_order_id': self.id,
                'default_company_id': self.company_id.id,
            },

        }