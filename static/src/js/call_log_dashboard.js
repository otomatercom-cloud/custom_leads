/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const DATE_FILTERS = [
    { key: "today", label: "Today" },
    { key: "yesterday", label: "Yesterday" },
    { key: "week", label: "This Week" },
    { key: "month", label: "This Month" },
    { key: "all", label: "All Time" },
];

const KPI_CARDS = [
    { key: "assigned", label: "Assigned", icon: "fa-address-book", accent: "blue" },
    { key: "total_calls", label: "Total Calls", icon: "fa-phone", accent: "purple" },
    { key: "connected", label: "Connected", icon: "fa-check-circle", accent: "green" },
    { key: "outgoing", label: "Outgoing", icon: "fa-arrow-up", accent: "orange" },
    { key: "incoming", label: "Incoming", icon: "fa-arrow-down", accent: "sky" },
    { key: "recordings", label: "Recordings", icon: "fa-microphone", accent: "pink" },
    { key: "called_leads", label: "Called Leads", icon: "fa-users", accent: "violet" },
    { key: "pending", label: "Pending", icon: "fa-hourglass-half", accent: "amber" },
];

export class CallLogDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            role: "officer",
            dateFilter: "today",
            dateFrom: "",
            dateTo: "",
            kpi: {},
            teams: [],
        });
        onWillStart(() => this.loadData());
    }

    get dateFilters() { return DATE_FILTERS; }
    get kpiCards() { return KPI_CARDS; }

    kpiValue(key) {
        if (key === "total_calls" && this.state.kpi.talk_time) {
            return this.state.kpi.total_calls || 0;
        }
        return this.state.kpi[key] || 0;
    }

    async setDateFilter(key) {
        if (this.state.dateFilter === key) return;
        this.state.dateFilter = key;
        await this.loadData();
    }

    async loadData() {
        this.state.loading = true;
        const result = await this.orm.call(
            "lead.call.log", "get_call_log_dashboard_data", [],
            { date_filter: this.state.dateFilter }
        );
        this.state.role = result.role || "officer";
        this.state.dateFrom = result.date_from || "";
        this.state.dateTo = result.date_to || "";
        this.state.kpi = result.kpi || {};
        this.state.teams = result.teams || [];
        this.state.loading = false;
    }

    connectBarColor(pct) {
        if (pct >= 60) return "good";
        if (pct >= 30) return "mid";
        return "low";
    }

    openAgentCalls(agent) {
        if (!agent.user_id) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `${agent.name} — Calls (${this.periodLabel})`,
            res_model: "lead.call.log",
            views: [[false, "list"], [false, "form"]],
            domain: [
                ["user_id", "=", agent.user_id],
                ["call_date", ">=", this.state.dateFrom],
                ["call_date", "<=", this.state.dateTo],
            ],
            target: "current",
        });
    }

    get periodLabel() {
        const df = this.dateFilters.find(d => d.key === this.state.dateFilter);
        return df ? df.label : "";
    }
}

CallLogDashboard.template = "custom_leads.CallLogDashboard";
registry.category("actions").add("call_log_dashboard", CallLogDashboard);
