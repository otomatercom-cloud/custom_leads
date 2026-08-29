/** @odoo-module **/
console.log("FINAL PATCH LOADED");

import { patch } from "@web/core/utils/patch";
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";


// ------------------------------
// PATCH 1: LIST CONTROLLER
// ------------------------------
patch(ListController.prototype, {
    async onRowClicked(record, ev) {
        console.log("ROW CLICK INTERCEPTED (Controller)");

        ev.preventDefault();
        ev.stopPropagation();

        const actionService = this.env.services.action;

        const popup_action = await this.orm.call(
            "leads.logic",
            "open_lead_popup",
            [[record.resId]],
            { context: this.context }
        );

        console.log("POPUP ACTION:", popup_action);

        await actionService.doAction(popup_action);
        return;
    },
});


// ------------------------------
// PATCH 2: LIST RENDERER (Backup patch)
// ------------------------------
patch(ListRenderer.prototype, {
    onRowClicked(record, ev) {
        console.log("ROW CLICK INTERCEPTED (Renderer)");

        ev.preventDefault();
        ev.stopPropagation();

        const controller = this.props.list.controller;

        controller.onRowClicked(record, ev);
    },
});
