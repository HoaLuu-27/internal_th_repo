import json
import logging
import time
from urllib.parse import urlencode

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
    ROUTE_TOLLS_URL = 'route-tolls'
    REVERSE_URL = 'reverse'


    def search_address(self, config, text):
        """Autocomplete v4 — trả list gợi ý thô cho dropdown.
        KHÔNG gọi place detail ở đây — chỉ gọi khi user chọn 1 gợi ý cụ thể
        (đúng khuyến nghị VietMap, tránh gọi place API cho mọi gợi ý hiển thị)."""
        if not text or len(text.strip()) < 3:
            return []
        url = '%s/%s' % (config.base_url.rstrip('/'), self.AUTOCOMPLETE_URL)
        params = {'apikey': config.api_key, 'text': text}
        request_url, masked_url = self._build_request_url(url, params)
        log = self._create_log(config, 'Search Address', url, params, query_text=text,
                               full_url=masked_url)
        started = time.time()
        try:
            response = requests.get(request_url, timeout=10)
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
        request_url, masked_url = self._build_request_url(url, params)
        log = self._create_log(config, 'Get Place Detail', url, params, ref_id=ref_id,
                               full_url=masked_url)
        started = time.time()
        try:
            response = requests.get(request_url, timeout=10)
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
        request_url, masked_url = self._build_request_url(url, params)
        log = self._create_log(config, 'Reverse Geocode', url, params, full_url=masked_url)
        started = time.time()
        try:
            response = requests.get(request_url, timeout=10)
            data = self._safe_json(response)
            duration_ms = int((time.time() - started) * 1000)
            log.write({'response_code': response.status_code, 'duration_ms': duration_ms})
            if response.status_code >= 400:
                raise UserError(_('Reverse geocode VietMap thất bại: %s') % data)
            log.action_mark_done(response.status_code, data)
            return {
                'name': self._extract_reverse_name(data),
                'lat': lat,
                'lng': lng,
            }
        except Exception as e:
            log.action_mark_error(e)
            config._set_error(e)
            raise UserError(_('Không lấy được tên địa chỉ từ toạ độ: %s') % e)

    def _extract_reverse_name(self, data):
        """Reverse geocode KHÔNG có tài liệu công khai mô tả rõ shape JSON
        (không giống autocomplete/place có ví dụ cụ thể) — thử lần lượt
        các dạng phổ biến: list thô, dict {results|data|features: [...]},
        và mỗi item có thể phẳng (như autocomplete) HOẶC kiểu GeoJSON
        Feature (dữ liệu thật nằm trong "properties", theo chuẩn
        Pelias/GraphHopper mà nhiều field VietMap khác cũng dựa trên).

        XÁC NHẬN THẬT qua Request Log — response có 2 lớp bọc kiểu
        {"code": "OK", "data": {"features": [...]}} (giống Route v4 bọc
        {code, message, paths}), mỗi feature là GeoJSON Feature với dữ
        liệu nằm trong "properties" (name/label/address, KHÔNG có field
        "display" như autocomplete/place)."""
        payload = data
        # Bóc lớp vỏ {code, message, data: {...}} — "data" lồng bên trong
        # LÀ dict (chứa "features"), khác payload top-level có thể LÀ list.
        if isinstance(payload, dict) and isinstance(payload.get('data'), (dict, list)):
            payload = payload['data']
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            items = payload.get('features') or payload.get('results') or []
        else:
            items = []
        if not items or not isinstance(items[0], dict):
            return ''
        first = items[0]
        props = first.get('properties') if isinstance(first.get('properties'), dict) else first
        # address ưu tiên trước label/name vì address là chuỗi ĐẦY ĐỦ
        # (tên + phường/xã + tỉnh/thành), còn label/name chỉ là tên ngắn.
        return (
            props.get('display') or props.get('address') or props.get('label')
            or props.get('name') or props.get('formatted_address') or ''
        )

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

    def _build_request_url(self, url, params):
        """Build URL đầy đủ THEO ĐÚNG CÁCH request thật sẽ gửi — safe=','
        giữ dấu phẩy nguyên văn (không percent-encode thành %2C), khớp
        đúng cách Postman gửi. XÁC NHẬN THẬT: VietMap parse sai toạ độ nếu
        dấu phẩy trong 'point' bị encode %2C (server tách bằng dấu phẩy
        TRƯỚC KHI url-decode) — lỗi 'Cannot find point'. Áp dụng chung cho
        MỌI param (không riêng 'point') để nhất quán, tránh lặp lại bug
        tương tự với param khác có dấu phẩy (VD annotations=congestion,toll).
        Trả về (request_url, masked_url) — masked_url che apikey để log an
        toàn, request_url dùng để gọi requests.get() thật."""
        request_url = '%s?%s' % (url, urlencode(params, doseq=True, safe=','))
        masked_params = dict(params)
        if 'apikey' in masked_params:
            masked_params['apikey'] = '***'
        masked_url = '%s?%s' % (url, urlencode(masked_params, doseq=True, safe=','))
        return request_url, masked_url

    def _create_log(self, config, name, endpoint, params, query_text=False, ref_id=False,
                    full_url=False):
        return self.env['att.vietmap.request.log'].sudo().create({
            'name': '[VIETMAP] %s' % name,
            'config_id': config.id,
            'endpoint': endpoint,
            'full_url': full_url,
            'http_method': 'GET',
            'query_text': query_text,
            'ref_id': ref_id,
            'request_body': json.dumps(
                {k: v for k, v in params.items() if k != 'apikey'},  # không log API key
                ensure_ascii=False, indent=2),
        })



    def _compute_vehicle_type_1_5(self, vehicle, capacity_kg):
        """Suy vehicle_type (1-5) cho /route-tolls từ vehicle+capacity —
        CÔNG THỨC LẤY NGUYÊN TỪ CODE PRODUCTION THẬT của Trang Huy
        (tranghuy_vietmaps_dashboard/models/vietmap_dashboard.py,
        calculate_route()). Chỉ car/truck có toll chính xác qua route-tolls
        (đúng như code gốc: toll_supported = vehicle in ('car', 'truck'))
        — motorcycle/container CHƯA hỗ trợ: container cần biết kích cỡ
        cont (20ft/40ft) mới suy đúng Loại 4/5, hiện chưa có field đó trên
        fleet.vehicle/Lệnh vận chuyển."""
        if vehicle == 'car':
            return 1
        if vehicle != 'truck':
            return None
        weight_kg = capacity_kg or 0
        if weight_kg >= 18000:
            return 5
        if weight_kg >= 10000:
            return 4
        if weight_kg >= 4000:
            return 3
        if weight_kg >= 2000:
            return 2
        return 1

    def get_route_tolls(self, config, geometry, vehicle_type):
        """POST /route-tolls — phí BOT CHÍNH XÁC theo đúng tuyến vừa tính
        (khác toll_cost/tolls có sẵn trong Route v4 — chỉ ước lượng thô
        theo vehicle=truck/container, KHÔNG phân biệt được tải trọng/kích
        cỡ cont chi tiết theo đúng bảng Loại 1-5 chính thức của BOT VN).
        Lấy đúng pattern THẬT đã chạy production của Trang Huy
        (_calculate_single_route_toll): gửi geometry [lng,lat] của tuyến
        vừa tính, sample tối đa 100 điểm (API không xử lý tốt geometry quá
        dày). Trả None nếu lỗi/không hỗ trợ — get_route_info() sẽ tự fallback
        về toll_cost/tolls gốc của Route v4, KHÔNG chặn cả luồng tìm đường."""
        if not geometry or vehicle_type is None:
            return None
        url = '%s/%s' % (config.base_url.rstrip('/'), self.ROUTE_TOLLS_URL)
        coords = [[lng, lat] for lat, lng in geometry]  # geometry lưu [lat,lng] — route-tolls cần [lng,lat]
        if len(coords) > 100:
            step = len(coords) // 100
            sampled = coords[::step]
            if sampled[-1] != coords[-1]:
                sampled.append(coords[-1])
            coords = sampled
        params = {'apikey': config.api_key, 'vehicle': vehicle_type}
        request_url, masked_url = self._build_request_url(url, params)
        log = self._create_log(config, 'Get Route Tolls', url, params, full_url=masked_url)
        started = time.time()
        try:
            response = requests.post(request_url, json=coords, timeout=15)
            data = self._safe_json(response)
            log.write({'response_code': response.status_code,
                       'duration_ms': int((time.time() - started) * 1000)})
            if response.status_code >= 400:
                log.action_mark_error('HTTP %s: %s' % (response.status_code, data))
                return None
            log.action_mark_done(response.status_code, data)
            tolls = data.get('tolls') or []
            return {
                'toll_cost': sum(t.get('price', 0) or 0 for t in tolls),
                'tolls': [{
                    'name': t.get('name'), 'address': t.get('address'),
                    'type': t.get('type'), 'price': t.get('price'),
                    'lat': t.get('lat'), 'lng': t.get('lng'),
                } for t in tolls],
            }
        except Exception as e:  # noqa: BLE001
            log.action_mark_error(e)
            return None

    def get_route_info(self, config, origin_lat, origin_lng, destination_lat, destination_lng,
                       vehicle='truck', capacity=None, departure_time=None, via_points=None):
        """Gọi Route v4 kèm annotations=congestion,toll — trả khoảng cách, thời
        gian, và danh sách trạm thu phí đúng theo loại xe/tải trọng truyền vào.

        departure_time: chuỗi ISO-8601 UTC (VD '2026-07-20T17:00:00Z') — XÁC
        NHẬN THẬT qua test Postman+VietMap support: KHÔNG gửi thì VietMap tự
        lấy giờ THỰC lúc gọi API để tính giờ cấm tải, có thể làm route lỗi
        'Connection between locations not found' dù tuyến hợp lệ (chỉ vì
        đang gọi đúng khung giờ cấm tải thật, không liên quan tới giờ xe
        THẬT SỰ sẽ chạy). route_finder.js luôn gửi departure_time do người
        dùng chọn; action_resolve_route_info() (transport_route.py) không
        truyền — giữ hành vi cũ (mặc định giờ hiện tại).
        via_points: list [(lat, lng), ...] điểm dừng giữa đường (tuỳ chọn,
        VietMap gọi là 'via points' — chèn giữa origin và destination theo
        đúng thứ tự trong danh sách point= gửi lên)."""
        url = '%s/%s' % (config.base_url.rstrip('/'), self.ROUTE_V4_URL)
        points = ['%s,%s' % (origin_lat, origin_lng)]
        for via_lat, via_lng in (via_points or []):
            points.append('%s,%s' % (via_lat, via_lng))
        points.append('%s,%s' % (destination_lat, destination_lng))
        params = {
            'apikey': config.api_key,
            'point': points,
            'vehicle': vehicle,
            'annotations': 'congestion,toll',
            'points_encoded': 'false',
        }
        if capacity:
            params['capacity'] = capacity
        if departure_time:
            params['time'] = departure_time
        request_url, masked_url = self._build_request_url(url, params)
        log = self._create_log(config, 'Get Route Info', url, params, full_url=masked_url)
        started = time.time()
        try:
            response = requests.get(request_url, timeout=15)
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
            # [[lat, lng], ...] theo đúng thứ tự để vẽ polyline lên bản đồ —
            # đã đổi từ [lng, lat] (chuẩn GeoJSON VietMap/GraphHopper trả về)
            # sang [lat, lng] cho khớp quy ước lat trước dùng xuyên suốt
            # codebase (origin_lat, origin_lng...).
            geometry = self._extract_route_geometry(path.get('points'))
            toll_cost = path.get('toll_cost') or 0
            tolls = [{
                'name': t.get('name'), 'address': t.get('address'),
                'type': t.get('type'), 'price': t.get('price'),
                'lat': t.get('lat'), 'lng': t.get('lng'),
            } for t in (path.get('tolls') or [])]
            # Gọi thêm /route-tolls để lấy phí BOT CHÍNH XÁC hơn theo đúng
            # tuyến vừa tính + đúng Loại 1-5 (phân biệt tải trọng chi tiết,
            # Route v4's toll_cost/tolls chỉ ước lượng thô theo
            # vehicle=truck/container chung chung) — pattern THẬT từ
            # production Trang Huy. Chỉ car/truck được hỗ trợ (xem
            # _compute_vehicle_type_1_5); lỗi/không hỗ trợ thì get_route_tolls
            # trả None, GIỮ NGUYÊN toll_cost/tolls gốc của Route v4, không
            # chặn luồng tìm đường.
            vehicle_type = self._compute_vehicle_type_1_5(vehicle, capacity)
            refined = self.get_route_tolls(config, geometry, vehicle_type)
            if refined is not None:
                toll_cost = refined['toll_cost']
                tolls = refined['tolls']
            return {
                'distance_km': round((path.get('distance') or 0) / 1000, 2),
                'eta_minutes': round((path.get('time') or 0) / 60000),
                'toll_cost': toll_cost,
                'tolls': tolls,
                'geometry': geometry,
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
                'congestion': self._extract_congestion(
                    path.get('annotations'), path.get('instructions')),
            }
        except Exception as e:
            log.action_mark_error(e)
            config._set_error(e)
            raise UserError(_('Không lấy được thông tin tuyến từ VietMap: %s') % e)

    @api.model
    def get_route_info_ui(self, origin_lat, origin_lng, destination_lat, destination_lng,
                          vehicle='truck', capacity=None, departure_time=None, via_points=None):
        """Wrapper gọi từ JS (panel Tìm đường) — tự tìm config active. BẮT
        BUỘC @api.model: JS orm.call gửi args thuần không kèm ids, thiếu
        decorator này call_kw sẽ IndexError (đúng lỗi từng gặp với
        get_style_url_ui).
        departure_time: chuỗi ISO-8601 UTC, JS tự quy đổi từ giờ local qua
        Date.toISOString() — xem get_route_info() để biết lý do bắt buộc
        gửi (tránh dính giờ cấm tải THỰC lúc gọi API thay vì giờ xe THẬT
        SỰ chạy).
        via_points: list [[lat, lng], ...] điểm dừng giữa đường, JS gửi
        dạng mảng con (orm.call không truyền được tuple).
        Lỗi trả về dạng {'error': ...} thay vì raise — panel Tìm đường xử
        lý hiển thị inline, không muốn dialog lỗi đỏ của Odoo bung ra."""
        config = self.env['att.vietmap.config']._get_active_config()
        if not config:
            return {'error': _('Chưa cấu hình VietMap (không có config active).')}
        try:
            return self.get_route_info(
                config, origin_lat, origin_lng, destination_lat, destination_lng,
                vehicle=vehicle, capacity=capacity, departure_time=departure_time,
                via_points=[(p[0], p[1]) for p in (via_points or [])])
        except Exception as e:  # noqa: BLE001
            return {'error': str(e)}

    def _extract_congestion(self, annotations, instructions=None):
        """Chuẩn hoá annotations.congestion thành list
        [{'level', 'first', 'last', 'distance_km', 'street_name'}, ...]. Ghép
        thêm quãng đường từng đoạn từ congestion_distance (mảng song song
        cùng index), và tên đường bằng cách khớp first/last với
        instructions[].interval (xem _match_street_name)."""
        if not isinstance(annotations, dict):
            return []
        segments = annotations.get('congestion') or []
        distances = annotations.get('congestion_distance') or []
        instructions = instructions or []
        result = []
        for i, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            dist_m = 0
            if i < len(distances) and isinstance(distances[i], dict):
                dist_m = distances[i].get('value') or 0
            first = seg.get('first') or 0
            last = seg.get('last') or 0
            result.append({
                'level': seg.get('value') or 'unknown',
                'first': first,
                'last': last,
                'distance_km': round(dist_m / 1000, 1),
                'street_name': self._match_street_name(first, last, instructions),
            })
        return result

    def _match_street_name(self, first, last, instructions):
        """Khớp 1 đoạn tắc nghẽn (chỉ số first/last trỏ vào mảng points) với
        tên đường trong instructions — ĐÃ XÁC NHẬN qua Request Log thật:
        instructions[].interval=[start, end] dùng CHUNG hệ chỉ số điểm với
        congestion[].first/last (cùng trỏ vào path.points). Vì cùng 1 hệ
        chỉ số nên so đè khoảng chỉ số là khớp chính xác — KHÔNG cần so
        thêm distance (đơn vị mét, không liên quan tới việc khớp vị trí).
        Chọn instruction có phần đè lên NHIỀU nhất; bỏ qua instruction rẽ/
        vòng xoay không có street_name."""
        best_name, best_overlap = '', -1
        for instr in instructions:
            if not isinstance(instr, dict):
                continue
            street = instr.get('street_name')
            interval = instr.get('interval')
            if not street or not isinstance(interval, list) or len(interval) != 2:
                continue
            overlap = min(last, interval[1]) - max(first, interval[0])
            if overlap >= 0 and overlap > best_overlap:
                best_overlap = overlap
                best_name = street
        return best_name

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