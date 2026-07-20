# -*- coding: utf-8 -*-
"""FLOW BÁO GIÁ NCC (RFQ mời thầu) — vòng đời chốt NCC trên purchase.order.

    draft ──chốt NCC──> won ──tạo HĐNT──> contracted
      └── manual ──> lost (Không chọn — CHỈ khi NCC nợ xấu/lịch sử kém)

Nhóm báo giá = các RFQ cùng SO nguồn (att_source_sale_order_id).

Rule nghiệp vụ:
- Đủ ngưỡng tối thiểu (config, mặc định 5 NCC/nhóm) mới được chốt.
- NHIỀU NCC cùng nhóm đều tạo được HĐNT (họp KH 07/2026 — bỏ auto-loại).
- 'lost' KHÔNG bao giờ tự động — chỉ Quản lý đánh tay khi NCC nợ xấu.

- action_att_create_ncc_rfq: SO → mở form RFQ prefill dòng
- action_att_create_po_best_price: đặt xe NCC GIÁ RẺ NHẤT đã ký HĐNT

PO THỰC THI nằm ở purchase_order.py — không phải ở đây.

HOOK cho module transport (inherit sau):
- sale.order._att_get_outsource_lines(): base = mọi dòng dịch vụ;
  transport override = chỉ dòng THIẾU XE nội bộ.
- sale.order._att_prepare_rfq_line_vals(sol): transport bổ sung logistics.
"""
import logging
from markupsafe import Markup
from odoo import models, fields,api, _
from odoo.exceptions import ValidationError, UserError


_logger = logging.getLogger(__name__)

ATT_RFQ_MANAGER_STATES = ('won',)
ATT_RFQ_ADMIN_STATES = ('contracted', 'lost')
ATT_RFQ_LOCK_EXEMPT_FIELDS = {
    'att_quote_state', 'att_contract_id',
    'message_follower_ids', 'message_ids', 'activity_ids',
}



class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'


    att_quote_state = fields.Selection([
        ('draft','Nháp'),
        ('won','Đã chốt NCC'),
        ('contracted','Đã tạo HĐNT'),
        ('lost','Không chọn'),
    ],'Trạng thái báo giá', default='draft', copy=False, tracking=True, index=True)

    att_source_sale_order_id = fields.Many2one('sale.order','Đơn hàng gốc', index=True, copy=False, domain="[('state','=','sale')]")
    att_contract_id = fields.Many2one('att.contract', 'Hợp đồng nguyên tắc', readonly=True, copy=False)
    att_rfq_group_count = fields.Integer('Số RFQ trong nhóm', compute='_compute_att_rfq_group_count',help='Số báo giá NCC cùng SO nguồn - đr ngưỡng mới được chốt.')
    att_can_edit = fields.Boolean('Được sửa nội dung', compute='_compute_att_can_edit')



    @api.depends('att_quote_state')
    def _compute_att_can_edit(self):
        is_manager = self.env.user.has_group('att_contract_management.group_att_qc_manager')
        is_admin = self.env.user.has_group('base.group_system')
        for rec in self:
            if rec.att_quote_state in ATT_RFQ_ADMIN_STATES:
                rec.att_can_edit = is_admin
            elif rec.att_quote_state in ATT_RFQ_MANAGER_STATES:
                rec.att_can_edit = is_manager
            else:
                rec.att_can_edit = True


    def write(self, vals):
        if set(vals.keys()) - ATT_RFQ_LOCK_EXEMPT_FIELDS:
            for rec in self.filtered(lambda r: not r.att_is_execution):
                if (rec.att_quote_state in ATT_RFQ_ADMIN_STATES
                        and not self.env.user.has_group('base.group_system')):
                    raise UserError(_(
                        'Báo giá NCC %s đã kết thúc vòng đời — chỉ Admin hệ thống '
                        'mới sửa được nội dung.') % rec.name)
                if (rec.att_quote_state in ATT_RFQ_MANAGER_STATES
                        and not self.env.user.has_group(
                            'att_contract_management.group_att_qc_manager')):
                    raise UserError(_(
                        'Báo giá NCC %s đã chốt NCC — chỉ Quản lý trở lên mới sửa '
                        'được nội dung.') % rec.name)
        return super().write(vals)


    @api.model
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') in ('/', False) and not vals.get('att_is_execution'):
                name = self.env['ir.sequence'].next_by_code('att.purchase.quotation')
                if name:
                    vals['name'] = name
        return super().create(vals_list)


    def _compute_att_rfq_group_count(self):
        for rec in self:
            rec.att_rfq_group_count = (len(rec._att_get_sibling_rfqs()) if rec.att_source_sale_order_id else (1 if rec.id else 0))


    def _att_get_sibling_rfqs(self):
        """
        Mọi RFQ cùng SO nguồn, gồm chính nó - Không tính đơn thực thi và báo giá đã loại.
        """
        self.ensure_one()
        if not self.att_source_sale_order_id:
            return self
        return self.search([
            ('att_source_sale_order_id','=', self.att_source_sale_order_id.id),
            ('att_is_execution','=', False),
            ('att_quote_state','=', 'lost'),
        ])


    @api.model
    def _att_get_min_rfq_threshold(self):
        """
        Ngưỡng tối thiểu NCC/nhóm - chỉnh qua system parameter 'att_contract_management.min_rfq_per_group' (mặc định là 5).
        """
        param = self.env['ir.config_parameter'].sudo().get_param('att_contract_management.mỉn_rfq_per_group', '5')
        try:
            return max(int(param), 1)
        except ValueError:
            return 5


    def _att_check_min_rfq_threshold(self):
        self.ensure_one()
        minimum = self._att_get_min_rfq_threshold()
        count = len(self._att_get_sibling_rfqs())
        if count < minimum:
            raise UserError(_(
                'Nhóm hỏi giá của SO %(so)s mới có %(n)d báo giá NCC — cần tối '
                'thiểu %(min)d để so sánh trước khi chốt.\n'
                '(Đổi ngưỡng: System Parameter '
                'att_contract_management.min_rfq_per_group)',
                so=self.att_source_sale_order_id.name or '?',
                n=count, min=minimum
            ))


    def _att_check_manager(self):
        if not self.env.user.has_group('att_contract_management.group_att_qc_manager'):
            raise UserError(_('Chỉ Quản lý mới được chốt NCC.'))


    #CHốt NCC
    def action_att_mark_won(self):
        self.ensure_one()
        self._att_check_manager()
        for rec in self:
            if rec.att_is_execution:
                raise UserError(_('Đơn thực thi không phải báo giá để chốt.'))
            if rec.att_quote_state != 'draft':
                raise UserError(_('Báo giá %s đã được xử lý rồi') % rec.name)
            rec._att_check_min_rfq_threshold()
            rec.att_quote_state = 'won'
            rec.message_post(
                ody=Markup('<b>%s</b> chốt NCC <b>%s</b> thắng '
                           '(nhóm %d báo giá).') % (
                        self.env.user.name, rec.partner_id.name,
                        rec.att_rfq_group_count),
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )


    def action_att_mark_lost(self):
        """'Không chọn' — THỦ CÔNG DUY NHẤT, khi NCC nợ xấu/lịch sử kém.
        (Họp KH 07/2026: bỏ auto-loại khi NCC khác tạo HĐNT.)"""
        self._att_check_manager()
        for rec in self:
            if rec.att_is_execution:
                raise UserError(_('Đơn thực thi không phải báo giá NCC để loại.'))
            if rec.att_quote_state == 'contracted':
                raise UserError(_(
                    'Báo giá %s đã tạo HĐNT — xử lý ở vòng đời hợp đồng.')
                    % rec.name)
            if rec.state in ('draft', 'sent'):
                rec.button_cancel()
            rec.att_quote_state = 'lost'
            rec.message_post(
                body=Markup('<b>%s</b> đánh dấu <b>Không chọn</b> NCC <b>%s</b> '
                            '(nợ xấu / lịch sử giao dịch kém).') % (
                    self.env.user.name, rec.partner_id.name),
                message_type='notification', subtype_xmlid='mail.mt_note')


    #tạo HDNT
    def action_create_att_contract(self):
        self.ensure_one()
        self._att_check_manager()
        if self.att_quote_state != 'won':
            raise UserError(_('Chỉ báo giá "Đã chốt NCC" mới tạo được HĐNT.'))
        if self.att_contract_id:
            raise UserError(_('Báo giá này đã gắn hợp đồng %s.') % self.att_contract_id.name)
        existing = self.env['att.contract']._get_running_contract( self.partner_id, 'purchase', self.company_id)
        if existing:
            raise UserError(_(
                'NCC %(ncc)s đã có HĐNT đang hiệu lực (%(hd)s).\n'
                'Tạo PHỤ LỤC giá mới trên hợp đồng đó thay vì ký HĐ mới.',
                ncc=self.partner_id.name, hd=existing.name
            ))
        # Quá hạn chốt (Order Deadline) → giá NCC chào không còn cam kết
        if self.date_order and self.date_order.date() < fields.Date.today():
            raise UserError(_(
                'Báo giá NCC %(bg)s quá hạn chốt từ %(ngay)s — xác nhận lại '
                'giá với NCC (cập nhật Hạn chốt đơn) trước khi tạo HĐNT.',
                bg=self.name, ngay=self.date_order.strftime('%d/%m/%Y')))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo hợp đồng nguyên tắc NCC'),
            'res_model': 'att.contract',
            'view_mode': 'form',
            'context': {
                'default_contract_type': 'purchase',
                'default_partner_id': self.partner_id.id,
                'default_source_purchase_order_id': self.id,
                'default_company_id': self.company_id.id,
            },
        }
        # att_quote_state → 'contracted' do att.contract.create() gắn ngược
        # khi HĐ thực sự được lưu (đã có sẵn ở att_contract.py)


class AttSaleOrderPurchaseFlow(models.Model):
    _inherit = 'sale.order'


    att_rfq_ids = fields.One2many('purchase.order', 'att_source_sale_order_id', 'Báo giá NCC')
    att_rfq_count = fields.Integer(compute='_compute_att_rfq_count')


    def _compute_att_rfq_count(self):
        counts = dict(self.env['purchase.order']._read_group(
            [('att_source_sale_order_id','in',self.ids)],
            ['att_source_sale_order_id'], ['__count']
        ))
        for rec in self:
            rec.att_rfq_count = counts.get(rec, 0)

    def _att_get_outsource_lines(self):
        """
        Dòng cần thuê ngoài: Base : mọi dòng dịch vụ thật.
        Transport Override: chỉ dòng dịch vụ thiếu xe nội bộ (để tạo TO thuê ngoài).
        """
        self.ensure_one()
        return self.order_line.filtered(
            lambda l: not l.display_type and l.product_id
        )


    def _att_purchase_rfq_line_vals(self, sol):
        """
        Map dòng SO -> dòng RFQ NCC. Giá để 0.
        Transport Override: bổ sung logistics (tuyến, xe, lái xe) để NCC biết chạy.
        """
        product = self.env['att.contract.appendix']._att_get_default_product('purchase')
        return {
            'product_id': product.id,
            'name': sol.name,
            'product_qty': sol.product_uom_qty,
            'price_unit': 0.0,
        }


    def action_att_create_ncc_rfq(self):
        """

        """
        self.ensure_one()
        if self.state != 'sale':
            raise UserError(_('Chỉ SO đã xác nhận mới tạo được báo giá NCC.'))
        lines = self._att_get_outsource_lines()
        if not lines:
            raise UserError(_('Đơn bán hàng %s không có dòng nào cần thuê ngoài') % self.name)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tạo RFQ NCC từ %s') % self.name,
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'context': {
                'default_source_sale_order_id': self.id,
                'default_origin': self.name,
                'default_order_line': [
                    fields.Command.create(self._att_purchase_rfq_line_vals(sol)) for sol in lines
                ],
            },
        }


    def action_view_att_rfqs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Báo giá NCC của %s') % self.name,
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('att_source_sale_order_id', '=', self.id)],
            'context': {
                'default_source_sale_order_id': self.id,
            }
        }


    #dat xe - ưu tiên NCC giá rẻ nhất
    def action_att_create_po_best_price(self):
        """
        Duyệt các báo giá đã ký HDNT của SO này theo Tổng tiền tăng dần,
        lấy NCC đầu tiên còn HĐ hiệu lực + phụ lục đã xác nhận -> sinh PO thực thi từ phụ lục đó hoặc từ HDNT luôn.
        """
        self.ensure_one()
        self.env['purchase.order']._att_check_manager()
        candidates = self.env['purchase.order'].search([
            ('att_source_sale_order_id', '=', self.id),
            ('att_is_execution',  '=', False),
            ('att_quote_state', '=', 'contracted'),
        ], order='amount_total asc')
        if not candidates:
            raise UserError(_(
                'SO %s chưa có báo giá NCC nào "Đã tạo HĐNT".\n'
                'Flow: tạo RFQ NCC → chốt NCC → tạo HĐNT → quay lại đây.') % self.name
            )
        Appendix = self.env['att.contract.appendix']
        for rfq in candidates:
            contract = rfq.att_contract_id
            if not contract or contract.state != 'running':
                continue
            appendix = Appendix.search([
                ('contract_id', '=', contract.id),
                ('state', 'in', ('draft','confirmed')),
            ], order='id desc', limit=1)
            if appendix:
                self.message_post(
                    body=Markup('Đặt xe NCC <b>%s</b> — báo giá <b>%s</b> '
                                '(tổng %s, rẻ nhất trong %d NCC đã ký HĐNT). '
                                'Sinh PO từ phụ lục <b>%s</b>.') % (
                             rfq.partner_id.name, rfq.name,
                             f'{rfq.amount_total:,.0f}', len(candidates),
                             appendix.name),
                    message_type='notification', subtype_xmlid='mail.mt_note'
                )
                return appendix.action_create_purchase_order(rfq)
            po = rfq._att_create_execution_po_from_contract()
            self.message_post(
                body=Markup('Đặt xe NCC <b>%s</b> — báo giá <b>%s</b> '
                            '(tổng %s, rẻ nhất trong %d NCC đã ký HĐNT). '
                            'HĐ <b>%s</b> chưa có phụ lục — sinh PO trực tiếp '
                            'theo giá RFQ thắng.') % (
                         rfq.partner_id.name, rfq.name,
                         f'{rfq.amount_total:,.0f}', len(candidates), contract.name),
                message_type='notification', subtype_xmlid='mail.mt_note')
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order',
                'view_mode': 'form',
                'res_id': po.id,
            }
        raise UserError(_(
            '%d báo giá đã tạo HĐNT nhưng không NCC nào còn hợp đồng đang '
            'hiệu lực. Kiểm tra vòng đời HĐ trước khi đặt xe.')
                        % len(candidates))


    def _att_create_execution_po_from_contract(self):
        """Sinh PO thực thi TRỰC TIẾP từ HĐNT — dùng khi NCC đã ký HĐ nhưng
        chưa làm phụ lục. Giá lấy từ chính RFQ thắng (self) — đó là nguồn
        giá của HĐ tại thời điểm ký. Khi có phụ lục thì đường phụ lục
        được ưu tiên (giá mới hơn)."""
        self.ensure_one()
        if not self.att_contract_id or self.att_contract_id.state != 'running':
            raise UserError(_('Báo giá %s không gắn hợp đồng đang hiệu lực.')
                            % self.name)
        lines = self.order_line.filtered(lambda l: not l.display_type)
        if not lines:
            raise UserError(_('RFQ %s không có dòng nào để tạo đơn.') % self.name)
        return self.create({
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'att_contract_id': self.att_contract_id.id,
            'att_is_execution': True,
            'att_source_sale_order_id': self.att_source_sale_order_id.id,
            'origin': '%s, %s' % (self.att_contract_id.name, self.name),
            'payment_term_id': self.payment_term_id.id,
            'order_line': [fields.Command.create({
                'product_id': pol.product_id.id,
                'name': pol.name,
                'product_qty': pol.product_qty,
                'price_unit': pol.price_unit,       # giá NCC đã chốt
                'tax_ids': [fields.Command.set(pol.tax_ids.ids)],
            }) for pol in lines],
        })
