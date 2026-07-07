/** @odoo-module **/

/*
    Patch Thread model của Odoo Discuss.

    Mục tiêu:
    - Nếu channel_type = zalo thì coi như chat channel.
    - Không cho user leave channel Zalo linh tinh.
    - Avatar ưu tiên lấy từ correspondent giống chat cá nhân.
*/

import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    get avatarUrl() {
        if (this.channel_type === "zalo" && this.correspondent) {
            return this.correspondent.persona.avatarUrl;
        }
        return super.avatarUrl;
    },

    get isChatChannel() {
        return this.channel_type === "zalo" || super.isChatChannel;
    },

    get canLeave() {
        return this.channel_type !== "zalo" && super.canLeave;
    },

    get canUnpin() {
        if (this.channel_type === "zalo") {
            return this.importantCounter === 0;
        }
        return super.canUnpin;
    },
});