from odoo import api, models


class ReportSaleQuotation(models.AbstractModel):
    """Bơm `data` (cấu hình cột rpt_show_*) vào context template báo giá SO.

    Không có abstract model này thì in từ nút Print biến `data` luôn là None
    → mọi checkbox cấu hình cột bị bỏ qua (bài học từ module cũ).
    """
    _name = 'report.att_quotations_contracts.report_attqc_sale_quotation'
    _description = 'Report Báo giá vận chuyển (Sale Order)'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['sale.order'].browse(docids)
        # In từ nút Print (không truyền data) → lấy cấu hình rpt_show_* lưu
        # trên chính SO để bản in khớp checkbox user đã tick
        if not data and len(docs) == 1:
            data = docs._get_report_data()
        return {
            'doc_ids': docids,
            'doc_model': 'sale.order',
            'docs': docs,
            'data': data or {},
        }
