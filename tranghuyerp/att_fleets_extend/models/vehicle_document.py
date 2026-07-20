from datetime import timedelta

from odoo import api, fields, models, _


class ThVehicleDocument(models.Model):
    """Giấy tờ xe: đăng kiểm / bảo hiểm / phù hiệu... (interview QLPT).
    Lái xe/user upload; cron cảnh báo theo ngày hết hạn."""
    _name = 'att.vehicle.document'
    _description = 'Giấy tờ xe'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'expiry_date, id desc'

    vehicle_id = fields.Many2one('fleet.vehicle', 'Xe', required=True,
                                 ondelete='cascade', index=True)
    doc_type = fields.Selection([
        ('dang_kiem', 'Đăng kiểm'),
        ('bao_hiem', 'Bảo hiểm'),
        ('phu_hieu', 'Phù hiệu'),
        ('khac', 'Khác'),
    ], string='Loại giấy tờ', required=True, default='dang_kiem')
    name = fields.Char('Số / Tên giấy tờ', required=True)
    issue_date = fields.Date('Ngày cấp')
    expiry_date = fields.Date('Ngày hết hạn', required=True, tracking=True, index=True)
    attachment = fields.Binary('File giấy tờ')
    attachment_filename = fields.Char('Tên file')
    note = fields.Text('Ghi chú')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    days_to_expiry = fields.Integer('Số ngày còn hạn', compute='_compute_days_to_expiry')
    expiry_state = fields.Selection([
        ('valid', 'Còn hạn'),
        ('expiring', 'Sắp hết hạn'),
        ('expired', 'Đã hết hạn'),
    ], compute='_compute_days_to_expiry', string='Tình trạng hạn')

    @api.depends('expiry_date')
    def _compute_days_to_expiry(self):
        today = fields.Date.today()
        warn_days = self._get_warn_days()
        for rec in self:
            if not rec.expiry_date:
                rec.days_to_expiry = 0
                rec.expiry_state = 'valid'
                continue
            days = (rec.expiry_date - today).days
            rec.days_to_expiry = days
            if days < 0:
                rec.expiry_state = 'expired'
            elif days <= warn_days:
                rec.expiry_state = 'expiring'
            else:
                rec.expiry_state = 'valid'

    @api.model
    def _get_warn_days(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'att.vehicle.doc_warn_days', '30')
        try:
            return int(raw)
        except ValueError:
            return 30

    @api.model
    def _cron_notify_expiring_documents(self):
        """Cron ngày: giấy tờ sắp hết hạn → activity người quản lý xe (SRS 2.8)."""
        warn_days = self._get_warn_days()
        deadline = fields.Date.today() + timedelta(days=warn_days)
        docs = self.search([
            ('expiry_date', '<=', deadline),
            ('expiry_date', '>=', fields.Date.today()),
        ])
        for doc in docs:
            if doc.activity_ids.filtered(lambda a: not a.date_done):
                continue
            user = doc.vehicle_id.manager_id or self.env.ref('base.user_admin')
            doc.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=doc.expiry_date,
                user_id=user.id,
                summary=_('Xe %(xe)s: %(loai)s hết hạn ngày %(ngay)s',
                          xe=doc.vehicle_id.license_plate or doc.vehicle_id.name,
                          loai=dict(doc._fields['doc_type'].selection)[doc.doc_type],
                          ngay=doc.expiry_date.strftime('%d/%m/%Y')),
            )
