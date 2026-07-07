/** @odoo-module **/

/*
    Patch riêng cho Discuss thread.

    Mục tiêu:
    - Zalo channel có member list.
    - Ẩn bớt member đại diện kỹ thuật nếu cần.
*/

import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    _computeOfflineMembers() {
        const res = super._computeOfflineMembers();

        if (this.channel_type === "zalo" && this.zalo_partner_id) {
            return res.filter((member) => member.persona?.id !== this.zalo_partner_id);
        }

        return res;
    },

    get hasMemberList() {
        return this.channel_type === "zalo" || super.hasMemberList;
    },
});