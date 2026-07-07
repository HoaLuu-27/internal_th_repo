import logging
from odoo import models, fields, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)



class ContractLiquidationReason(models.Model):
    _name = 'att.contract.liquidation.reason'
    _description = 'Lý do thanh lý hợp đồng'
    _order = 'sequence, id'

    name = fields.Char('Lý do', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)