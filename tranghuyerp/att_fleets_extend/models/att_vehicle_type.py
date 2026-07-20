from odoo import fields, models, api, _


class AttVehicleType(models.Model):
    _name = "att.vehicle.type"
    _description = "Loại xe vận chuyển"
    _order = "sequence, name"

    name = fields.Char(string="Tên loại xe", required=True)
    code = fields.Char(string="Mã")
    sequence = fields.Integer(default=10)

    length_cm = fields.Float(string="Dài thùng xe (cm)")
    width_cm = fields.Float(string="Rộng thùng xe (cm)")
    height_cm = fields.Float(string="Cao thùng xe (cm)")

    dimension_text = fields.Char(
        string="Kích thước thùng xe",
        compute="_compute_dimension_text",
        store=True,
    )

    # Tải trọng — max_weight_kg là field GỐC (kg), mọi nơi khác trong hệ
    # thống (domain, so sánh, truyền cho VietMap) đều đọc field này. 2 field
    # weight_input_* chỉ là cổng nhập liệu tiện (nhân viên quen gõ theo
    # tấn/tạ hơn là gõ thẳng số kg lớn), không phải nguồn dữ liệu thật.
    max_weight_kg = fields.Float(string="Tải trọng tối đa (kg)")
    weight_input_unit = fields.Selection([
        ('kg', 'kg'),
        ('ta', 'Tạ (100kg)'),
        ('tan', 'Tấn (1000kg)'),
    ], string="Đơn vị nhập", default='tan',
        help="Chỉ để tiện gõ số — hệ thống tự quy đổi và lưu vào "
             "'Tải trọng tối đa (kg)'.")
    weight_input_value = fields.Float(
        string="Tải trọng (theo đơn vị nhập)",
        help="Gõ số theo đơn vị chọn ở trên (VD: 5 + Tấn = 5000kg) — tự "
             "động quy đổi và ghi vào Tải trọng tối đa (kg).")
    max_weight_per_package_kg = fields.Float(string="Tối đa kg/kiện")

    max_volume_m3 = fields.Float(
        string="Thể tích tối đa (m³)",
        compute="_compute_max_volume_m3",
        store=True,
    )

    description = fields.Text(string="Diễn giải")
    active = fields.Boolean(default=True)

    # VietMap Route v4 chỉ nhận đúng 4 nhóm xe này (đã tra tài liệu chính
    # thức) — capacity (tải trọng kg) chỉ áp dụng/được yêu cầu khi
    # vehicle=truck; 3 nhóm còn lại không nhận/không cần capacity.
    vietmap_vehicle_class = fields.Selection([
        ('motorcycle', 'Xe máy'),
        ('car', 'Xe con / xe tải nhẹ (không khai tải trọng)'),
        ('truck', 'Xe tải (khai tải trọng)'),
        ('container', 'Xe container'),
    ], string="Nhóm xe (VietMap)", default='truck', required=True,
        help="VietMap Route API chỉ nhận đúng 4 nhóm này để tính tuyến "
             "đúng luật (né đường cấm tải, hầm chui, giờ cấm...).")

    _WEIGHT_UNIT_TO_KG = {'kg': 1, 'ta': 100, 'tan': 1000}

    @api.depends("length_cm", "width_cm", "height_cm")
    def _compute_dimension_text(self):
        for rec in self:
            values = [rec.length_cm, rec.width_cm, rec.height_cm]
            if all(values):
                rec.dimension_text = "%s x %s x %s" % (
                    int(rec.length_cm),
                    int(rec.width_cm),
                    int(rec.height_cm),
                )
            else:
                rec.dimension_text = False

    @api.depends("length_cm", "width_cm", "height_cm")
    def _compute_max_volume_m3(self):
        for rec in self:
            if rec.length_cm and rec.width_cm and rec.height_cm:
                rec.max_volume_m3 = (
                    rec.length_cm * rec.width_cm * rec.height_cm
                ) / 1000000
            else:
                rec.max_volume_m3 = 0.0

    @api.onchange('weight_input_value', 'weight_input_unit')
    def _onchange_weight_input(self):
        for rec in self:
            if rec.weight_input_value:
                rec.max_weight_kg = (
                    rec.weight_input_value
                    * self._WEIGHT_UNIT_TO_KG.get(rec.weight_input_unit, 1))

    def _vietmap_route_params(self):
        """Trả (vehicle, capacity) đúng chuẩn VietMap Route v4 — capacity
        (kg) CHỈ gửi khi vehicle=truck (theo tài liệu VietMap, 3 nhóm xe
        khác không nhận/không cần tham số này)."""
        self.ensure_one()
        vehicle = self.vietmap_vehicle_class or 'truck'
        capacity = int(self.max_weight_kg) if vehicle == 'truck' and self.max_weight_kg else None
        return vehicle, capacity
