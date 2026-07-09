from odoo import fields, models


class FleetVehicle(models.Model):
    """current_to_id đặt ở att_transport_order (tham chiếu th.transport.order),
    giữ att_fleet_extend độc lập không phụ thuộc ngược."""
    _inherit = 'fleet.vehicle'

    current_to_id = fields.Many2one('att.transport.order', 'Lệnh đang thực hiện',
                                    compute='_compute_current_to')

    def _compute_current_to(self):
        for rec in self:
            rec.current_to_id = self.env['att.transport.order'].search([
                ('vehicle_id', '=', rec.id), ('state', '=', 'in_transit')], limit=1)
