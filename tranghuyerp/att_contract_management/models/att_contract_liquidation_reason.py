# -*- coding: utf-8 -*-
from odoo import fields, models


class AttContractLiquidationReason(models.Model):
    """Danh mục lý do thanh lý hợp đồng."""
    _name = 'att.contract.liquidation.reason'
    _description = 'Lý do thanh lý hợp đồng'
    _order = 'sequence, id'

    name = fields.Char('Lý do', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
