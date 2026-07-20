import json
from odoo import fields, models


class VietmapTestWizard(models.TransientModel):
    """Form test nhanh API VietMap — gõ trực tiếp, không cần qua SO/PO."""
    _name = 'att.vietmap.test.wizard'
    _description = 'VietMap - Test nhanh API'

    query_text = fields.Char('Từ khoá tìm địa chỉ')
    ref_id = fields.Char('Ref ID (dán vào để test Place Detail)')
    result_json = fields.Text('Kết quả (JSON)', readonly=True)

    def action_test_search(self):
        self.ensure_one()
        result = self.env['att.vietmap.api'].search_address_ui(self.query_text or '')
        self.result_json = json.dumps(result, ensure_ascii=False, indent=2)
        return self._reopen()

    def action_test_place_detail(self):
        self.ensure_one()
        result = self.env['att.vietmap.api'].get_place_detail_ui(self.ref_id or '')
        self.result_json = json.dumps(result, ensure_ascii=False, indent=2)
        return self._reopen()

    def _reopen(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }