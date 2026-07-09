from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ThVehicleHandover(models.Model):
    """Biên bản bàn giao xe + vật tư đi kèm (interview QLPT).
    Hai chiều: HCNS ↔ Lái xe và Lái xe ↔ Lái xe."""
    _name = 'att.vehicle.handover'
    _description = 'Biên bản bàn giao xe/vật tư'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char('Số biên bản', default='/', copy=False, readonly=True)
    vehicle_id = fields.Many2one('fleet.vehicle', 'Xe', required=True, index=True)
    handover_type = fields.Selection([
        ('hcns_lx', 'HCNS → Lái xe'),
        ('lx_hcns', 'Lái xe → HCNS'),
        ('lx_lx', 'Lái xe → Lái xe'),
    ], string='Loại bàn giao', required=True, default='hcns_lx')
    date = fields.Datetime('Thời điểm bàn giao', required=True, default=fields.Datetime.now)
    from_employee_id = fields.Many2one('hr.employee', 'Bên giao', required=True)
    to_employee_id = fields.Many2one('hr.employee', 'Bên nhận', required=True)
    line_ids = fields.One2many('att.vehicle.handover.line', 'handover_id', 'Checklist vật tư')
    odometer = fields.Float('Odometer lúc giao (km)')
    note = fields.Text('Ghi chú')
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('done', 'Đã xác nhận'),
    ], default='draft', tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') in ('/', False):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'att.vehicle.handover') or '/'
        return super().create(vals_list)

    def action_confirm(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Biên bản cần ít nhất một dòng vật tư/hạng mục.'))
            if rec.from_employee_id == rec.to_employee_id:
                raise UserError(_('Bên giao và bên nhận phải khác nhau.'))
            rec.state = 'done'
            if rec.handover_type in ('hcns_lx', 'lx_lx'):
                rec.vehicle_id.default_driver_employee_id = rec.to_employee_id
            if rec.odometer:
                rec.vehicle_id.odometer = rec.odometer
            rec.message_post(
                body=Markup('Bàn giao xe <b>%s</b>: <b>%s</b> → <b>%s</b> (%d hạng mục).') % (
                    rec.vehicle_id.display_name, rec.from_employee_id.name,
                    rec.to_employee_id.name, len(rec.line_ids)),
                message_type='notification', subtype_xmlid='mail.mt_note')

    def action_reset_draft(self):
        self.write({'state': 'draft'})


class ThVehicleHandoverLine(models.Model):
    _name = 'att.vehicle.handover.line'
    _description = 'Dòng checklist bàn giao'
    _order = 'sequence, id'

    handover_id = fields.Many2one('att.vehicle.handover', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char('Vật tư / Hạng mục', required=True)
    quantity = fields.Float('Số lượng', default=1.0)
    condition = fields.Selection([
        ('good', 'Tốt'),
        ('used', 'Đã dùng / trầy xước'),
        ('damaged', 'Hư hỏng'),
        ('missing', 'Thiếu'),
    ], string='Tình trạng', default='good', required=True)
    note = fields.Char('Ghi chú')
