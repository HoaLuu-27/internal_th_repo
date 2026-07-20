# -*- coding: utf-8 -*-
import re
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class AttContractClause(models.Model):
    _name = 'att.contract.clause'
    _description = 'Thư viện điều khoản hợp đồng'
    _order = 'clause_type, sequence'

    name = fields.Char('Tên điều khoản', required=True)
    clause_type = fields.Selection([
        ('sale', 'Hợp đồng bán'),
        ('purchase', 'Hợp đồng mua'),
        ('both', 'Cả hai'),
    ], string='Loại HĐ áp dụng', required=True, default='both')
    sequence = fields.Integer('Số thứ tự', default=10)
    title = fields.Char('Tiêu đề điều')
    content = fields.Html('Nội dung')
    is_fixed = fields.Boolean(
        'Cố định', default=False,
        help='Nếu bật, điều khoản này không cho phép chỉnh sửa khi load vào HĐ.')
    active = fields.Boolean(default=True)


class AttContractTermLine(models.Model):
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
    display_title = fields.Char('Số điều', compute='_compute_display_title')
    content = fields.Html('Nội dung')
    note = fields.Text('Ghi chú')
    is_fixed = fields.Boolean('Cố định', default=False)
    clause_id = fields.Many2one('att.contract.clause', string='Điều khoản',
                                ondelete='set null')

    @api.model
    def _strip_dieu_prefix(self, title):
        """Bỏ tiền tố 'Điều <số>:' nếu user/dữ liệu cũ vẫn gõ kèm số."""
        if not title:
            return title
        return re.sub(r'^\s*điều\s*\d+\s*[:.\-–]?\s*', '', title,
                      flags=re.IGNORECASE).strip()

    @api.depends('title', 'sequence', 'contract_id.term_line_ids',
                 'contract_id.term_line_ids.sequence')
    def _compute_display_title(self):
        for line in self:
            number = 1
            for idx, sibling in enumerate(line.contract_id.term_line_ids, start=1):
                if sibling == line:
                    number = idx
                    break
            clean_title = self._strip_dieu_prefix(line.title)
            if clean_title:
                line.display_title = _('Điều %(num)d: %(title)s',
                                       num=number, title=clean_title)
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
                vals['title'] = self._strip_dieu_prefix(vals['title'])
        return super().create(vals_list)

    def write(self, vals):
        for rec in self:
            if rec.is_fixed and not self.env.context.get('skip_fixed_check'):
                blocked = {'title', 'content', 'is_fixed'}
                if blocked.intersection(vals.keys()):
                    raise UserError(_('Không được sửa điều khoản cố định.'))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.is_fixed and not self.env.context.get('skip_fixed_check'):
                raise UserError(_('Không được xóa điều khoản cố định.'))
        return super().unlink()
