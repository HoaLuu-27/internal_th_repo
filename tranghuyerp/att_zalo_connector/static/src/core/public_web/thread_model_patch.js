/** @odoo-module **/

/*
    Gán Zalo channel vào category Zalo trong Discuss.

    Điều kiện:
    - Backend cần tạo discuss.channel với channel_type = "zalo".
*/

import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    _computeDiscussAppCategory() {
        if (this.channel_type === "zalo") {
            return this.store.discuss.zalo;
        }
        return super._computeDiscussAppCategory();
    },
});