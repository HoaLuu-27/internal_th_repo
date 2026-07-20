from odoo import fields, models

# Ngưỡng coi xe "đang dừng" khi lâu không có toạ độ mới trong lúc đang chạy —
# tạm thời vì chưa có tín hiệu GPS thật (EUP) báo trực tiếp đang chạy/dừng.
# Field th_display_state KHÔNG store nên mỗi lần đọc lại (JS poll định kỳ ở
# màn Bản đồ nhiệt) sẽ tính lại đúng thời điểm hiện tại — khi tích hợp EUP
# xong (cập nhật toạ độ liên tục) thì trạng thái "dừng" tự chính xác hơn mà
# không cần sửa gì ở đây.
STALE_MINUTES = 15


class FleetVehicle(models.Model):
    """current_to_id đặt ở att_transport_orders (tham chiếu att.transport.order),
    giữ att_fleet_extend độc lập không phụ thuộc ngược."""
    _inherit = 'fleet.vehicle'

    current_to_id = fields.Many2one('att.transport.order', 'Lệnh đang thực hiện',
                                    compute='_compute_current_to')
    # Trạng thái hiển thị tổng hợp cho Bản đồ nhiệt — kết hợp state Lệnh vận
    # chuyển (kể cả lệnh mới confirmed, chưa in_transit) + độ mới của toạ độ
    # xe, KHÔNG phải state riêng trên att.transport.order (state đó giữ
    # nguyên 5 giá trị cũ, không đổi).
    th_display_state = fields.Selection([
        ('available', 'Sẵn sàng'),
        ('maintenance', 'Bảo dưỡng'),
        ('broken', 'Hỏng'),
        ('waiting_departure', 'Chờ xuất phát'),
        ('to_pickup_moving', 'Đến điểm bốc hàng'),
        ('to_pickup_stopped', 'Dừng (đến điểm bốc hàng)'),
        ('to_delivery_moving', 'Đến điểm giao hàng'),
        ('to_delivery_stopped', 'Dừng (đến điểm giao hàng)'),
        ('delivered_pending', 'Đã giao - chờ hoàn tất'),
    ], string='Trạng thái hiển thị (Realtime)', compute='_compute_th_display_state')
    # Lệnh gắn với th_display_state ở trên (confirmed HOẶC in_transit) — để
    # popup Bản đồ nhiệt link thẳng tới lệnh, KHÁC current_to_id (chỉ tính
    # in_transit, dùng cho mục đích khác trước đây).
    active_to_id = fields.Many2one('att.transport.order', 'Lệnh đang gắn (Realtime)',
                                   compute='_compute_th_display_state')

    def _compute_current_to(self):
        for rec in self:
            rec.current_to_id = self.env['att.transport.order'].search([
                ('vehicle_id', '=', rec.id), ('state', '=', 'in_transit')], limit=1)

    def _compute_th_display_state(self):
        for rec in self:
            if rec.th_state in ('maintenance', 'broken'):
                rec.th_display_state = rec.th_state
                rec.active_to_id = False
                continue
            # Lệnh đang "sống" của xe — kể cả confirmed (chưa bắt đầu chạy)
            # lẫn in_transit, KHÁC current_to_id (chỉ tính in_transit).
            order = self.env['att.transport.order'].search([
                ('vehicle_id', '=', rec.id),
                ('state', 'in', ('confirmed', 'in_transit')),
            ], limit=1)
            rec.active_to_id = order
            if not order:
                rec.th_display_state = 'available'
            elif order.state == 'confirmed':
                rec.th_display_state = 'waiting_departure'
            else:
                stale = not rec.current_position_updated or (
                    fields.Datetime.now() - rec.current_position_updated
                ).total_seconds() > STALE_MINUTES * 60
                if not order.source_confirmed:
                    rec.th_display_state = 'to_pickup_stopped' if stale else 'to_pickup_moving'
                elif not order.dest_confirmed:
                    rec.th_display_state = 'to_delivery_stopped' if stale else 'to_delivery_moving'
                else:
                    rec.th_display_state = 'delivered_pending'
