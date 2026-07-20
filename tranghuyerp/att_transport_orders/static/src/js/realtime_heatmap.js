/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";

// Cứ 25s poll lại 1 lần — đủ "liên tục" để cảm nhận realtime nhưng không
// dội API quá dày. Field th_display_state (fleet_vehicle.py) KHÔNG store
// nên mỗi lần searchRead sẽ tính lại đúng thời điểm hiện tại.
const POLL_INTERVAL_MS = 25000;

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
// Bảng màu tô cho th_display_state (trạng thái xe kết hợp TO — tính ở
// att_transport_orders/models/fleet_vehicle.py) — đủ 9 giá trị phân biệt
// rõ để user nhận ra ngay tình trạng xe qua chấm màu + chữ, KHÔNG icon.
const VEHICLE_STATE_LABELS = {
    available: "Sẵn sàng",
    maintenance: "Bảo dưỡng",
    broken: "Hỏng",
    waiting_departure: "Chờ xuất phát",
    to_pickup_moving: "Đến điểm bốc hàng",
    to_pickup_stopped: "Dừng (đến điểm bốc hàng)",
    to_delivery_moving: "Đến điểm giao hàng",
    to_delivery_stopped: "Dừng (đến điểm giao hàng)",
    delivered_pending: "Đã giao - chờ hoàn tất",
};
const VEHICLE_STATE_COLORS = {
    available: "#1fa189",
    maintenance: "#d4b106",
    broken: "#c0392b",
    waiting_departure: "#4a7fd1",
    to_pickup_moving: "#2fa14f",
    to_pickup_stopped: "#f2c744",
    to_delivery_moving: "#1a56c4",
    to_delivery_stopped: "#f0812e",
    delivered_pending: "#6a3fb5",
};

// Bản đồ nhiệt Realtime — KHÔNG phải bản đồ địa lý, mà là 1 BẢNG danh sách
// Lệnh vận chuyển đang sống (chưa huỷ), mỗi dòng kèm: trạng thái lệnh (màu),
// xe tương ứng, trạng thái xe (màu, đã kết hợp TO+GPS ở th_display_state),
// điểm bốc hàng, điểm giao hàng — poll định kỳ để tự cập nhật liên tục.
export class RealtimeHeatmap extends Component {
    static template = "att_transport_orders.RealtimeHeatmap";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            rows: [],
            loading: true,
        });

        onWillStart(async () => {
            await this._load();
            this.state.loading = false;
        });
        this._pollTimer = setInterval(() => this._load(), POLL_INTERVAL_MS);
        onWillUnmount(() => clearInterval(this._pollTimer));
    }

    async _load() {
        const orders = await this.orm.searchRead(
            "att.transport.order",
            [["state", "!=", "cancelled"]],
            ["name", "state", "vehicle_id", "route_id"],
            { limit: 100, order: "scheduled_date desc" }
        );
        const vehicleIds = [...new Set(
            orders.filter((o) => o.vehicle_id).map((o) => o.vehicle_id[0])
        )];
        const vehicles = vehicleIds.length ? await this.orm.searchRead(
            "fleet.vehicle",
            [["id", "in", vehicleIds]],
            ["license_plate", "name", "th_display_state", "current_position_updated"],
        ) : [];
        const vehicleById = Object.fromEntries(vehicles.map((v) => [v.id, v]));
        this.state.rows = orders.map((o) => {
            const [pickup, delivery] = this._splitRoute(o.route_id);
            return {
                id: o.id,
                name: o.name,
                state: o.state,
                vehicle: o.vehicle_id ? vehicleById[o.vehicle_id[0]] : null,
                pickup,
                delivery,
            };
        });
    }

    // route_id trả [id, display_name] — display_name có dạng "Điểm bốc đầy
    // đủ – Điểm giao đầy đủ" (tạo ở att.transport.route._find_or_create) —
    // tách theo dấu "–", GIỮ NGUYÊN địa chỉ đầy đủ (không rút gọn) để ghi
    // rõ ràng trên bảng.
    _splitRoute(routeTuple) {
        if (!routeTuple) {
            return ["", ""];
        }
        const parts = (routeTuple[1] || "").split(" – ");
        if (parts.length !== 2) {
            return [routeTuple[1] || "", ""];
        }
        return parts;
    }

    get stateLabel() {
        return STATE_LABELS;
    }

    get stateColor() {
        return STATE_COLORS;
    }

    get vehicleStateLabel() {
        return VEHICLE_STATE_LABELS;
    }

    get vehicleStateColor() {
        return VEHICLE_STATE_COLORS;
    }

    onOrderClick(row) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "att.transport.order",
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    onVehicleClick(vehicle) {
        if (!vehicle) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "fleet.vehicle",
            res_id: vehicle.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("att_transport_orders.realtime_heatmap", RealtimeHeatmap);
