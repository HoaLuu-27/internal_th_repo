# -*- coding: utf-8 -*-
"""PHỤ LỤC HỢP ĐỒNG — nguồn giá của đơn thực thi.
Vòng đời: draft → confirmed → done | cancelled
1 hợp đồng có thể có NHIỀU phụ lục cùng hiệu lực song song (mỗi phụ lục gắn
với 1 báo giá nguồn riêng qua source_sale_order_id) — xác nhận phụ lục mới
KHÔNG thay thế/vô hiệu hoá phụ lục khác của cùng hợp đồng.
"""
import logging
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


ATT_APPENDIX_LOCK_EXEMPT_FIELDS = {
    'state', 'message_follower_ids', 'message_ids', 'activity_ids',
}

class AttContractAppendix(models.Model):
    _name = 'att.contract.appendix'
    _description = 'Phụ lục hợp đồng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char('Số phụ lục', default='/', copy=False, readonly=True)
    contract_id = fields.Many2one(
        'att.contract', 'Hợp đồng', required=True, index=True,
        ondelete='restrict',            # HĐ có phụ lục thì không xoá được HĐ
        domain="[('state', '=', 'running')]")
    appendix_type = fields.Selection(related='contract_id.contract_type',
                                     store=True, string='Loại')
    partner_id = fields.Many2one(related='contract_id.partner_id',
                                 store=True, string='Đối tác')
    company_id = fields.Many2one(related='contract_id.company_id', store=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)

    effective_date = fields.Date('Giá hiệu lực từ', required=True,
                                 default=fields.Date.context_today)
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('confirmed', 'Đã xác nhận'),
        ('done', 'Đã sinh đơn'),
        ('superseded', 'Bị thay thế'),
        ('cancelled', 'Đã huỷ'),
    ], default='draft', tracking=True, index=True, copy=False)

    source_sale_order_id = fields.Many2one(
        'sale.order', 'SO báo giá nguồn', copy=False,
        domain="[('partner_id', '=', partner_id),"
               " ('att_quote_state', 'in', ('won', 'contracted'))]")

    # ---- Người ký — mặc định kéo từ HĐ (onchange), sửa được từng PL ----
    partner_signer_ids = fields.Many2many(
        'res.partner', 'att_appendix_partner_signer_rel',
        'appendix_id', 'partner_id', string='Người ký Bên A',
        domain="[('id', 'child_of', partner_id)]")
    company_signer_ids = fields.Many2many(
        'res.partner', 'att_appendix_company_signer_rel',
        'appendix_id', 'partner_id', string='Người ký Bên B',
        domain="[('user_ids', '!=', False)]")

    appendix_line_ids = fields.One2many('att.contract.appendix.line',
                                        'appendix_id', 'Dòng phụ lục',
                                        copy=True)
    amount_untaxed = fields.Monetary('Tổng chưa thuế', store=True,
                                     compute='_compute_amounts',
                                     currency_field='currency_id')
    amount_total = fields.Monetary('Tổng cộng', store=True,
                                   compute='_compute_amounts',
                                   currency_field='currency_id')
    att_can_edit = fields.Boolean('Được sửa nội dung', compute='_compute_att_can_edit')



    @api.depends('state')
    def _compute_att_can_edit(self):
        is_admin = self.env.user.has_group('base.group_system')
        for rec in self:
            rec.att_can_edit = True if rec.state == 'draft' else is_admin


    def write(self, vals):
        if set(vals.keys()) - ATT_APPENDIX_LOCK_EXEMPT_FIELDS:
            for rec in self:
                if rec.state != 'draft' and not self.env.user.has_group('base.group_system'):
                    raise UserError(_(
                        'Phụ lục %s không còn ở trạng thái Nháp — chỉ Admin hệ '
                        'thống mới sửa được nội dung.') % rec.name)
        return super().write(vals)


    @api.depends('appendix_line_ids.price_subtotal',
                 'appendix_line_ids.price_total')
    def _compute_amounts(self):
        for rec in self:
            lines = rec.appendix_line_ids.filtered(lambda l: not l.display_type)
            rec.amount_untaxed = sum(lines.mapped('price_subtotal'))
            rec.amount_total = sum(lines.mapped('price_total'))


    @api.onchange('contract_id')
    def _onchange_contract_signers(self):
        """Chọn HĐ → kéo bộ người ký + báo giá nguồn hiện tại của HĐ xuống
        làm mặc định. Báo giá nguồn có thể đã đổi so với lúc HĐ mới tạo nếu
        KH tái đàm phán giá (xem att.contract._att_rebase_price_source)."""
        for rec in self:
            if rec.contract_id:
                rec.partner_signer_ids = rec.contract_id.partner_signer_ids
                rec.company_signer_ids = rec.contract_id.company_signer_ids
                if rec.appendix_type == 'sale' and rec.contract_id.source_sale_order_id:
                    rec.source_sale_order_id = rec.contract_id.source_sale_order_id


    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') in ('/', False):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'att.contract.appendix') or '/'
        return super().create(vals_list)


    @api.model
    def _att_get_default_product(self, order_type='sale'):
        """Product mặc định cho đơn thực thi. Kế toán cấu hình TK/VAT
        trên product này MỘT LẦN, mọi đơn dùng chung."""
        xmlid = ('att_contract_management.product_service_freight_sale'
                 if order_type == 'sale'
                 else 'att_contract_management.product_service_freight_purchase')
        return self.env.ref(xmlid)



    def _prepare_appendix_line_vals(self, sol):
        """Map 1 dòng SO báo giá nguồn → vals dòng phụ lục."""
        self.ensure_one()
        if sol.display_type:
            return {'display_type': sol.display_type, 'name': sol.name}
        return {
            'name': sol.name,
            'product_id': sol.product_id.id,
            'uom_id': sol.product_uom_id.id,
            'quantity': sol.product_uom_qty,
            'price_unit': sol.price_unit,
            'tax_ids': [fields.Command.set(sol.tax_ids.ids)],
        }


    def action_load_source_lines(self):
        """Nạp dòng từ SO báo giá nguồn — thay cho nhập tay 3 lần (BG→PL→đơn).
        Xoá dòng cũ nạp lại từ đầu — phụ lục nháp là bản nháp đúng nghĩa."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Chỉ nạp dòng khi phụ lục còn Nháp.'))
        source = self.source_sale_order_id
        if not source:
            raise UserError(_('Vui lòng chọn SO báo giá nguồn trước.'))
        if source.validity_date and source.validity_date < fields.Date.today():
            raise UserError(_(
                'Báo giá %(bg)s hết hiệu lực từ %(ngay)s — giá không còn cam kết. '
                'Cập nhật hạn hiệu lực trước khi nạp.',
                bg=source.name, ngay=source.validity_date.strftime('%d/%m/%Y')))
        commands = [fields.Command.clear()]
        commands += [fields.Command.create(self._prepare_appendix_line_vals(sol))
                     for sol in source.order_line]
        self.appendix_line_ids = commands


    def action_confirm(self):
        """Xác nhận phụ lục — KHÔNG tự thay thế phụ lục khác của cùng HĐ.
        1 hợp đồng có thể có nhiều phụ lục cùng hiệu lực song song, mỗi phụ
        lục độc lập theo báo giá nguồn (source_sale_order_id) riêng của nó."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Chỉ xác nhận được phụ lục Nháp.'))
            if rec.contract_id.state != 'running':
                raise UserError(_('Hợp đồng %s chưa/không còn hiệu lực.')
                                % rec.contract_id.name)
            if not rec.appendix_line_ids.filtered(
                    lambda l: not l.display_type and l.price_unit):
                raise UserError(_('Phụ lục cần ít nhất một dòng có giá.'))
            rec.state = 'confirmed'


    def action_cancel(self):
        for rec in self:
            if rec.state == 'superseded':
                raise UserError(_('Phụ lục đã bị thay thế — không thao tác nữa.'))
            rec.state = 'cancelled'


    def action_create_sale_order(self):
        """Sinh SO thực thi (NHÁP) — giá luôn từ phụ lục, user rà số lượng
        thực tế từng đợt rồi tự confirm. 1 phụ lục sinh được NHIỀU SO
        (done vẫn sinh tiếp — done chỉ đánh dấu 'đã dùng')."""
        self.ensure_one()
        if self.appendix_type != 'sale':
            raise UserError(_('Chỉ phụ lục bán mới tạo đơn bán hàng.'))
        if self.state not in ('confirmed', 'done'):
            raise UserError(_('Chỉ phụ lục đã xác nhận mới sinh được đơn.'))
        lines = self.appendix_line_ids.filtered(lambda l: not l.display_type)
        if not lines:
            raise UserError(_('Không có dòng nào để tạo đơn.'))
        order = self.env['sale.order'].create({
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'att_appendix_id': self.id,
            'origin': self.name,
            'order_line': [fields.Command.create(
                line._prepare_sale_order_line_vals()) for line in lines],
        })
        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'name': _('SO thực thi %s') % order.name,
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': order.id,
            'context': {},
        }


    def action_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('SO thực thi của %s') % self.name,
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('att_appendix_id', '=', self.id)],
            'context': {
                'default_att_appendix_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_company_id': self.company_id.id,
            },
        }



class AttContractAppendixLine(models.Model):
    _name = 'att.contract.appendix.line'
    _description = 'Dòng phụ lục hợp đồng'
    _order = 'sequence, id'

    appendix_id = fields.Many2one('att.contract.appendix', required=True,
                                  ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    display_type = fields.Selection([
        ('line_section', 'Nhóm'), ('line_note', 'Ghi chú')], default=False)

    name = fields.Text('Nội dung', required=True)
    # Product OPTIONAL ở phụ lục — sinh đơn mới cần, thiếu thì lấy default
    product_id = fields.Many2one('product.product', 'Nội dung xuất hoá đơn',
                                 domain=[('type', '=', 'service')])
    uom_id = fields.Many2one('uom.uom', 'Đơn vị tính')
    quantity = fields.Float('Số lượng', default=1.0)
    price_unit = fields.Monetary('Đơn giá', currency_field='currency_id')
    tax_ids = fields.Many2many('account.tax', string='Thuế',
                               domain="[('type_tax_use', '=', 'sale')]")
    currency_id = fields.Many2one(related='appendix_id.currency_id', store=True)
    price_subtotal = fields.Monetary('Thành tiền', store=True,
                                     compute='_compute_amount',
                                     currency_field='currency_id')
    price_total = fields.Monetary('Thành tiền (gồm thuế)', store=True,
                                  compute='_compute_amount',
                                  currency_field='currency_id')


    @api.depends('quantity', 'price_unit', 'tax_ids')
    def _compute_amount(self):
        for line in self:
            if line.display_type:
                line.price_subtotal = line.price_total = 0.0
                continue
            taxes = line.tax_ids.compute_all(
                line.price_unit, currency=line.currency_id,
                quantity=line.quantity)
            line.price_subtotal = taxes['total_excluded']
            line.price_total = taxes['total_included']


    # HOOK — transport override đẩy field logistics xuống SO thực thi
    def _prepare_sale_order_line_vals(self):
        self.ensure_one()
        product = (self.product_id
                   or self.appendix_id._att_get_default_product('sale'))
        return {
            'product_id': product.id,
            'name': self.name,                  # tuyến/hàng hoá sống ở mô tả
            'product_uom_qty': self.quantity,
            'price_unit': self.price_unit,      # giá LUÔN từ phụ lục
            'tax_ids': [fields.Command.set(self.tax_ids.ids)],
        }



class AttContract(models.Model):
    """Phần MỞ RỘNG att.contract thuộc mối quan tâm phụ lục — đặt ở đây
    (không đặt trong att_contract.py) để file HĐ tự chứa, không biết về PL."""
    _inherit = 'att.contract'

    appendix_ids = fields.One2many('att.contract.appendix', 'contract_id',
                                   'Phụ lục')
    appendix_count = fields.Integer(compute='_compute_appendix_count')


    def _compute_appendix_count(self):
        counts = dict(self.env['att.contract.appendix']._read_group(
            [('contract_id', 'in', self.ids)], ['contract_id'], ['__count']))
        for rec in self:
            rec.appendix_count = counts.get(rec, 0)


    def action_view_appendices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Phụ lục của %s') % self.name,
            'res_model': 'att.contract.appendix',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {'default_contract_id': self.id},
        }