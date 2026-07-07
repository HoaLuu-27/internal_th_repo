/** @odoo-module **/

/*
    Khi click avatar member trong Zalo channel:
    - Nếu là khách Zalo thì mở chat/partner tương ứng.
    - Tránh lỗi userId invalid giống module cũ.
*/

import { ChannelMemberList } from "@mail/discuss/core/common/channel_member_list";
import { patch } from "@web/core/utils/patch";

patch(ChannelMemberList.prototype, {
    onClickAvatar(ev, member) {
        if (this.props.thread.channel_type === "zalo") {
            if (member.persona?.id) {
                this.store.openChat({ partnerId: member.persona.id });
            }
            return;
        }

        return super.onClickAvatar(...arguments);
    },
});