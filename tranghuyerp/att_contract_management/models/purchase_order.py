# -*- coding: utf-8 -*-
"""PO THỰC THI — đơn mua sinh từ PHỤ LỤC hợp đồng NCC (giá từ phụ lục).

Phân biệt với RFQ mời thầu bằng att_is_execution (compute từ att_appendix_id).
Gate button_confirm: RFQ mời thầu KHÔNG confirm thẳng thành PO — flow chuẩn
chốt NCC → HĐNT → phụ lục → PO thực thi. Ngoại lệ mua lẻ gấp: Quản lý.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    att_appendix_id = fields.Many2one(
        'att.contract.appendix', 'Phụ lục nguồn',
        readonly=True, copy=False, index=True,
        help='Set bởi appendix.action_create_purchase_order khi sinh đơn.')
    att_is_execution = fields.Boolean(
        'Là đơn thực thi', compute='_compute_att_is_execution', store=True)




    @api.model
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name','/') in ('/', False) and vals.get('att_is_execution'):
                name = self.env['ir.sequence'].next_by_code('att.purchase.order.execution')
                if name:
                    vals['name'] = name
        return super().create(vals_list)


    @api.depends('att_appendix_id')
    def _compute_att_is_execution(self):
        for rec in self:
            rec.att_is_execution = bool(rec.att_appendix_id)

    def button_confirm(self):
        """Chặn confirm RFQ mời thầu — server-side.
        - PO thực thi (có phụ lục): confirm tự do, giá đã chốt qua HĐ/PL.
        - RFQ: chỉ Quản lý confirm được (đường mua lẻ gấp không qua HĐ)."""
        for rec in self:
            if rec.att_is_execution:
                continue
            if not self.env.user.has_group(
                    'att_contract_management.group_att_qc_manager'):
                raise UserError(_(
                    'RFQ %s là báo giá mời thầu — không xác nhận trực tiếp được.\n'
                    'Flow chuẩn: chốt NCC → HĐNT → Phụ lục → PO thực thi.\n'
                    '(Mua chuyến lẻ gấp cần Quản lý xác nhận.)') % rec.name)
        return super().button_confirm()

    def action_view_att_appendix(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'att.contract.appendix',
            'view_mode': 'form',
            'res_id': self.att_appendix_id.id,
        }