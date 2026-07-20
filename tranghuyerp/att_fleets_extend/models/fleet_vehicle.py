from odoo import api, fields, models, _


class FleetVehicle(models.Model):
    """Mở rộng xe cho điều vận Trang Huy (SRS 2.5.6).

    th_state là field THƯỜNG (không compute): available/in_transit do module
    att_transport_orders ghi khi lệnh chạy/đóng; maintenance/broken do người
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

    # VietMap Route v4 chỉ nhận đúng 4 nhóm xe — khi điều vận đã gán đúng 1
    # xe thật (sol.vehicle_id), ưu tiên số liệu CHÍNH xe đó (payload_capacity
    # đã có sẵn ở trên, đơn vị TẤN) thay vì số liệu chung chung của
    # att.vehicle.type — chính xác hơn cho routing.
    vietmap_vehicle_class = fields.Selection([
        ('motorcycle', 'Xe máy'),
        ('car', 'Xe con / xe tải nhẹ (không khai tải trọng)'),
        ('truck', 'Xe tải (khai tải trọng)'),
        ('container', 'Xe container'),
    ], string="Nhóm xe (VietMap)", default='truck',
        help="VietMap Route API chỉ nhận đúng 4 nhóm này để tính tuyến "
             "đúng luật (né đường cấm tải, hầm chui, giờ cấm...).")

    # ---- Vị trí hiện tại — TẠM nhập tay để mô phỏng bản đồ nhiệt, chờ
    # VietMap bàn giao API Tracking (đang vướng bảo mật) mới đồng bộ tự động.
    # Kiến trúc giữ nguyên khi có API thật: chỉ đổi NGUỒN ghi 2 field này
    # (cron/webhook thay vì user gõ tay), phần hiển thị bản đồ không đổi.
    current_lat = fields.Float(
        'Vĩ độ hiện tại', digits=(10, 7),
        help='Vị trí hiện tại của xe. Tạm nhập tay để mô phỏng — sau này '
             'đồng bộ tự động từ thiết bị GPS VietMap Tracking khi có API.')
    current_lng = fields.Float('Kinh độ hiện tại', digits=(10, 7))
    current_position_updated = fields.Datetime(
        'Cập nhật vị trí lúc', readonly=True, copy=False,
        help='Thời điểm toạ độ hiện tại được ghi lần cuối — tự động cập '
             'nhật mỗi khi current_lat/current_lng đổi.')

    def write(self, vals):
        if 'current_lat' in vals or 'current_lng' in vals:
            vals = dict(vals, current_position_updated=fields.Datetime.now())
        return super().write(vals)

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

    @api.depends('payload_capacity', 'license_plate')
    def _compute_vehicle_name(self):
        """Đổi tên hiển thị thành 'Tải trọng-BKS' (VD: 5T-29K21231) thay vì
        'Hãng/Model/BKS' mặc định của Odoo — điều vận viên chọn xe theo TẢI
        TRỌNG là chính (không nhớ hãng/đời xe), nên đưa thẳng thông tin cần
        ra tên hiển thị để dễ chọn đúng ngay trên dropdown."""
        for record in self:
            capacity = record.payload_capacity
            cap_str = ('%gT' % capacity) if capacity else '?T'
            plate = record.license_plate or _('Chưa có biển số')
            record.name = '%s-%s' % (cap_str, plate)

    def _vietmap_route_params(self):
        """Trả (vehicle, capacity) từ chính XE THẬT — payload_capacity
        (tấn) tự quy đổi sang kg cho VietMap. capacity CHỈ gửi khi
        vehicle=truck (theo tài liệu VietMap)."""
        self.ensure_one()
        vehicle = self.vietmap_vehicle_class or 'truck'
        capacity = (int(self.payload_capacity * 1000)
                    if vehicle == 'truck' and self.payload_capacity else None)
        return vehicle, capacity
