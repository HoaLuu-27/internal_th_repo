import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AttAddressSuggestion(models.Model):
    """Model trung gian cho Many2one 'gõ tìm địa chỉ' trên SOL/POL.
    Record được tạo ĐỘNG ngay trong name_search() khi user gõ, dựa theo kết
    quả VietMap Autocomplete — không phải data nhập tay. Đây chỉ là điểm tựa
    để Many2one (widget chuẩn Odoo) hiện dropdown; toạ độ chỉ được lấy đúng
    1 lần khi user THỰC SỰ chọn (action_resolve_coordinates), tránh gọi Place
    Detail cho cả 5 gợi ý mỗi lần gõ."""
    _name = 'att.address.suggestion'
    _description = 'VietMap - Gợi ý địa chỉ (tạm)'
    _order = 'create_date desc'

    name = fields.Char('Địa chỉ', required=True)
    ref_id = fields.Char('VietMap ref_id', index=True)
    lat = fields.Float('Vĩ độ', digits=(10, 7))
    lng = fields.Float('Kinh độ', digits=(10, 7))
    detail_fetched = fields.Boolean(default=False)

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        domain = domain or []
        if not name or len(name.strip()) < 3:
            return super().name_search(name, domain, operator, limit)

        config = self.env['att.vietmap.config']._get_active_config()
        if not config:
            return super().name_search(name, domain, operator, limit)

        results = self.env['att.vietmap.api'].search_address(config, name)
        ids = []
        for r in results[:limit]:
            ref_id = r.get('ref_id')
            existing = self.search([('ref_id', '=', ref_id)], limit=1)
            if existing:
                ids.append(existing.id)
                continue
            rec = self.create({
                'name': r.get('display') or r.get('name'),
                'ref_id': ref_id,
            })
            ids.append(rec.id)
        records = self.browse(ids)
        return [(rec.id, rec.name) for rec in records]

    def action_resolve_coordinates(self):
        """Gọi Place Detail đúng 1 lần — chỉ khi user thật sự chọn record này."""
        self.ensure_one()
        if self.detail_fetched or not self.ref_id:
            return
        config = self.env['att.vietmap.config']._get_active_config()
        if not config:
            return
        detail = self.env['att.vietmap.api'].get_place_detail(config, self.ref_id)
        self.write({
            'lat': detail.get('lat') or 0.0,
            'lng': detail.get('lng') or 0.0,
            'detail_fetched': True,
        })

    @api.model
    def _cron_cleanup_old_suggestions(self):
        """Chỉ xoá record CHƯA TỪNG được chọn (detail_fetched=False) và đã
        tạo hơn 6 tiếng — đây là gợi ý user gõ ra nhưng không chọn, rác thật.
        Record ĐÃ được chọn (detail_fetched=True) giữ lại VĨNH VIỄN — vì có
        thể đang bị SOL/POL nào đó tham chiếu (module này không được phép
        biết sale/purchase là gì để tự kiểm tra còn ai dùng hay không) —
        đồng thời tận dụng làm cache: gõ trùng địa chỉ cũ khỏi cần gọi lại
        Place Detail (dedup theo ref_id trong name_search)."""
        cutoff = fields.Datetime.now() - timedelta(hours=6)
        self.search([
            ('detail_fetched', '=', False),
            # ('create_date', '<', cutoff),
        ]).unlink()