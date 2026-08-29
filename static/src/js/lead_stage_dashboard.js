/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const STAGES = [
    { key: "funnel",         label: "Funnel",      caption: "Fresh leads entering the sales funnel",    icon: "fa-filter",         accent: "funnel" },
    { key: "prospects",      label: "Prospects",   caption: "Qualified leads ready for counselling",    icon: "fa-user",           accent: "prospect" },
    { key: "rnr_dnp",        label: "RNR / DNP",   caption: "Ringing, not reachable, or did not pick", icon: "fa-phone",          accent: "rnr" },
    { key: "admission_done", label: "Admissions",  caption: "Converted leads — admission completed",   icon: "fa-graduation-cap", accent: "admission" },
    { key: "re_try",         label: "Re-Try",      caption: "Leads being followed up again",           icon: "fa-refresh",        accent: "retry" },
    { key: "alumni",         label: "Alumni",      caption: "Past students and existing alumni",       icon: "fa-star",           accent: "alumni" },
    { key: "junk",           label: "Junk",        caption: "Invalid or irrelevant leads",             icon: "fa-trash",          accent: "junk" },
];

const DATE_FILTERS = [
    { key: "today", label: "Today" },
    { key: "week",  label: "This Week" },
    { key: "month", label: "This Month" },
    { key: "all",   label: "All Time" },
];

export class LeadStageDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            counts: {},
            total: 0,
            totalCalls: 0,
            loading: true,
            isAdmissionOfficer: false,
            officers: [],
            performers: { day: null, week: null, month: null },
            officerSearch: "",
            dateFilter: "month",
        });
        onWillStart(() => this.loadCounts());
    }

    get stages() { return STAGES; }
    get dateFilters() { return DATE_FILTERS; }

    getStageCount(key) { return this.state.counts[key] || 0; }
    getStagePercent(key) {
        if (!this.state.total) return 0;
        return Math.round((this.getStageCount(key) / this.state.total) * 100);
    }

    // Footer of the officer table sums only the officers actually listed
    // (active, currently-assigned officers) so it always matches the rows
    // shown above it, rather than an org-wide figure that could include
    // resigned staff or leads with no owner.
    getOfficersStageTotal(key) {
        return this.state.officers.reduce((s, o) => s + (o.counts[key] || 0), 0);
    }
    get officersGrandTotal() {
        return this.state.officers.reduce((s, o) => s + (o.total || 0), 0);
    }

    get filteredOfficers() {
        const q = (this.state.officerSearch || "").toLowerCase().trim();
        const list = q ? this.state.officers.filter(o => o.name.toLowerCase().includes(q)) : this.state.officers;
        return list;
    }

    async setDateFilter(key) {
        if (this.state.dateFilter === key) return;
        this.state.dateFilter = key;
        await this.loadCounts();
    }

    async loadCounts() {
        this.state.loading = true;
        const result = await this.orm.call("leads.logic", "get_dashboard_stage_counts", [], { date_filter: this.state.dateFilter });
        this.state.counts = result.counts || {};
        this.state.isAdmissionOfficer = result.is_admission_officer || false;
        this.state.officers = result.officers || [];
        this.state.performers = result.performers || { day: null, week: null, month: null };
        this.state.total = Object.values(this.state.counts).reduce((s, v) => s + v, 0);
        this.state.totalCalls = this.state.officers.reduce((s, o) => s + (o.calls || 0), 0);
        this.state.loading = false;
    }

    get callsPeriodLabel() {
        const df = this.dateFilters.find(d => d.key === this.state.dateFilter);
        return df ? df.label : "";
    }

    openStage(stageKey) {
        const stage = STAGES.find(s => s.key === stageKey);
        const domain = [["lead_stage_category", "=", stageKey]];
        const context = {};
        if (this.state.isAdmissionOfficer) context.search_default_lead_owner = true;
        this.action.doAction({
            type: "ir.actions.act_window", name: stage ? stage.label : "Leads",
            res_model: "leads.logic", views: [[false, "list"], [false, "form"]],
            domain, context, target: "current",
        });
    }

    openOfficerStage(officerId, stageKey) {
        const stage = STAGES.find(s => s.key === stageKey);
        const officer = this.state.officers.find(o => o.id === officerId);
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `${officer ? officer.name : "Officer"} — ${stage ? stage.label : stageKey}`,
            res_model: "leads.logic", views: [[false, "list"], [false, "form"]],
            domain: [["lead_owner", "=", officerId], ["lead_stage_category", "=", stageKey]],
            target: "current",
        });
    }

    openOfficerAll(officerId) {
        const officer = this.state.officers.find(o => o.id === officerId);
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `${officer ? officer.name : "Officer"} — All Leads`,
            res_model: "leads.logic", views: [[false, "list"], [false, "form"]],
            domain: [["lead_owner", "=", officerId]], target: "current",
        });
    }

    openOfficerCalls(officerId) {
        const officer = this.state.officers.find(o => o.id === officerId);
        const labels = { today: "Today", week: "This Week", month: "This Month", all: "All Time" };
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `${officer ? officer.name : "Officer"} — Calls (${labels[this.state.dateFilter] || ""})`,
            res_model: "lead.call.log", views: [[false, "list"], [false, "form"]],
            domain: [["user_id.employee_id", "=", officerId]], target: "current",
        });
    }

    openPerformerAdmissions(officerId, period) {
        const labels = { day: "Today", week: "This Week", month: "This Month" };
        const performer = this.state.performers[period];
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `${performer ? performer.name : "Officer"} — Admissions (${labels[period] || period})`,
            res_model: "leads.logic", views: [[false, "list"], [false, "form"]],
            domain: [["lead_owner", "=", officerId], ["lead_stage_category", "=", "admission_done"]],
            target: "current",
        });
    }

    openAnalysis() {
        this.action.doAction("custom_leads.action_lead_stage_analysis");
    }
}

LeadStageDashboard.template = "custom_leads.LeadStageDashboard";
registry.category("actions").add("custom_leads.lead_stage_dashboard", LeadStageDashboard);
