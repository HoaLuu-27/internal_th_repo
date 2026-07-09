from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ThTransportCostType(models.Model):
    """Loại chi phí phát sinh (SRS 2.5.2). Một bản ghi gói đủ bên chịu,
    cách xử lý kế toán, product ánh xạ, logic duyệt."""
    _name = 'att.transport.cost.type'
    _description = 'Loại chi phí phát sinh'
    _order = 'name'

    name = fields.Char('Tên loại chi phí', required=True)
    paid_by = fields.Selection([
        ('customer', 'Khách hàng trả'),
        ('company', 'Trang Huy chịu'),
        ('vendor', 'NCC chịu'),
    ], string='Bên chịu chi phí', required=True, default='customer')
    expense_type = fields.Selection([
        ('so_line', 'Thêm vào dòng đơn hàng bán'),
        ('vendor_bill', 'Tạo phiếu chi NCC nháp'),
        ('internal', 'Chi phí nội bộ'),
    ], string='Cách xử lý kế toán', required=True, default='so_line')
    product_id = fields.Many2one('product.product', 'Sản phẩm Odoo ánh xạ',
                                 domain=[('type', '=', 'service')],
                                 help='Dùng tạo dòng SO hoặc dòng phiếu chi NCC.')
    expense_account_id = fields.Many2one('account.account', 'Tài khoản hạch toán',
                                         help='Tài khoản GL mặc định cho chi phí nội bộ.')
    requires_approval = fields.Boolean('Cần phê duyệt', default=False,
                                       help='KD phải duyệt trước khi đẩy lên đơn hàng.')
    approval_threshold = fields.Monetary('Ngưỡng phê duyệt (VNĐ)', currency_field='currency_id',
                                         help='Vượt ngưỡng mới cần duyệt. 0 = luôn cần duyệt.')
    currency_id = fields.Many2one('res.currency',
                                  default=lambda self: self.env.company.currency_id)
    default_description = fields.Char('Mô tả mặc định')
    active = fields.Boolean(default=True)

    @api.constrains('expense_type', 'product_id')
    def _check_product_required(self):
        for rec in self:
            if rec.expense_type in ('so_line', 'vendor_bill') and not rec.product_id:
                raise UserError(_(
                    'Loại chi phí "%s": cách xử lý "%s" bắt buộc chọn Sản phẩm ánh xạ.'
                ) % (rec.name, dict(rec._fields['expense_type'].selection)[rec.expense_type]))


class ThTransportCostLine(models.Model):
    """Dòng chi phí thực tế trên từng lệnh (SRS 2.5.3).
    Vòng đời: pending → approved → pushed."""
    _name = 'att.transport.cost.line'
    _description = 'Dòng chi phí phát sinh'
    _order = 'date desc, id desc'

    transport_order_id = fields.Many2one('att.transport.order', 'Lệnh vận chuyển',
                                         required=True, ondelete='cascade', index=True)
    cost_type_id = fields.Many2one('att.transport.cost.type', 'Loại chi phí', required=True)
    description = fields.Char('Mô tả')
    amount = fields.Monetary('Số tiền', required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency',
                                  default=lambda self: self.env.company.currency_id)
    date = fields.Date('Ngày phát sinh', required=True, default=fields.Date.today)
    paid_by = fields.Selection(related='cost_type_id.paid_by', store=True, string='Bên chịu')
    expense_type = fields.Selection(related='cost_type_id.expense_type', store=True,
                                    string='Cách xử lý')
    state = fields.Selection([
        ('pending', 'Chờ duyệt'),
        ('approved', 'Đã duyệt'),
        ('pushed', 'Đã xử lý'),
    ], default='pending', index=True, copy=False)
    needs_approval = fields.Boolean('Cần duyệt', compute='_compute_needs_approval', store=True)
    approved_by = fields.Many2one('res.users', 'Người duyệt', readonly=True, copy=False)
    approved_date = fields.Datetime('Ngày duyệt', readonly=True, copy=False)
    vendor_bill_id = fields.Many2one('account.move', 'Phiếu chi NCC', readonly=True, copy=False)
    sale_order_line_id = fields.Many2one('sale.order.line', 'Dòng đơn hàng bán',
                                         readonly=True, copy=False)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    partner_id = fields.Many2one("res.partner",string="Đối tác/NCC",)
    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise UserError(_('Số tiền chi phí phải lớn hơn 0.'))

    @api.depends('cost_type_id', 'amount')
    def _compute_needs_approval(self):
        for rec in self:
            ct = rec.cost_type_id
            rec.needs_approval = bool(
                ct and ct.requires_approval and ct.paid_by == 'customer'
                and (not ct.approval_threshold or rec.amount > ct.approval_threshold))

    @api.onchange('cost_type_id')
    def _onchange_cost_type_id(self):
        for rec in self:
            if rec.cost_type_id and not rec.description:
                rec.description = rec.cost_type_id.default_description or rec.cost_type_id.name

    def action_approve(self):
        """KD/Quản lý duyệt chi phí KH trả — dùng group sale manager native."""
        if not self.env.user.has_group('sales_team.group_sale_manager'):
            raise UserError(_('Bạn không có quyền duyệt chi phí phát sinh.'))
        for rec in self:
            if rec.state != 'pending':
                raise UserError(_('Chỉ duyệt được dòng đang Chờ duyệt.'))
            rec.write({
                'state': 'approved',
                'approved_by': self.env.user.id,
                'approved_date': fields.Datetime.now(),
            })
            rec.transport_order_id.message_post(
                body=_('%(user)s đã duyệt chi phí %(mota)s: %(tien)s.',
                       user=self.env.user.name,
                       mota=rec.description or rec.cost_type_id.name,
                       tien=rec.currency_id.format(rec.amount)),
                message_type='notification', subtype_xmlid='mail.mt_note')
