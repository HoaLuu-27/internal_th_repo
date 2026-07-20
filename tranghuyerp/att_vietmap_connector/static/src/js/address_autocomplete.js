/** @odoo-module **/
import { registry } from "@web/core/registry";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

export class AttAddressAutocomplete extends Component {
    static template = "att_vietmap_connector.AddressAutocomplete";
    static components = { AutoComplete };
    static props = {
        ...standardFieldProps,
        latField: { type: String, optional: true },
        lngField: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.searchRequestId = 0;
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get sources() {
        return [{ options: (request) => this.loadOptionsSource(request) }];
    }

    async loadOptionsSource(query) {
        if (!query || query.length < 3) return [];
        // Gõ nhanh -> nhiều request bắn chồng chéo, phản hồi có thể về không
        // đúng thứ tự. Đánh số mỗi lần gọi, chỉ áp dụng kết quả của lần gọi
        // MỚI NHẤT — kết quả trễ của các lần gọi cũ hơn bị bỏ qua.
        const requestId = ++this.searchRequestId;
        const results = await this.orm.call("att.vietmap.api", "search_address_ui", [query]);
        if (requestId !== this.searchRequestId) {
            return [];
        }
        // onSelect gắn vào TỪNG option — AutoComplete gốc không nhận onSelect
        // ở cấp component, mà gọi option.onSelect() khi user chọn.
        return results.map((r) => ({
            label: r.display,
            onSelect: () => this.selectAddress(r.ref_id),
        }));
    }

    async selectAddress(refId) {
        const detail = await this.orm.call("att.vietmap.api", "get_place_detail_ui", [refId]);
        this.props.record.update({
            [this.props.name]: detail.display || detail.address,
            [this.props.latField]: detail.lat,
            [this.props.lngField]: detail.lng,
        });
    }

    // KHÔNG ghi record lúc đang gõ (onInput) — ghi vào field thật mỗi ký tự sẽ
    // kích hoạt onchange của dòng SOL/POL, làm Odoo re-render huỷ luôn component
    // này giữa chừng lúc đang chờ VietMap trả kết quả (mất kết quả dù API đã trả đúng).
    // Chỉ ghi khi: (1) user chọn 1 gợi ý — selectAddress, hoặc (2) rời khỏi ô mà gõ
    // tay không chọn gì — onBlur.
    onBlur({ inputValue }) {
        if (inputValue && inputValue !== this.value) {
            this.props.record.update({ [this.props.name]: inputValue });
        }
    }
}

registry.category("fields").add("att_address_autocomplete", {
    component: AttAddressAutocomplete,
    extractProps: ({ options }) => ({
        latField: options.lat_field,
        lngField: options.lng_field,
    }),
});