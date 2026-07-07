from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    att_contract_id = fields.Many2one(
        'att.contract',
        string='Hợp đồng',
        copy=False,
        index=True,
        readonly=True,
    )

    att_appendix_id = fields.Many2one(
        'att.contract.appendix',
        string='Phụ lục',
        copy=False,
        index=True,
        readonly=True,
    )

    att_quotation_request_id = fields.Many2one(
        'att.quotation.request',
        string='Yêu cầu báo giá',
        related='att_contract_id.source_quotation_id',
        store=True,
        readonly=True,
    )


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    att_appendix_line_id = fields.Many2one(
        'att.contract.appendix.line',
        string='Dòng phụ lục',
        copy=False,
        readonly=True,
        index=True,
    )

    pickup_location = fields.Char(
        string='Điểm đi',
    )

    delivery_location = fields.Char(
        string='Điểm đến',
    )

    route_detail = fields.Char(
        string='Chi tiết điểm đi & điểm đến',
    )

    vehicle_id = fields.Many2one(
        'fleet.vehicle',
        string='Phương tiện',
    )

    vehicle_type = fields.Char(
        string='Loại xe',
    )

    cargo_description = fields.Text(
        string='Mô tả hàng hóa',
    )
    transport_mode_id = fields.Many2one(
        "att.transport.mode",
        string="Hình thức vận chuyển",
    )