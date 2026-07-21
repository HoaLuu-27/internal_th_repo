/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { Component, useState, onWillStart, onWillUnmount, markup } from "@odoo/owl";
import { VietmapMap } from "@att_vietmap_connector/js/vietmap_widget";

// Cache cấp MODULE — sống qua các lần unmount/remount component (user bấm
// "Tạo báo giá" sang SO/PO rồi back về màn Bản đồ): giữ nguyên toạ độ/địa
// chỉ đã nhập + tuyến đã tìm, không bắt nhập lại. Mất khi tải lại cả trang
// (F5) — chấp nhận được.
const searchStateCache = { data: null };

// Icon nhỏ (đơn sắc, fill="currentColor" — tự đổi màu theo CSS nút đang
// active/không) cho 4 nút chọn loại xe — theo yêu cầu user, KHÁC quy tắc
// "không icon trang trí" mặc định vì đây là icon CHỨC NĂNG (chọn loại xe),
// không phải icon trang trí, giống icon xe vẽ trên bản đồ.
const ICON_CAR = markup(
    '<svg viewBox="0 0 20 16" width="18" height="15" fill="currentColor">' +
    '<path d="M5 6 Q7 2 12 2 Q15 2 16 6 Z"/>' +
    '<rect x="2" y="6" width="16" height="5" rx="2"/>' +
    '<circle cx="6" cy="12.5" r="2" fill="#fff"/><circle cx="6" cy="12.5" r="2" fill="none" stroke="currentColor"/>' +
    '<circle cx="15" cy="12.5" r="2" fill="#fff"/><circle cx="15" cy="12.5" r="2" fill="none" stroke="currentColor"/>' +
    '</svg>'
);
const ICON_MOTORCYCLE = markup(
    '<svg viewBox="0 0 20 16" width="18" height="15" fill="none" stroke="currentColor" stroke-width="1.5">' +
    '<circle cx="4.5" cy="12" r="3"/><circle cx="15.5" cy="12" r="3"/>' +
    '<path d="M4.5 12 L9 6 L13 6 L15.5 12" stroke-linecap="round" stroke-linejoin="round"/>' +
    '</svg>'
);
const ICON_TRUCK = markup(
    '<svg viewBox="0 0 20 16" width="18" height="15" fill="currentColor">' +
    '<rect x="1" y="4" width="9" height="7" rx="1"/>' +
    '<path d="M10 6 L15 6 L17.5 9 L17.5 11 L10 11 Z"/>' +
    '<circle cx="5" cy="12.5" r="1.8" fill="#fff"/><circle cx="5" cy="12.5" r="1.8" fill="none" stroke="currentColor"/>' +
    '<circle cx="14" cy="12.5" r="1.8" fill="#fff"/><circle cx="14" cy="12.5" r="1.8" fill="none" stroke="currentColor"/>' +
    '</svg>'
);
const ICON_CONTAINER = markup(
    '<svg viewBox="0 0 20 16" width="18" height="15" fill="currentColor">' +
    '<rect x="0.5" y="4" width="13" height="7" rx="0.5"/>' +
    '<path d="M13 6 L17 6 L18.5 8.5 L18.5 11 L13 11 Z"/>' +
    '<circle cx="4" cy="12.5" r="1.6" fill="#fff"/><circle cx="4" cy="12.5" r="1.6" fill="none" stroke="currentColor"/>' +
    '<circle cx="9" cy="12.5" r="1.6" fill="#fff"/><circle cx="9" cy="12.5" r="1.6" fill="none" stroke="currentColor"/>' +
    '<circle cx="16" cy="12.5" r="1.6" fill="#fff"/><circle cx="16" cy="12.5" r="1.6" fill="none" stroke="currentColor"/>' +
    '</svg>'
);

// 4 nhóm xe VietMap Route v4 chấp nhận — nút chọn trên panel Tìm đường.
const VIETMAP_VEHICLE_CLASSES = [
    { key: "car", label: "Ô tô", icon: ICON_CAR },
    { key: "motorcycle", label: "Xe máy", icon: ICON_MOTORCYCLE },
    { key: "truck", label: "Xe tải", icon: ICON_TRUCK },
    { key: "container", label: "Container", icon: ICON_CONTAINER },
];
// Mức tắc nghẽn VietMap trả trong annotations.congestion — màu theo quy
// ước bản đồ giao thông quen mắt (xanh thông → vàng → cam → đỏ tắc).
// Key lạ chưa gặp sẽ rơi về unknown (xanh dương như line thường).
const CONGESTION_LEVELS = {
    low: { label: "Thông thoáng", color: "#2fa14f" },
    moderate: { label: "Đông nhẹ", color: "#f2c744" },
    medium: { label: "Đông vừa", color: "#f2c744" },
    heavy: { label: "Đông đúc", color: "#f0812e" },
    high: { label: "Đông đúc", color: "#f0812e" },
    severe: { label: "Tắc nghẽn", color: "#e0231f" },
    unknown: { label: "Không rõ", color: "#1a56c4" },
};

// Khung giờ cao điểm — CHỈ CẢNH BÁO CHUNG, không phải xác nhận chính xác
// "giờ cấm tải" theo từng con đường (VietMap KHÔNG có API cho biết đúng
// đoạn đường nào cấm tải giờ nào — banner đỏ trên web VietMap là tính
// năng riêng của họ, không public qua API). Lấy đúng khung giờ mặc định
// từ code production thật của Trang Huy
// (tranghuy_vietmaps_core.peak_hours: '07:00-09:00,16:30-19:00').
const PEAK_HOUR_RANGES = [[7 * 60, 9 * 60], [16 * 60 + 30, 19 * 60]];

// Công cụ "Tìm đường & Báo giá" — tách ra từ dashboard Điều vận để Sales/
// Purchase dùng được mà không cần cài att_transport_orders. Chỉ gồm: bản
// đồ trơn + panel Tìm đường (địa chỉ/toạ độ) + tạo báo giá từ tuyến vừa
// tìm. KHÔNG có danh sách Lệnh/Xe/Chi phí/heat layer mật độ — những phần
// đó thuộc nghiệp vụ điều vận, ở lại att_transport_orders.
//
// LƯU Ý phụ thuộc chéo: createQuotationFromSearch() gọi RPC thẳng tới
// sale.order.action_new_quotation_for_route / purchase.order.
// action_new_rfq_for_route — 2 method này định nghĩa ở att_transport_orders
// (kéo theo field pickup/delivery mở rộng trên SOL/POL), KHÔNG di chuyển
// sang đây. Module này không depends Python vào att_transport_orders (tránh
// vòng lặp vì att_transport_orders đã depends att_vietmap_connector) —
// RPC vẫn chạy bình thường miễn att_transport_orders được cài cùng DB.
export class RouteFinderDashboard extends Component {
    static template = "att_vietmap_connector.RouteFinderDashboard";
    static components = { VietmapMap };
    // Client action — framework tự truyền action/actionId/updateActionState/
    // className, khai props rỗng/cụ thể sẽ bị Owl validate từ chối.
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            search: searchStateCache.data || {
                inputMode: "address", // address | coords
                vehicleClass: "truck",
                capacityKg: "",
                originText: "",
                destText: "",
                originSuggestions: [],
                destSuggestions: [],
                originCoords: "",
                destCoords: "",
                origin: null,      // {name, lat, lng}
                dest: null,
                // Điểm dừng giữa đường (via points) — mỗi phần tử:
                // {text, coords, suggestions, point}, cùng shape gốc/đích
                // để tái dùng chung được logic resolve toạ độ/địa chỉ.
                viaPoints: [],
                // Giờ khởi hành — BẮT BUỘC gửi lên VietMap (xem
                // vietmap_api.py get_route_info) để tránh dính giờ cấm tải
                // THỰC lúc bấm tìm thay vì giờ xe THẬT SỰ sẽ chạy. Tách
                // riêng ngày (input type=date) + giờ dạng text "HH:mm" 24h
                // TỰ KIỂM SOÁT — không dùng input type=datetime-local/time
                // vì trình duyệt tự hiển thị 12h/24h theo locale hệ điều
                // hành, không ép được luôn 24h qua HTML/CSS.
                departureDate: this._defaultDepartureDate(),
                departureTimeStr: this._defaultDepartureTimeStr(),
                searching: false,
                error: "",
                result: null,      // kết quả get_route_info_ui
                section: "directions", // directions | tolls | congestion
            },
        });
        this._suggestTimers = {};

        onWillStart(async () => {
            const [canSale, canPurchase] = await Promise.all([
                user.hasGroup("sales_team.group_sale_salesman"),
                user.hasGroup("purchase.group_purchase_user"),
            ]);
            this.state.canSaleQuote = canSale;
            this.state.canPurchaseQuote = canPurchase;
        });
        onWillUnmount(() => {
            // Chụp lại trạng thái tìm đường trước khi component bị huỷ —
            // toRaw không có sẵn nên clone JSON (bỏ reactive proxy) cho an
            // toàn; searching luôn reset false để không kẹt nút "Đang tìm".
            const snap = JSON.parse(JSON.stringify(this.state.search));
            snap.searching = false;
            searchStateCache.data = snap;
        });
    }

    get vehicleClasses() {
        return VIETMAP_VEHICLE_CLASSES;
    }

    // Cảnh báo tham khảo — giờ khởi hành (đã nhập, local VN) rơi vào
    // khung giờ cao điểm chung, KHÔNG khẳng định chính xác tuyến/đoạn
    // đường cụ thể có bị cấm tải hay không (xem giải thích ở
    // PEAK_HOUR_RANGES).
    get isPeakHour() {
        const m = (this.state.search.departureTimeStr || "").match(/^(\d{2}):(\d{2})$/);
        if (!m) {
            return false;
        }
        const minutes = parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
        return PEAK_HOUR_RANGES.some(([start, end]) => minutes >= start && minutes < end);
    }

    pickVehicleClass(key) {
        this.state.search.vehicleClass = key;
    }

    setInputMode(mode) {
        this.state.search.inputMode = mode;
        this.state.search.error = "";
    }

    // Ngày/giờ hiện tại theo giờ LOCAL trình duyệt — KHÔNG dùng
    // toISOString() ở đây vì nó trả UTC (lệch múi giờ so với ô nhập).
    _defaultDepartureDate() {
        const now = new Date();
        const pad = (n) => String(n).padStart(2, "0");
        return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    }

    _defaultDepartureTimeStr() {
        const now = new Date();
        const pad = (n) => String(n).padStart(2, "0");
        return `${pad(now.getHours())}:${pad(now.getMinutes())}`;
    }

    // Đảo điểm đi <-> điểm đến (địa chỉ/toạ độ đã nhập lẫn điểm đã resolve).
    swapPoints() {
        const s = this.state.search;
        [s.originText, s.destText] = [s.destText, s.originText];
        [s.originCoords, s.destCoords] = [s.destCoords, s.originCoords];
        [s.origin, s.dest] = [s.dest, s.origin];
        s.originSuggestions = [];
        s.destSuggestions = [];
    }

    addViaPoint() {
        this.state.search.viaPoints.push({ text: "", coords: "", suggestions: [], point: null });
    }

    removeViaPoint(index) {
        this.state.search.viaPoints.splice(index, 1);
    }

    onViaAddressInput(index, ev) {
        const text = ev.target.value;
        const via = this.state.search.viaPoints[index];
        via.text = text;
        via.point = null;
        clearTimeout(this._suggestTimers["via" + index]);
        if (!text || text.trim().length < 3) {
            via.suggestions = [];
            return;
        }
        this._suggestTimers["via" + index] = setTimeout(async () => {
            const res = await this.orm.call("att.vietmap.api", "search_address_ui", [text]);
            via.suggestions = (res || []).slice(0, 6);
        }, 400);
    }

    async selectViaSuggestion(index, sug) {
        const via = this.state.search.viaPoints[index];
        const detail = await this.orm.call("att.vietmap.api", "get_place_detail_ui", [sug.ref_id]);
        via.point = {
            name: this.suggestionLabel(sug),
            lat: (detail && detail.lat) || 0,
            lng: (detail && detail.lng) || 0,
        };
        via.text = via.point.name;
        via.suggestions = [];
    }

    // Toạ độ combine (1 chuỗi "lat,lng" mỗi điểm) → suy tên hiển thị qua
    // reverse_geocode_ui. Lỗi/không parse được thì fallback tên = chính
    // chuỗi toạ độ, không chặn việc tìm đường.
    async _resolveCoordsPoint(which) {
        const s = this.state.search;
        const raw = which === "origin" ? s.originCoords : s.destCoords;
        const parts = (raw || "").split(",").map((p) => parseFloat(p.trim()));
        if (parts.length !== 2 || parts.some((n) => Number.isNaN(n))) {
            return null;
        }
        const [lat, lng] = parts;
        let name = `${lat}, ${lng}`;
        try {
            const res = await this.orm.call("att.vietmap.api", "reverse_geocode_ui", [lat, lng]);
            if (res && !res.error && res.name) {
                name = res.name;
            }
        } catch {
            // giữ fallback tên = chuỗi toạ độ thô
        }
        return { name, lat, lng };
    }

    async _resolveCoordsPoints() {
        const s = this.state.search;
        const [origin, dest] = await Promise.all([
            this._resolveCoordsPoint("origin"), this._resolveCoordsPoint("dest"),
        ]);
        if (origin) {
            s.origin = origin;
        }
        if (dest) {
            s.dest = dest;
        }
        await Promise.all(s.viaPoints.map(async (via) => {
            const parts = (via.coords || "").split(",").map((p) => parseFloat(p.trim()));
            if (parts.length !== 2 || parts.some((n) => Number.isNaN(n))) {
                return;
            }
            const [lat, lng] = parts;
            let name = `${lat}, ${lng}`;
            try {
                const res = await this.orm.call("att.vietmap.api", "reverse_geocode_ui", [lat, lng]);
                if (res && !res.error && res.name) {
                    name = res.name;
                }
            } catch {
                // giữ fallback tên = chuỗi toạ độ thô
            }
            via.point = { name, lat, lng };
        }));
    }

    // Gõ địa chỉ → autocomplete VietMap, debounce 400ms để không bắn API
    // theo từng phím. which = 'origin' | 'dest'.
    onAddressInput(which, ev) {
        const text = ev.target.value;
        const s = this.state.search;
        if (which === "origin") {
            s.originText = text;
            s.origin = null;
        } else {
            s.destText = text;
            s.dest = null;
        }
        clearTimeout(this._suggestTimers[which]);
        if (!text || text.trim().length < 3) {
            s[which === "origin" ? "originSuggestions" : "destSuggestions"] = [];
            return;
        }
        this._suggestTimers[which] = setTimeout(async () => {
            const res = await this.orm.call("att.vietmap.api", "search_address_ui", [text]);
            s[which === "origin" ? "originSuggestions" : "destSuggestions"] =
                (res || []).slice(0, 6);
        }, 400);
    }

    suggestionLabel(sug) {
        return sug.display || sug.name || sug.address || "";
    }

    async selectSuggestion(which, sug) {
        const s = this.state.search;
        const detail = await this.orm.call(
            "att.vietmap.api", "get_place_detail_ui", [sug.ref_id]);
        const point = {
            name: this.suggestionLabel(sug),
            lat: (detail && detail.lat) || 0,
            lng: (detail && detail.lng) || 0,
        };
        if (which === "origin") {
            s.origin = point;
            s.originText = point.name;
            s.originSuggestions = [];
        } else {
            s.dest = point;
            s.destText = point.name;
            s.destSuggestions = [];
        }
    }

    async findRoute() {
        const s = this.state.search;
        if (s.inputMode === "coords") {
            await this._resolveCoordsPoints();
        }
        if (!s.origin || !s.dest) {
            s.error = "Chọn điểm đi và điểm đến từ danh sách gợi ý trước.";
            return;
        }
        s.error = "";
        s.searching = true;
        s.result = null;
        try {
            const capacity = s.vehicleClass === "truck" && parseInt(s.capacityKg, 10) > 0
                ? parseInt(s.capacityKg, 10) : null;
            // Ghép ngày + giờ (24h, tự nhập, không qua widget trình duyệt)
            // -> ISO-8601 UTC ("Z") đúng format VietMap yêu cầu — Date tự
            // quy đổi múi giờ theo trình duyệt, không cần tự trừ/cộng tay.
            const departureDt = (s.departureDate && s.departureTimeStr)
                ? new Date(`${s.departureDate}T${s.departureTimeStr}:00`) : null;
            const departureTimeUtc = (departureDt && !Number.isNaN(departureDt.getTime()))
                ? departureDt.toISOString() : null;
            const viaPointsPayload = s.viaPoints
                .filter((via) => via.point)
                .map((via) => [via.point.lat, via.point.lng]);
            const res = await this.orm.call("att.vietmap.api", "get_route_info_ui", [
                s.origin.lat, s.origin.lng, s.dest.lat, s.dest.lng,
                s.vehicleClass, capacity, departureTimeUtc, viaPointsPayload,
            ]);
            if (res && res.error) {
                s.error = res.error;
            } else {
                s.result = res;
                s.section = "directions";
                this._drawSearchRoute(res.geometry || [], res.congestion || []);
            }
        } finally {
            s.searching = false;
        }
    }

    // Vẽ tuyến vừa tìm lên bản đồ, TÔ MÀU THEO MỨC TẮC NGHẼN: mỗi segment
    // congestion (first/last = chỉ số vào mảng geometry) thành 1 LineString
    // riêng mang màu mức tắc của nó. Không có dữ liệu tắc → 1 line xanh
    // dương như cũ. Zoom vừa khung tuyến sau khi vẽ.
    _drawSearchRoute(geometry, congestion) {
        const map = this.mapInstance;
        if (!map || !geometry.length) {
            return;
        }
        const coords = geometry.map((c) => [c[1], c[0]]); // [lat,lng] → [lng,lat]
        let features;
        if (congestion.length) {
            features = congestion.map((seg) => ({
                type: "Feature",
                properties: {
                    color: (CONGESTION_LEVELS[seg.level] || CONGESTION_LEVELS.unknown).color,
                },
                geometry: {
                    type: "LineString",
                    coordinates: coords.slice(seg.first, seg.last + 2),
                },
            })).filter((f) => f.geometry.coordinates.length >= 2);
        } else {
            features = [{
                type: "Feature",
                properties: { color: "#1a56c4" },
                geometry: { type: "LineString", coordinates: coords },
            }];
        }
        const data = { type: "FeatureCollection", features };
        if (map.getSource("att_search_route")) {
            map.getSource("att_search_route").setData(data);
        } else {
            map.addSource("att_search_route", { type: "geojson", data });
            map.addLayer({
                id: "att_search_route_line",
                type: "line",
                source: "att_search_route",
                layout: { "line-join": "round", "line-cap": "round" },
                paint: {
                    "line-color": ["get", "color"],
                    "line-width": 5,
                    "line-opacity": 0.9,
                },
            });
        }
        let [minLng, minLat, maxLng, maxLat] = [coords[0][0], coords[0][1], coords[0][0], coords[0][1]];
        for (const [lng, lat] of coords) {
            minLng = Math.min(minLng, lng); maxLng = Math.max(maxLng, lng);
            minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
        }
        map.fitBounds([[minLng, minLat], [maxLng, maxLat]], { padding: 70 });
    }

    // Dòng tóm tắt cho tab "Tắc nghẽn" — mỗi segment kèm nhãn/màu/km.
    get congestionRows() {
        const segs = (this.state.search.result && this.state.search.result.congestion) || [];
        return segs.map((seg) => {
            const lv = CONGESTION_LEVELS[seg.level] || CONGESTION_LEVELS.unknown;
            return {
                label: lv.label, color: lv.color, distance_km: seg.distance_km,
                streetName: seg.street_name || "",
            };
        });
    }

    // Marker của tuyến đang tìm: điểm đi (xanh lá), điểm đến (đỏ), các
    // trạm BOT trên đúng tuyến này (tím) — không vẽ gì khác ngoài tuyến
    // đang xem, khác dashboard điều vận (không có layer mật độ/xe/BOT lịch sử).
    get searchMarkers() {
        const s = this.state.search;
        const markers = [];
        if (s.origin && s.origin.lat) {
            markers.push({ lat: s.origin.lat, lng: s.origin.lng, color: "#2e7d32",
                           popupHtml: `<b>Điểm đi</b><br/>${s.origin.name}` });
        }
        if (s.dest && s.dest.lat) {
            markers.push({ lat: s.dest.lat, lng: s.dest.lng, color: "#c62828",
                           popupHtml: `<b>Điểm đến</b><br/>${s.dest.name}` });
        }
        s.viaPoints.forEach((via, idx) => {
            if (via.point && via.point.lat) {
                markers.push({
                    lat: via.point.lat, lng: via.point.lng, color: "#f9a825",
                    popupHtml: `<b>Điểm dừng ${idx + 1}</b><br/>${via.point.name}`,
                });
            }
        });
        for (const t of (s.result && s.result.tolls) || []) {
            if (t.lat && t.lng && (t.price || 0) > 0) {
                markers.push({
                    lat: t.lat, lng: t.lng, icon: "toll", color: "#6a3fb5",
                    popupHtml: `<b>${t.name || "Trạm thu phí"}</b>` +
                        (t.price ? `<br/>Phí: ${t.price.toLocaleString("vi-VN")} đ` : ""),
                });
            }
        }
        return markers;
    }

    get mapMarkers() {
        return this.searchMarkers;
    }

    // kind = 'sale' (báo giá bán) | 'purchase' (RFQ thuê NCC chạy tuyến).
    async createQuotationFromSearch(kind) {
        const s = this.state.search;
        if (!s.origin || !s.dest) {
            return;
        }
        const [model, method] = kind === "purchase"
            ? ["purchase.order", "action_new_rfq_for_route"]
            : ["sale.order", "action_new_quotation_for_route"];
        const action = await this.orm.call(model, method, [{
            origin_name: s.origin.name, origin_lat: s.origin.lat, origin_lng: s.origin.lng,
            destination_name: s.dest.name, destination_lat: s.dest.lat, destination_lng: s.dest.lng,
        }]);
        this.action.doAction(action);
    }

    onMapReady(map) {
        this.mapInstance = map;
        // Tuyến đã tìm trước khi rời màn (khôi phục từ cache) — vẽ lại khi
        // bản đồ mới sẵn sàng, user không phải bấm Tìm lại sau khi back từ SO/PO.
        const restored = this.state.search.result;
        if (restored && (restored.geometry || []).length) {
            this._drawSearchRoute(restored.geometry, restored.congestion || []);
        }
    }
}

registry.category("actions").add("att_vietmap_connector.route_finder", RouteFinderDashboard);
