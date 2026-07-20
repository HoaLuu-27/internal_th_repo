/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

const STATE_LABELS = {
    draft: "Nháp",
    confirmed: "Đã xác nhận",
    in_transit: "Đang vận chuyển",
    done: "Hoàn thành",
    cancelled: "Đã huỷ",
};
const STATE_COLORS = {
    draft: "#9e9e9e",
    confirmed: "#2d6cdf",
    in_transit: "#1fa189",
    done: "#3c8a3c",
    cancelled: "#c0392b",
};
// Màu/nhãn trạng thái xe — dùng cho tab danh sách "Xe" (đủ 4 trạng thái).
const VEHICLE_STATE_COLORS = {
    available: "#1fa189",
    in_transit: "#e08e2b",
    maintenance: "#d4b106",
    broken: "#c0392b",
};
const VEHICLE_STATE_LABELS = {
    available: "Sẵn sàng",
    in_transit: "Đang chạy",
    maintenance: "Bảo dưỡng",
    broken: "Hỏng",
};
// Dashboard "Điều vận" — thuần danh sách/thống kê: 4 tab (Lệnh vận chuyển/
// Lộ trình/Xe/Chi phí cần duyệt) + biểu đồ phân bố trạng thái. Bản đồ +
// panel Tìm đường + tạo báo giá đã tách sang att_vietmap_connector
// (route_finder.js) để Sales/Purchase dùng được không cần cài module này.
// Bản đồ nhiệt Realtime (trạng thái TO+xe kết hợp) nằm ở màn riêng
// realtime_heatmap.js.
export class DispatchDashboard extends Component {
    static template = "att_transport_orders.DispatchDashboard";
    // KHÔNG khai static props — đây là client action, framework tự truyền
    // thêm action/actionId/updateActionState/className... khai props ở
    // đây (kể cả rỗng) sẽ làm Owl validate và từ chối các prop đó.
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            routes: [],
            orders: [],
            vehicles: [],
            costLines: [],
            loading: true,
            activeTab: "orders",
        });

        onWillStart(async () => {
            await Promise.all([
                this._loadRoutes(), this._loadOrders(), this._loadVehicles(),
                this._loadCostLines(),
            ]);
            this.state.loading = false;
        });
    }

    // Dòng chi phí cần xử lý NGAY — needs_approval=True (đã tính theo
    // ngưỡng của loại chi phí) và state vẫn đang 'pending', để KD/quản lý
    // vào duyệt nhanh mà không phải mở từng Lệnh vận chuyển tìm.
    async _loadCostLines() {
        const lines = await this.orm.searchRead(
            "att.transport.cost.line",
            [["needs_approval", "=", true], ["state", "=", "pending"]],
            ["date", "description", "cost_type_id", "amount", "transport_order_id"],
            { limit: 100, order: "date desc" }
        );
        this.state.costLines = lines;
    }

    onCostLineClick(line) {
        if (!line.transport_order_id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "att.transport.order",
            res_id: line.transport_order_id[0],
            views: [[false, "form"]],
            target: "current",
        });
    }

    // Tải TẤT CẢ xe (kể cả chưa có toạ độ / đang bảo dưỡng) — tab "Xe" cần
    // đủ danh sách kèm trạng thái. Xem vị trí/trạng thái realtime chi tiết
    // hơn (kèm bản đồ) thì dùng màn "Bản đồ nhiệt (Realtime)" riêng.
    async _loadVehicles() {
        const vehicles = await this.orm.searchRead(
            "fleet.vehicle",
            [],
            ["name", "license_plate", "th_state", "default_driver_employee_id"],
            { limit: 200, order: "license_plate" }
        );
        this.state.vehicles = vehicles;
    }

    // Bấm 1 xe trong tab danh sách: mở thẳng bản ghi xe — dashboard này
    // không còn bản đồ để bay-tới nữa (đã tách sang màn Bản đồ nhiệt).
    locateVehicle(v) {
        this.openVehicleForm(v);
    }

    openVehicleForm(v) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "fleet.vehicle",
            res_id: v.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    get vehicleStateLabel() {
        return VEHICLE_STATE_LABELS;
    }

    get vehicleStateColor() {
        return VEHICLE_STATE_COLORS;
    }

    async _loadRoutes() {
        const routes = await this.orm.searchRead(
            "att.transport.route",
            [],
            ["name", "origin_name", "destination_name", "distance_km", "eta_minutes", "cost_total"],
            { limit: 200 }
        );
        this.state.routes = routes;
    }

    // Tên tuyến rút gọn cho tab "Lộ trình" — cùng cách rút gọn với
    // shortRouteName(order) nhưng route ở đây là record thật (origin_name/
    // destination_name), không phải tuple [id, display_name] của route_id.
    shortRouteLabel(route) {
        return `${this._shortAddress(route.origin_name)} – ${this._shortAddress(route.destination_name)}`;
    }

    onRouteClick(route) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "att.transport.route",
            res_id: route.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    async _loadOrders() {
        const orders = await this.orm.searchRead(
            "att.transport.order",
            [["state", "!=", "cancelled"]],
            ["name", "partner_id", "route_id", "state", "scheduled_date"],
            { limit: 50, order: "scheduled_date desc" }
        );
        this.state.orders = orders;
    }

    get stateLabel() {
        return STATE_LABELS;
    }

    // Rút gọn 1 vế địa chỉ về đúng đoạn cuối cùng (thường là Tỉnh/Thành phố),
    // bỏ luôn tiền tố hành chính — "129 Đường Nguyễn Trãi, Phường Khương
    // Đình, Thành phố Hà Nội" -> "Hà Nội" (không phải "Thành phố Hà Nội").
    _shortAddress(text) {
        if (!text) {
            return "";
        }
        const parts = text.split(",").map((p) => p.trim()).filter(Boolean);
        const last = parts.length ? parts[parts.length - 1] : text;
        return last.replace(/^(Thành phố|Tỉnh)\s+/i, "");
    }

    // route_id trả [id, display_name] — display_name = route.name, đã có
    // dạng "Điểm đi đầy đủ – Điểm đến đầy đủ" (tạo ở _find_or_create) —
    // tách theo dấu "–" rồi rút gọn từng vế.
    shortRouteName(order) {
        if (!order.route_id) {
            return "";
        }
        const fullName = order.route_id[1] || "";
        const parts = fullName.split(" – ");
        if (parts.length !== 2) {
            return fullName;
        }
        return `${this._shortAddress(parts[0])} – ${this._shortAddress(parts[1])}`;
    }

    onOrderClick(order) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "att.transport.order",
            res_id: order.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    get chartBars() {
        const counts = {};
        for (const o of this.state.orders) {
            counts[o.state] = (counts[o.state] || 0) + 1;
        }
        const max = Math.max(1, ...Object.values(counts));
        return Object.keys(STATE_LABELS).map((key) => ({
            key,
            label: STATE_LABELS[key],
            color: STATE_COLORS[key],
            count: counts[key] || 0,
            pct: Math.round(((counts[key] || 0) / max) * 100),
        }));
    }
}

registry.category("actions").add("att_transport_orders.dispatch_dashboard", DispatchDashboard);
