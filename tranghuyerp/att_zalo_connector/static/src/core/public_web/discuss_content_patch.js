/** @odoo-module **/

/*
    Cho phép hiển thị avatar ở thread Zalo.

    Một số thread kiểu channel mặc định không show avatar giống chat.
    Với Zalo, ta muốn nhìn giống cuộc trò chuyện khách hàng.
*/

import { DiscussContent } from "@mail/core/public_web/discuss_content";
import { patch } from "@web/core/utils/patch";

patch(DiscussContent.prototype, {
    get showThreadAvatar() {
        return super.showThreadAvatar || this.thread?.channel_type === "zalo";
    },
});