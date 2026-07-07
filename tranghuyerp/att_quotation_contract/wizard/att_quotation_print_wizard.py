from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)


class QuotationPrintWizard(models.TransientModel):
    _name = 'att.quotation.print.wizard'
    _description = 'Chọn fields in báo giá'

    quotation_id = fields.Many2one('att.quotation.request', required=True)

    # ── Thông tin tuyến ──
    show_name = fields.Boolean('Nội dung vận chuyển', default=True)
    show_pickup = fields.Boolean('Điểm đi', default=True)
    show_delivery = fields.Boolean('Điểm đến', default=True)
    show_route_detail = fields.Boolean('Chi tiết điểm đi & đến', default=False)

    # ── Phương tiện ──
    show_vehicle_type = fields.Boolean('Loại xe/Phương tiện', default=False)
    show_vehicle_id = fields.Boolean('Phương tiện (Fleet)', default=False)
    show_transport_mode = fields.Boolean('Hình thức vận chuyển', default=False)

    # ── Số lượng & thời gian ──
    show_quantity = fields.Boolean('Số chuyến', default=True)
    show_uom = fields.Boolean('Đơn vị tính', default=True)
    show_expected_date = fields.Boolean('Thời gian dự kiến', default=False)

    # ── Hàng hóa ──
    show_cargo_description = fields.Boolean('Mô tả hàng hóa', default=False)

    # ── Giá ──
    show_price_unit = fields.Boolean('Đơn giá', default=True)
    show_tax = fields.Boolean('Thuế', default=False)
    show_price_subtotal = fields.Boolean('Thành tiền chưa thuế', default=False)
    show_price_total = fields.Boolean('Tổng tiền', default=False)

    # ── Khác ──
    show_note = fields.Boolean('Ghi chú', default=True)

    def action_do_print(self):
        self.ensure_one()
        return self.env.ref(
            'att_quotation_contract.action_report_att_quotation_request'
        ).report_action(
            self.quotation_id,
            data={
                'show_name': self.show_name,
                'show_pickup': self.show_pickup,
                'show_delivery': self.show_delivery,
                'show_route_detail': self.show_route_detail,
                'show_vehicle_type': self.show_vehicle_type,
                'show_vehicle_id': self.show_vehicle_id,
                'show_transport_mode': self.show_transport_mode,
                'show_quantity': self.show_quantity,
                'show_uom': self.show_uom,
                'show_expected_date': self.show_expected_date,
                'show_cargo_description': self.show_cargo_description,
                'show_price_unit': self.show_price_unit,
                'show_tax': self.show_tax,
                'show_price_subtotal': self.show_price_subtotal,
                'show_price_total': self.show_price_total,
                'show_note': self.show_note,
            },
        )

    def action_do_send(self):
        self.ensure_one()
        self.quotation_id._send_quotation_pdf({
            'show_name': self.show_name,
            'show_pickup': self.show_pickup,
            'show_delivery': self.show_delivery,
            'show_route_detail': self.show_route_detail,
            'show_vehicle_type': self.show_vehicle_type,
            'show_vehicle_id': self.show_vehicle_id,
            'show_transport_mode': self.show_transport_mode,
            'show_quantity': self.show_quantity,
            'show_uom': self.show_uom,
            'show_expected_date': self.show_expected_date,
            'show_cargo_description': self.show_cargo_description,
            'show_price_unit': self.show_price_unit,
            'show_tax': self.show_tax,
            'show_price_subtotal': self.show_price_subtotal,
            'show_price_total': self.show_price_total,
            'show_note': self.show_note,
        })
        return {'type': 'ir.actions.act_window_close'}