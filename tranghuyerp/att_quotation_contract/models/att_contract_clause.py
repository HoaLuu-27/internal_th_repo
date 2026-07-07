import logging
from odoo import api,fields,models,_
from odoo.exceptions import UserError


logger = logging.getLogger(__name__)


class ContractClause(models.Model):
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
    title = fields.Char('Tiêu đề điều',)
    content = fields.Html('Nội dung')
    is_fixed = fields.Boolean('Cố định', default=False, help='Nếu bật, điều khoản này không cho phép chỉnh sửa khi load vào HĐ')
    active = fields.Boolean(default=True)

