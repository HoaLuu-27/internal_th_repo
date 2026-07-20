import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class VietmapConfig(models.Model):
    """Cấu hình trung tâm cho VietMap Services.
    Giữ đơn giản như att.zalo.service.config — 1 config có thể đại diện cho
    nhiều "khả năng" (address, route, tolls...) sau này, không tách nhỏ."""
    _name = 'att.vietmap.config'
    _description = 'VietMap Service Configuration'
    _order = 'id desc'

    name = fields.Char('Tên cấu hình', required=True, default='VietMap Trang Huy', tracking=True)
    active = fields.Boolean('Hoạt động', default=True, tracking=True)
    api_key = fields.Char('API Key (REST)', groups='base.group_system', required=True,
                          help='API Key gọi các API REST (search/route/place...) — dùng ở '
                               'server Python, giữ bí mật, chỉ System xem được.')
    tile_map_api_key = fields.Char(
        'API Key (Tile map)',
        help='Key RIÊNG VietMap cấp cho hiển thị bản đồ (Keypro tile map) — dùng thẳng '
             'ở trình duyệt (JS), không giữ bí mật được nên VietMap tách riêng, giới hạn '
             'theo domain thay vì theo secret. KHÔNG dùng chung với API Key (REST) ở trên.')
    base_url = fields.Char('Base URL', default='https://maps.vietmap.vn/api',
                           help='Đổi ở đây nếu VietMap đổi domain/version, không sửa rải rác trong code.')

    # Debug
    debug_log = fields.Boolean('Bật debug log', default=True,
                               help='Nếu bật, lưu raw request/response để debug.')
    last_error = fields.Text('Lỗi gần nhất', readonly=True, copy=False)

    @api.model
    def _get_active_config(self):
        """Lấy config đang active — service/controller dùng hàm này, không
        query trực tiếp để sau này đổi logic (VD nhiều config theo company)
        chỉ cần sửa 1 chỗ."""
        return self.sudo().search([('active', '=', True)], limit=1)

    def action_test_connection(self):
        self.ensure_one()
        if not self.api_key:
            raise UserError(_('Chưa nhập API Key.'))
        result = self.env['att.vietmap.api'].sudo().search_address(self, 'Hà Nội')
        if not result:
            raise UserError(_('Gọi thử API không có kết quả — kiểm tra lại API Key.'))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('VietMap'),
                'message': _('Kết nối thành công — tìm thấy %d gợi ý cho "Hà Nội".') % len(result),
                'type': 'success',
                'sticky': False,
            }
        }

    @api.model
    def get_style_url_ui(self):
        """Trả URL style bản đồ (kèm key TILE MAP riêng, KHÔNG dùng api_key
        REST) để JS khởi tạo VietMap GL Map — sudo() vì field giới hạn nhóm
        System nhưng điều vận viên thường vẫn cần xem bản đồ."""
        config = self.sudo()._get_active_config()
        if not config or not config.tile_map_api_key:
            return False
        root = config.base_url.rstrip('/')
        if root.endswith('/api'):
            root = root[:-4]
        return '%s/maps/styles/tm/style.json?apikey=%s' % (root, config.tile_map_api_key)

    def _set_error(self, error):
        self.sudo().write({'last_error': str(error)})
        _logger.error('[VIETMAP CONFIG] %s', error)