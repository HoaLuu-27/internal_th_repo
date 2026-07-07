from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

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

    sale_order_id = fields.Many2one(
        'sale.order',
        string='SO nguồn',
        related='att_contract_id.sale_order_id',
        store=True,
        readonly=True,
    )


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

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
        string='Loại xe',
    )
    transport_mode_id = fields.Many2one(
        "att.transport.mode",
        string="Hình thức vận chuyển",
    )

    cargo_description = fields.Text(
        string='Mô tả hàng hóa',
    )