/** @odoo-module **/

console.log("OPEN LEAD POPUP JS LOADED");   // CONFIRM FILE LOADED

import { ListController } from "@web/views/list/list_controller";
import { patch } from "@web/core/utils/patch";

patch(ListController.prototype, {

    onRowClicked(ev) {

        console.log("ROW CLICKED TEST");   // Debug 1

        // Only activate for this tree: <tree js_class="open_lead_popup">
        if (this.props.archInfo.jsClass !== "open_lead_popup") {
            return super.onRowClicked(ev);
        }

        console.log("PATCH ACTIVATED");   // Debug 2

        ev.preventDefault();
        ev.stopPropagation();

        const record = ev.detail?.record;
        if (!record) {
            return super.onRowClicked(ev);
        }

        console.log("RECORD:", record.resId);  // Debug 3

        // Open popup wizard
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Lead Popup",
            res_model: "lead.open.wizard",
            view_mode: "form",
            target: "new",
            context: {
                default_lead_id: record.resId,
            },
        });
    },
});
