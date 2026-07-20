# -*- coding: utf-8 -*-
"""SO THỰC THI — đơn bán sinh từ PHỤ LỤC hợp đồng (giá lấy từ phụ lục).

Phân biệt với báo giá bằng att_is_execution (compute từ att_appendix_id):
có phụ lục nguồn = đơn thực thi, không thể set sai bằng tay.

Gate action_confirm: báo giá KHÔNG confirm thẳng thành đơn — phải đi
flow duyệt giá → HĐNT → phụ lục. Ngoại lệ đơn lẻ B2C: Quản lý confirm được.
"""
import logging
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

class SaleOrder(models.Model):
    _inherit = 'sale.order'


    att_appendix_id = fields.Many2one('att.contract.appendix', 'Phụ lục nguồn',readonly=True, copy=False, index=True)
    att_is_execution = fields.Boolean('Là đơn thực thi', compute='_compute_att_is_execute',store=True)



    @api.model
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name','/') in ('/', False) and vals.get('att_appendix_id'):
                name = self.env['ir.sequence'].next_by_code('att.sale.order.execution')
                if name:
                    vals['name'] = name
        return super().create(vals_list)


    @api.depends('att_appendix_id')
    def _compute_att_is_execute(self):
        for rec in self:
            rec.att_is_execution = bool(rec.att_appendix_id)


    def action_confirm(self):
        for rec in self:
            if rec.att_is_execution:
                continue
            if not self.env.user.has_group('att_contract_management.group_att_qc_manager'):
                raise UserError(_(
                    'Báo giá %s không xác nhận trực tiếp được.\n'
                    'Flow chuẩn: duyệt giá → KH chốt → HĐNT → Phụ lục → SO thực thi.\n'
                    '(Đơn lẻ B2C cần Quản lý xác nhận.)'
                )% rec.name)
        return super().action_confirm()


    def action_view_att_appendix(self):
        self.ensure_one()
        return {
            'type':'ir.actions.act_window',
            'res_model': 'att.contract.appendix',
            'view_mode': 'form',
            'res_id': self.att_appendix_id.id,
        }