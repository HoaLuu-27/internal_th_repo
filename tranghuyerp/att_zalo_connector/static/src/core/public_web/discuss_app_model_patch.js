/** @odoo-module **/

/*
    Thêm category "Zalo" vào sidebar Discuss.

    Sau này tất cả discuss.channel có channel_type = zalo
    sẽ được gom về category này.
*/

import { DiscussApp } from "@mail/core/public_web/discuss_app_model";
import { fields } from "@mail/core/common/record";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(DiscussApp.prototype, {
    setup() {
        super.setup(...arguments);

        this.zalo = fields.One("DiscussAppCategory", {
            compute() {
                return {
                    addTitle: _t("Search Zalo Conversation"),
                    extraClass: "o-zalo-DiscussSidebarCategory",
                    hideWhenEmpty: false,
                    icon: "fa fa-comments",
                    id: "zalo",
                    name: _t("Zalo"),
                    sequence: 20,
                    serverStateKey: "is_discuss_sidebar_category_zalo_open",
                };
            },
            eager: true,
        });
    },
});