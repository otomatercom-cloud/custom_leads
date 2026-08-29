/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

class CallCampaignDashboard extends Component {
    static template = "custom_leads.CallCampaignDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            campaigns: [],
            stats: { total: 0, running: 0, draft: 0, done: 0, total_leads: 0, total_called: 0 },
            filter: "all",   // all | running | draft | done | mine
            search: "",
            role: "officer",
        });

        onWillStart(async () => await this.loadCampaigns());
    }

    async loadCampaigns() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "call.campaign", "get_campaign_dashboard_data", [], {}
            );
            this.state.campaigns = data.campaigns;
            this.state.stats = data.stats;
            this.state.role = data.role;
        } catch (e) {
            this.notification.add("Error loading campaigns: " + e.message, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    get filteredCampaigns() {
        let list = this.state.campaigns;
        if (this.state.filter === "running") list = list.filter(c => c.state === "running");
        else if (this.state.filter === "draft")   list = list.filter(c => c.state === "draft");
        else if (this.state.filter === "done")    list = list.filter(c => c.state === "done");
        else if (this.state.filter === "mine")    list = list.filter(c => c.is_mine);
        if (this.state.search) {
            const q = this.state.search.toLowerCase();
            list = list.filter(c =>
                c.name.toLowerCase().includes(q) ||
                (c.created_by || "").toLowerCase().includes(q)
            );
        }
        return list;
    }

    setFilter(f) { this.state.filter = f; }
    onSetFilter(f) { return () => { this.state.filter = f; }; }

    onSearchInput(ev) { this.state.search = ev.target.value; }

    openRunner(campaignId, campaignName) {
        this.action.doAction({
            type: "ir.actions.client",
            tag: "call_campaign_runner",
            name: "📞 " + campaignName,
            params: { campaign_id: campaignId },
        });
    }

    openForm(campaignId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "call.campaign",
            res_id: campaignId,
            views: [[false, "form"]],
            target: "main",
        });
    }

    createNew() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "call.campaign",
            views: [[false, "form"]],
            target: "main",
        });
    }

    progressPct(c) {
        if (!c.total) return 0;
        return Math.round((c.called / c.total) * 100);
    }

    stateLabel(state) {
        return { draft: "Draft", running: "Running", done: "Done", cancelled: "Cancelled" }[state] || state;
    }

    stateClass(state) {
        return {
            draft: "o_cc_badge_draft",
            running: "o_cc_badge_running",
            done: "o_cc_badge_done",
            cancelled: "o_cc_badge_cancelled",
        }[state] || "";
    }
}

registry.category("actions").add("call_campaign_dashboard", CallCampaignDashboard);
