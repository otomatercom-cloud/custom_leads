/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const ACCENTS = ["a1", "a2", "a3", "a4", "a5", "a6"];

function todayStr() {
    return new Date().toISOString().slice(0, 10);
}

function initials(name) {
    if (!name) return "?";
    const parts = name.trim().split(/\s+/);
    return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}

export class CallPerformanceDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            agents: [],
            totals: { total: 0, incoming: 0, outgoing: 0, answered: 0, not_answered: 0 },
            loading: true,
            dateFrom: "",
            dateTo: "",
        });
        onWillStart(() => this.loadCounts());
    }

    accentFor(index) { return ACCENTS[index % ACCENTS.length]; }
    initialsFor(name) { return initials(name); }

    async loadCounts() {
        this.state.loading = true;
        const result = await this.orm.call(
            "lead.call.log", "get_call_performance_counts", [],
            { date_from: this.state.dateFrom || false, date_to: this.state.dateTo || false }
        );
        this.state.agents = result.agents || [];
        this.state.totals = result.totals || { total: 0, incoming: 0, outgoing: 0, answered: 0, not_answered: 0 };
        this.state.loading = false;
    }

    async onDateChange(field, ev) {
        this.state[field] = ev.target.value;
        await this.loadCounts();
    }

    today() {
        this.state.dateFrom = todayStr();
        this.state.dateTo = todayStr();
        this.loadCounts();
    }

    thisMonth() {
        const now = new Date();
        this.state.dateFrom = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10);
        this.state.dateTo = todayStr();
        this.loadCounts();
    }

    allTime() {
        this.state.dateFrom = "";
        this.state.dateTo = "";
        this.loadCounts();
    }

    _dateDomain() {
        const domain = [];
        if (this.state.dateFrom) domain.push(["call_time", ">=", this.state.dateFrom + " 00:00:00"]);
        if (this.state.dateTo) domain.push(["call_time", "<=", this.state.dateTo + " 23:59:59"]);
        return domain;
    }

    openAgent(userId, name, extra) {
        const domain = [["user_id", "=", userId], ...this._dateDomain(), ...(extra || [])];
        this.action.doAction({
            type: "ir.actions.act_window", name: `Calls — ${name}`,
            res_model: "lead.call.log", views: [[false, "list"], [false, "form"]],
            domain, target: "current",
        });
    }
}

CallPerformanceDashboard.template = "custom_leads.CallPerformanceDashboard";
registry.category("actions").add("custom_leads.call_performance_dashboard", CallPerformanceDashboard);
