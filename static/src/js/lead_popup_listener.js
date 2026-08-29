/** @odoo-module **/

import { registry } from "@web/core/registry";

function registerLeadPopupListener(env) {
    env.bus.on("LEAD_POPUP_DONE", null, (resId) => {
        env.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: "leads.logic",
            res_id: resId,
            view_mode: "form",
        });
    });
}

registry.category("services").add("leadPopupListener", registerLeadPopupListener);
