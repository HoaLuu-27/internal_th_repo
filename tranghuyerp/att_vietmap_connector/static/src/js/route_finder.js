/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { Component, useState, onWillStart } from "@odoo/owl";
import { VietmapMap } from "@att_vietmap_connector/js/vietmap_widget";

// 4 nhóm xe VietMap Route v4 chấp nhận — nút chọn trên panel Tìm đường.
const VIETMAP_VEHICLE_CLASSES = [
    { key: "car", label: "Ô tô" },
    { key: "motorcycle", label: "Xe máy" },
    { key: "truck", label: "Xe tải" },
    { key: "container", label: "Container" },
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
            search: {
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
    }

    get vehicleClasses() {
        return VIETMAP_VEHICLE_CLASSES;
    }

    pickVehicleClass(key) {
        this.state.search.vehicleClass = key;
    }

    setInputMode(mode) {
        this.state.search.inputMode = mode;
        this.state.search.error = "";
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
            const res = await this.orm.call("att.vietmap.api", "get_route_info_ui", [
                s.origin.lat, s.origin.lng, s.dest.lat, s.dest.lng,
                s.vehicleClass, capacity,
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
            return { label: lv.label, color: lv.color, distance_km: seg.distance_km };
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
    }
}

registry.category("actions").add("att_vietmap_connector.route_finder", RouteFinderDashboard);
