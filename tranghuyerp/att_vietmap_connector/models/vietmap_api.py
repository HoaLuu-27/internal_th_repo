import json
import logging
import time

import requests
from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class VietmapApi(models.AbstractModel):
    """Service gọi VietMap API — không tạo record, chỉ là helper.
    v1: search_address (Autocomplete v4) + get_place_detail (Place v4)."""
    _name = 'att.vietmap.api'
    _description = 'VietMap API Service'

    AUTOCOMPLETE_URL = 'autocomplete/v4'
    PLACE_URL = 'place/v4'
    ROUTE_V4_URL = 'route/v4'
    REVERSE_URL = 'reverse'


    def search_address(self, config, text):
        """Autocomplete v4 — trả list gợi ý thô cho dropdown.
        KHÔNG gọi place detail ở đây — chỉ gọi khi user chọn 1 gợi ý cụ thể
        (đúng khuyến nghị VietMap, tránh gọi place API cho mọi gợi ý hiển thị)."""
        if not text or len(text.strip()) < 3:
            return []
        url = '%s/%s' % (config.base_url.rstrip('/'), self.AUTOCOMPLETE_URL)
        params = {'apikey': config.api_key, 'text': text}
        # _logger.info('[VIETMAP DEBUG] search_address goi url=%s params=%s', url,
        #               {k: v for k, v in params.items() if k != 'apikey'})
        log = self._create_log(config, 'Search Address', url, params, query_text=text)
        started = time.time()
        try:
            response = requests.get(url, params=params, timeout=10)
            data = self._safe_json(response)
            # _logger.info('[VIETMAP DEBUG] search_address status=%s type(data)=%s data=%r',
            #              response.status_code, type(data).__name__, data)
            duration_ms = int((time.time() - started) * 1000)
            log.write({'response_code': response.status_code, 'duration_ms': duration_ms})
            if response.status_code >= 400:
                raise UserError(_('Tìm địa chỉ VietMap thất bại: %s') % data)
            log.action_mark_done(response.status_code, data)
            return data if isinstance(data, list) else []
        except Exception as e:
            log.action_mark_error(e)
            config._set_error(e)
            # Không raise UserError chặn UI — autocomplete lỗi thì trả rỗng,
            # để ô nhập vẫn dùng được như field text thường.
            # _logger.warning('[VIETMAP] search_address failed: %s', e)
            return []


    @api.model
    def search_address_ui(self, *args, **kwargs):
        """Wrapper gọi từ JS (orm.call) — tự tìm config active, JS không cần biết config.
        @api.model bắt buộc để call_kw không nuốt args[0] làm ids.
        TẠM để *args/**kwargs + log để debug RPC đang gửi lên cái gì (xem odoo.log)."""
        # _logger.info('[VIETMAP DEBUG] search_address_ui nhận args=%r kwargs=%r', args, kwargs)
        text = args[0] if args else kwargs.get('text')
        if not text:
            # _logger.warning('[VIETMAP DEBUG] search_address_ui KHÔNG nhận được text nào!')
            return []
        config = self.env['att.vietmap.config']._get_active_config()
        if not config:
            # _logger.warning('[VIETMAP DEBUG] không có config active nào (att.vietmap.config)')
            return []
        return self.search_address(config, text)



    def get_place_detail(self, config, ref_id):
        """Place v4 — gọi đúng 1 lần khi user chọn 1 gợi ý cụ thể, trả về
        toạ độ + địa chỉ hành chính chuẩn hoá."""
        if not ref_id:
            return {}
        url = '%s/%s' % (config.base_url.rstrip('/'), self.PLACE_URL)
        params = {'apikey': config.api_key, 'refid': ref_id}
        log = self._create_log(config, 'Get Place Detail', url, params, ref_id=ref_id)
        started = time.time()
        try:
            response = requests.get(url, params=params, timeout=10)
            data = self._safe_json(response)
            duration_ms = int((time.time() - started) * 1000)
            log.write({'response_code': response.status_code, 'duration_ms': duration_ms})
            if response.status_code >= 400:
                raise UserError(_('Lấy chi tiết địa điểm VietMap thất bại: %s') % data)
            log.action_mark_done(response.status_code, data)
            return data
        except Exception as e:
            log.action_mark_error(e)
            config._set_error(e)
            raise UserError(_('Không lấy được toạ độ từ VietMap: %s') % e)


    @api.model
    def get_place_detail_ui(self, ref_id):
        """Wrapper gọi từ JS — tự tìm config active. @api.model bắt buộc
        (cùng lý do search_address_ui)."""
        config = self.env['att.vietmap.config']._get_active_config()
        if not config:
            return {}
        return self.get_place_detail(config, ref_id)

    def reverse_geocode(self, config, lat, lng):
        """Reverse Geocode — suy ra tên địa chỉ hiển thị từ 1 toạ độ
        (lat, lng), dùng cho ô nhập "toạ độ" ở panel Tìm đường. Endpoint
        này KHÔNG theo dạng /v4 như autocomplete/place — dùng query param
        api-version riêng theo tài liệu chính thức
        (https://maps.vietmap.vn/docs/map-api/reverse/)."""
        url = '%s/%s' % (config.base_url.rstrip('/'), self.REVERSE_URL)
        params = {
            'apikey': config.api_key,
            'api-version': '1.1',
            'point.lat': lat,
            'point.lon': lng,
        }
        log = self._create_log(config, 'Reverse Geocode', url, params)
        started = time.time()
        try:
            response = requests.get(url, params=params, timeout=10)
            data = self._safe_json(response)
            duration_ms = int((time.time() - started) * 1000)
            log.write({'response_code': response.status_code, 'duration_ms': duration_ms})
            if response.status_code >= 400:
                raise UserError(_('Reverse geocode VietMap thất bại: %s') % data)
            log.action_mark_done(response.status_code, data)
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get('results') or data.get('data') or []
            else:
                items = []
            first = items[0] if items and isinstance(items[0], dict) else {}
            return {
                'name': first.get('display') or first.get('name') or first.get('address') or '',
                'lat': lat,
                'lng': lng,
            }
        except Exception as e:
            log.action_mark_error(e)
            config._set_error(e)
            raise UserError(_('Không lấy được tên địa chỉ từ toạ độ: %s') % e)

    @api.model
    def reverse_geocode_ui(self, lat, lng):
        """Wrapper gọi từ JS (ô nhập toạ độ ở panel Tìm đường) — tự tìm
        config active. @api.model bắt buộc (cùng lý do search_address_ui).
        Lỗi trả {'error': ...} thay vì raise — JS sẽ fallback dùng thẳng
        chuỗi toạ độ thô làm tên hiển thị, không chặn luồng tìm đường."""
        config = self.env['att.vietmap.config']._get_active_config()
        if not config:
            return {'error': _('Chưa cấu hình VietMap (không có config active).')}
        try:
            return self.reverse_geocode(config, lat, lng)
        except Exception as e:  # noqa: BLE001
            return {'error': str(e)}

    # ------------------------------------------------------------------
    def _safe_json(self, response):
        try:
            return response.json()
        except Exception:
            return {'raw_response': response.text}

    def _create_log(self, config, name, endpoint, params, query_text=False, ref_id=False):
        return self.env['att.vietmap.request.log'].sudo().create({
            'name': '[VIETMAP] %s' % name,
            'config_id': config.id,
            'endpoint': endpoint,
            'http_method': 'GET',
            'query_text': query_text,
            'ref_id': ref_id,
            'request_body': json.dumps(
                {k: v for k, v in params.items() if k != 'apikey'},  # không log API key
                ensure_ascii=False, indent=2),
        })



    def get_route_info(self, config, origin_lat, origin_lng, destination_lat, destination_lng,
                       vehicle='truck', capacity=None):
        """Gọi Route v4 kèm annotations=congestion,toll — trả khoảng cách, thời
        gian, và danh sách trạm thu phí đúng theo loại xe/tải trọng truyền vào."""
        url = '%s/%s' % (config.base_url.rstrip('/'), self.ROUTE_V4_URL)
        params = {
            'apikey': config.api_key,
            'point': ['%s,%s' % (origin_lat, origin_lng), '%s,%s' % (destination_lat, destination_lng)],
            'vehicle': vehicle,
            'annotations': 'congestion,toll',
            'points_encoded': 'false',
        }
        if capacity:
            params['capacity'] = capacity
        log = self._create_log(config, 'Get Route Info', url, params)
        started = time.time()
        try:
            response = requests.get(url, params=params, timeout=15)
            data = self._safe_json(response)
            log.write({'response_code': response.status_code,
                       'duration_ms': int((time.time() - started) * 1000)})
            if response.status_code >= 400 or data.get('code') != 'OK':
                raise UserError(_('Tính tuyến VietMap thất bại: %s') % data)
            log.action_mark_done(response.status_code, data)
            path = (data.get('paths') or [{}])[0]
            points_raw = path.get('points')
            # _logger.info('[VIETMAP DEBUG] get_route_info points_encoded=%r type(points)=%s points_preview=%r',
            #              path.get('points_encoded'), type(points_raw).__name__,
            #              (points_raw if not isinstance(points_raw, str) else points_raw[:200]))
            # TẠM debug — kiểm tra VietMap Route v4 có thực sự trả dữ liệu
            # tắc nghẽn (annotations=congestion đã gửi kèm request) hay
            # không, và ở dạng nào (details/segments theo index, hay field
            # riêng như 'tolls') — để quyết định có làm được tab "Gợi ý
            # tránh tắc" hay không. XOÁ log này sau khi xác nhận xong.
            # _logger.info('[VIETMAP DEBUG] get_route_info path_keys=%r details_keys=%r '
            #              'has_congestion_key=%s congestion_preview=%r',
            #              list(path.keys()),
            #              list((path.get('details') or {}).keys()) if isinstance(path.get('details'), dict) else path.get('details'),
            #              'congestion' in path,
            #              path.get('congestion'))
            return {
                'distance_km': round((path.get('distance') or 0) / 1000, 2),
                'eta_minutes': round((path.get('time') or 0) / 60000),
                'toll_cost': path.get('toll_cost') or 0,
                'tolls': [{
                    'name': t.get('name'), 'address': t.get('address'),
                    'type': t.get('type'), 'price': t.get('price'),
                    'lat': t.get('lat'), 'lng': t.get('lng'),
                } for t in (path.get('tolls') or [])],
                # [[lat, lng], ...] theo đúng thứ tự để vẽ polyline lên bản
                # đồ — đã đổi từ [lng, lat] (chuẩn GeoJSON VietMap/GraphHopper
                # trả về) sang [lat, lng] cho khớp quy ước lat trước dùng
                # xuyên suốt codebase (origin_lat, origin_lng...).
                'geometry': self._extract_route_geometry(path.get('points')),
                # Chỉ dẫn từng chặng (GraphHopper instructions) — cho panel
                # "Tìm đường" trên dashboard điều vận. Parse phòng thủ vì
                # VietMap không cam kết field này trong tài liệu công khai.
                'instructions': [{
                    'text': i.get('text') or '',
                    'distance_km': round((i.get('distance') or 0) / 1000, 2),
                    'time_minutes': round((i.get('time') or 0) / 60000, 1),
                    'street_name': i.get('street_name') or '',
                } for i in (path.get('instructions') or []) if isinstance(i, dict)],
                # Tắc nghẽn theo đoạn — annotations.congestion trả segment
                # {value: low/..., first, last} với first/last là CHỈ SỐ trỏ
                # vào mảng points (= 'geometry' ở trên, cùng thứ tự) → tô
                # màu được đúng đoạn đường theo mức tắc. congestion_distance
                # song song cùng index cho biết quãng đường mỗi đoạn.
                'congestion': self._extract_congestion(path.get('annotations')),
            }
        except Exception as e:
            log.action_mark_error(e)
            config._set_error(e)
            raise UserError(_('Không lấy được thông tin tuyến từ VietMap: %s') % e)

    @api.model
    def get_route_info_ui(self, origin_lat, origin_lng, destination_lat, destination_lng,
                          vehicle='truck', capacity=None):
        """Wrapper gọi từ JS (panel Tìm đường trên dashboard điều vận) —
        tự tìm config active. BẮT BUỘC @api.model: JS orm.call gửi args
        thuần không kèm ids, thiếu decorator này call_kw sẽ IndexError
        (đúng lỗi từng gặp với get_style_url_ui).
        Lỗi trả về dạng {'error': ...} thay vì raise — panel Tìm đường xử
        lý hiển thị inline, không muốn dialog lỗi đỏ của Odoo bung ra."""
        config = self.env['att.vietmap.config']._get_active_config()
        if not config:
            return {'error': _('Chưa cấu hình VietMap (không có config active).')}
        try:
            return self.get_route_info(config, origin_lat, origin_lng,
                                       destination_lat, destination_lng,
                                       vehicle=vehicle, capacity=capacity)
        except Exception as e:  # noqa: BLE001
            return {'error': str(e)}

    def _extract_congestion(self, annotations):
        """Chuẩn hoá annotations.congestion thành list
        [{'level', 'first', 'last', 'distance_km'}, ...]. Ghép thêm quãng
        đường từng đoạn từ congestion_distance (mảng song song cùng index)."""
        if not isinstance(annotations, dict):
            return []
        segments = annotations.get('congestion') or []
        distances = annotations.get('congestion_distance') or []
        result = []
        for i, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            dist_m = 0
            if i < len(distances) and isinstance(distances[i], dict):
                dist_m = distances[i].get('value') or 0
            result.append({
                'level': seg.get('value') or 'unknown',
                'first': seg.get('first') or 0,
                'last': seg.get('last') or 0,
                'distance_km': round(dist_m / 1000, 1),
            })
        return result

    def _extract_route_geometry(self, points_raw):
        """Chuẩn hoá field 'points' của Route v4 thành [[lat, lng], ...] —
        VietMap (nền GraphHopper) trả 1 trong 3 dạng tuỳ points_encoded:
        dict GeoJSON {'coordinates': [[lng,lat],...]}, list thô [[lng,lat],...],
        hoặc chuỗi polyline mã hoá (fallback giải mã tay nếu VietMap vẫn trả
        encode dù đã gửi points_encoded=false)."""
        if not points_raw:
            return []
        if isinstance(points_raw, dict):
            coords = points_raw.get('coordinates') or []
        elif isinstance(points_raw, str):
            coords = self._decode_polyline(points_raw)
        elif isinstance(points_raw, list):
            coords = points_raw
        else:
            coords = []
        return [[c[1], c[0]] for c in coords if len(c) >= 2]

    def _decode_polyline(self, encoded, precision=5):
        """Giải mã Encoded Polyline Algorithm Format chuẩn (Google/GraphHopper)
        — trả [[lng, lat], ...] (chưa đảo thứ tự, _extract_route_geometry lo
        việc đó) để dùng chung 1 chỗ đảo trục duy nhất."""
        index, lat, lng = 0, 0, 0
        coordinates = []
        factor = 10 ** precision
        length = len(encoded)
        while index < length:
            result, shift = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            dlat = ~(result >> 1) if result & 1 else (result >> 1)
            lat += dlat
            result, shift = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            dlng = ~(result >> 1) if result & 1 else (result >> 1)
            lng += dlng
            coordinates.append([lng / factor, lat / factor])
        return coordinates