/** @odoo-module **/
import { useService } from "@web/core/utils/hooks";
import { Component, useRef, onMounted, onWillUnmount, onWillStart, onWillUpdateProps } from "@odoo/owl";

// SVG trắng 17px cho từng loại icon marker — key chính là giá trị
// item.icon nơi gọi truyền vào (không có trong map này thì rơi về marker
// giọt nước mặc định của vietmapgl).
const ICON_SVGS = {
    vehicle: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="#fff">
        <path d="M3 6a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h1a2.5 2.5 0 0 0 5 0h6a2.5 2.5 0 0 0 5 0h1a1 1 0 0 0 1-1v-4l-3-4h-3V6a1 1 0 0 0-1-1H3zm12 3h2.5l1.8 2.4H15V9zM6.5 17a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm11 0a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/>
    </svg>`,
    // Trạm thu phí: barie chắn ngang + trụ — nhìn ra ngay "trạm BOT".
    toll: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="22" height="22" fill="#fff">
        <path d="M4 4h2v16H4zM7 6l13-3 .5 2L7.6 8zM10 7.3l2-.5v3l-2 .5zM15 6.1l2-.5v3l-2 .5zM8 12h8a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1h-3v4h-2v-4H8a1 1 0 0 1-1-1v-2a1 1 0 0 1 1-1z"/>
    </svg>`,
};

// Component OWL thuần tái sử dụng được — CHỈ lo hiển thị bản đồ VietMap GL
// + marker cơ bản. Không biết gì về TO/Route/nghiệp vụ — nơi khác (dashboard
// điều vận) tự lấy dữ liệu rồi truyền props/gọi getMap() để vẽ thêm.
export class VietmapMap extends Component {
    static template = "att_vietmap_connector.VietmapMap";
    static props = {
        markers: { type: Array, optional: true },
        center: { type: Array, optional: true },
        zoom: { type: Number, optional: true },
        onMapReady: { type: Function, optional: true },
    };
    static defaultProps = {
        markers: [],
        center: [106, 16],
        zoom: 5,
    };

    setup() {
        this.orm = useService("orm");
        this.mapRef = useRef("mapContainer");
        this.map = null;
        this.markerInstances = [];

        onWillStart(async () => {
            this.styleUrl = await this.orm.call("att.vietmap.config", "get_style_url_ui", []);
        });

        onMounted(() => this._mountMap());
        onWillUnmount(() => {
            if (this.map) {
                this.map.remove();
                this.map = null;
            }
        });
        // markers là prop — cha đổi markers (VD bật/tắt chế độ bản đồ
        // nhiệt) phải vẽ lại ngay, không đợi mount lại cả bản đồ.
        onWillUpdateProps((nextProps) => {
            if (this.map && this.map.loaded()) {
                this._drawMarkers(nextProps.markers);
            }
        });
    }

    _mountMap() {
        if (!this.styleUrl) {
            return;
        }
        if (typeof vietmapgl === "undefined") {
            console.error("[VIETMAP] Thư viện vietmapgl chưa nạp được — kiểm tra assets.");
            return;
        }
        this.map = new vietmapgl.Map({
            container: this.mapRef.el,
            style: this.styleUrl,
            center: this.props.center,
            zoom: this.props.zoom,
        });
        this.map.addControl(new vietmapgl.NavigationControl(), "top-right");
        this.map.on("load", () => {
            this._drawMarkers(this.props.markers);
            if (this.props.onMapReady) {
                this.props.onMapReady(this.map);
            }
        });
    }

    _drawMarkers(markers) {
        for (const m of this.markerInstances) {
            m.remove();
        }
        this.markerInstances = [];
        for (const item of markers || []) {
            const options = ICON_SVGS[item.icon]
                ? { element: this._buildIconEl(item) }
                : { color: item.color || "#1f3a5f" };
            const marker = new vietmapgl.Marker(options)
                .setLngLat([item.lng, item.lat])
                .addTo(this.map);
            if (item.popupHtml) {
                const popup = new vietmapgl.Popup({ offset: 24, maxWidth: "320px" })
                    .setHTML(item.popupHtml);
                // Nút "Xem chi tiết" trong popup: popup HTML là chuỗi tĩnh
                // không gắn được handler OWL — gắn tay khi popup mở, tìm
                // theo class .att_popup_detail_btn.
                if (item.onDetailClick) {
                    popup.on("open", () => {
                        const btn = popup.getElement().querySelector(".att_popup_detail_btn");
                        if (btn) {
                            btn.onclick = item.onDetailClick;
                        }
                    });
                }
                marker.setPopup(popup);
            }
            this.markerInstances.push(marker);
        }
    }

    // Icon riêng theo loại đối tượng (khác hẳn marker giọt nước điểm
    // đi/đến) — hình SVG trắng trong khung tròn màu + nhãn (biển số...)
    // nền màu ngay dưới icon, kiểu VietMap Live Maps.
    _buildIconEl(item) {
        const el = document.createElement("div");
        el.className = "att_map_icon_marker";
        el.style.display = "flex";
        el.style.flexDirection = "column";
        el.style.alignItems = "center";
        el.style.cursor = "pointer";
        const circle = document.createElement("div");
        circle.style.width = "38px";
        circle.style.height = "38px";
        circle.style.borderRadius = "50%";
        circle.style.display = "flex";
        circle.style.alignItems = "center";
        circle.style.justifyContent = "center";
        circle.style.backgroundColor = item.color || "#2d6cdf";
        circle.style.border = "2px solid #fff";
        circle.style.boxShadow = "0 1px 4px rgba(0,0,0,0.4)";
        circle.innerHTML = ICON_SVGS[item.icon];
        el.appendChild(circle);
        if (item.label) {
            const label = document.createElement("div");
            label.textContent = item.label;
            label.style.marginTop = "2px";
            label.style.padding = "1px 6px";
            label.style.borderRadius = "3px";
            label.style.backgroundColor = item.color || "#2d6cdf";
            label.style.color = "#fff";
            label.style.fontSize = "11px";
            label.style.fontWeight = "700";
            label.style.whiteSpace = "nowrap";
            label.style.boxShadow = "0 1px 3px rgba(0,0,0,0.35)";
            el.appendChild(label);
        }
        return el;
    }

    // Cho component cha lấy trực tiếp instance map (vẽ heat layer, route
    // line...) sau khi đã sẵn sàng — dùng khi không truyền onMapReady.
    getMap() {
        return this.map;
    }
}
