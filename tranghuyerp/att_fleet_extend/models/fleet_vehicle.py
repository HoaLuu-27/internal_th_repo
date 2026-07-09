from odoo import api, fields, models, _


class FleetVehicle(models.Model):
    """Mở rộng xe cho điều vận Trang Huy (SRS 2.5.6).

    th_state là field THƯỜNG (không compute): available/in_transit do module
    att_transport_order ghi khi lệnh chạy/đóng; maintenance/broken do người
    quản lý xe đặt tay — TO không suy ra được 2 trạng thái này.
    """
    _inherit = 'fleet.vehicle'

    th_state = fields.Selection([
        ('available', 'Sẵn sàng'),
        ('in_transit', 'Đang chạy'),
        ('maintenance', 'Bảo dưỡng'),
        ('broken', 'Hỏng'),
    ], string='Trạng thái điều vận', default='available', tracking=True, index=True)

    default_driver_employee_id = fields.Many2one(
        'hr.employee', string='Lái xe mặc định',
        help='Lái xe gắn mặc định với xe. Điều vận viên có thể đổi khi tạo lệnh.')

    payload_capacity = fields.Float(
        'Tải trọng tối đa (tấn)',
        help='Dùng cảnh báo khi tổng hàng vượt tải cho phép.')
    volume_capacity = fields.Float(
        'Thể tích tối đa (m³)',
        help='Dùng lọc khi ghép hàng nhiều đơn.')

    # ---- Bảo dưỡng theo km (interview QLPT: theo km, đảo lốp...) ----
    service_interval_km = fields.Float(
        'Định mức bảo dưỡng (km)', default=0.0,
        help='Số km giữa 2 lần bảo dưỡng. 0 = không theo dõi.')
    last_service_odometer = fields.Float('Odometer lần bảo dưỡng cuối (km)', default=0.0)
    km_to_service = fields.Float('Km còn lại tới bảo dưỡng', compute='_compute_km_to_service')

    document_ids = fields.One2many('att.vehicle.document', 'vehicle_id', 'Giấy tờ xe')
    document_count = fields.Integer(compute='_compute_document_count')
    handover_ids = fields.One2many('att.vehicle.handover', 'vehicle_id', 'Biên bản bàn giao')
    handover_count = fields.Integer(compute='_compute_handover_count')

    @api.depends('odometer', 'service_interval_km', 'last_service_odometer')
    def _compute_km_to_service(self):
        for rec in self:
            if rec.service_interval_km > 0:
                rec.km_to_service = (rec.last_service_odometer
                                     + rec.service_interval_km - rec.odometer)
            else:
                rec.km_to_service = 0.0

    def _compute_document_count(self):
        for rec in self:
            rec.document_count = len(rec.document_ids)

    def _compute_handover_count(self):
        for rec in self:
            rec.handover_count = len(rec.handover_ids)

    def action_view_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Giấy tờ xe %s') % self.license_plate,
            'res_model': 'att.vehicle.document',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }

    def action_view_handovers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bàn giao xe %s') % self.license_plate,
            'res_model': 'att.vehicle.handover',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }

    @api.model
    def _cron_check_maintenance_due(self):
        """Cron ngày: xe chạy quá định mức km → activity người quản lý xe."""
        vehicles = self.search([('service_interval_km', '>', 0)])
        for vehicle in vehicles.filtered(lambda v: v.km_to_service <= 0):
            vehicle.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=vehicle.manager_id.id or self.env.ref('base.user_admin').id,
                summary=_('Xe %s tới hạn bảo dưỡng (quá %s km)') % (
                    vehicle.license_plate, abs(vehicle.km_to_service)),
            )
