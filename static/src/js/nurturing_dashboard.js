/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const CATEGORIES = [
    { key: "plus_one", label: "Plus One", caption: "Plus One students to nurture", icon: "fa-book", accent: "c1" },
    { key: "plus_two", label: "Plus Two", caption: "Plus Two students to nurture", icon: "fa-book", accent: "c2" },
    { key: "bcom_1", label: "B.Com 1st Year", caption: "First-year B.Com students", icon: "fa-graduation-cap", accent: "c3" },
    { key: "bcom_2", label: "B.Com 2nd Year", caption: "Second-year B.Com students", icon: "fa-graduation-cap", accent: "c4" },
    { key: "bcom_3", label: "B.Com 3rd Year", caption: "Third-year B.Com students", icon: "fa-graduation-cap", accent: "c5" },
    { key: "meta_leads", label: "Meta Leads", caption: "Facebook / Instagram / WhatsApp leads", icon: "fa-bullhorn", accent: "c6" },
];

const META_QUALITY = [
    { key: "hot", label: "Hot", icon: "fa-fire" },
    { key: "warm", label: "Warm", icon: "fa-sun-o" },
    { key: "cold", label: "Cold", icon: "fa-snowflake-o" },
];

function todayStr() {
    return new Date().toISOString().slice(0, 10);
}

export class NurturingDashboard extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            counts: {},
            metaQuality: {},
            total: 0,
            loading: true,
            backfilling: false,
            isAdmissionOfficer: false,
            dateFrom: "2026-05-01",
            dateTo: todayStr(),
            activity: { whatsapp: { batches: 0, leads_sent: 0 }, sms: { batches: 0, leads_sent: 0 },
                        call_exports: { batches: 0, leads_sent: 0 }, calls_made: 0 },
        });
        onWillStart(() => this.loadCounts());
    }

    get categories() { return CATEGORIES; }
    get metaQualityOptions() { return META_QUALITY; }

    getCount(key) { return this.state.counts[key] || 0; }
    getMetaQualityCount(key) { return this.state.metaQuality[key] || 0; }

    async loadCounts() {
        this.state.loading = true;
        const [dashboard, activity] = await Promise.all([
            this.orm.call(
                "leads.logic", "get_nurturing_dashboard_counts", [],
                { date_from: this.state.dateFrom || false, date_to: this.state.dateTo || false }
            ),
            this.orm.call(
                "leads.logic", "get_nurturing_activity_counts", [],
                { date_from: this.state.dateFrom || false, date_to: this.state.dateTo || false }
            ),
        ]);
        this.state.counts = dashboard.counts || {};
        this.state.metaQuality = dashboard.meta_quality || {};
        this.state.total = dashboard.total || 0;
        this.state.isAdmissionOfficer = dashboard.is_admission_officer || false;
        this.state.activity = activity;
        this.state.loading = false;
    }

    async onDateChange(field, ev) {
        this.state[field] = ev.target.value;
        await this.loadCounts();
    }

    resetToDefault() {
        this.state.dateFrom = "2026-05-01";
        this.state.dateTo = todayStr();
        this.loadCounts();
    }

    async backfillAll() {
        if (this.state.backfilling) return;
        if (!confirm(
            "This scans every lead with a Lead Source or Campaign set and fills in " +
            "Student Category wherever it's currently empty (existing values are never " +
            "overwritten). It can take a little while for large datasets. Continue?"
        )) return;

        this.state.backfilling = true;
        try {
            const result = await this.orm.call(
                "leads.logic", "recalculate_all_student_categories", [], { force: false }
            );
            this.notification.add(
                `Scanned ${result.scanned} leads — categorised ${result.updated} of them.`,
                { type: "success", title: "Backfill complete" }
            );
            await this.loadCounts();
        } catch (error) {
            this.notification.add(
                "Backfill failed — check you have permission, or try again.",
                { type: "danger", title: "Backfill error" }
            );
        } finally {
            this.state.backfilling = false;
        }
    }

    _dateDomain() {
        const domain = [];
        if (this.state.dateFrom) domain.push(["date_of_adding", ">=", this.state.dateFrom]);
        if (this.state.dateTo) domain.push(["date_of_adding", "<=", this.state.dateTo]);
        return domain;
    }

    openCategory(key) {
        const cat = CATEGORIES.find(c => c.key === key);
        const domain = [["student_category", "=", key], ...this._dateDomain()];
        if (key === "meta_leads") domain.push(["lead_stage_category", "=", "prospects"]);
        this.action.doAction({
            type: "ir.actions.act_window", name: `Nurturing — ${cat ? cat.label : key}`,
            res_model: "leads.logic", views: [[false, "list"], [false, "form"]],
            domain, target: "current",
        });
    }

    openMetaQuality(quality) {
        const q = META_QUALITY.find(m => m.key === quality);
        const domain = [
            ["student_category", "=", "meta_leads"],
            ["lead_stage_category", "=", "prospects"],
            ["lead_quality", "=", quality],
            ...this._dateDomain(),
        ];
        this.action.doAction({
            type: "ir.actions.act_window", name: `Meta Leads — ${q ? q.label : quality}`,
            res_model: "leads.logic", views: [[false, "list"], [false, "form"]],
            domain, target: "current",
        });
    }

    _activityDateDomain(dateField) {
        const domain = [];
        if (this.state.dateFrom) domain.push([dateField, ">=", this.state.dateFrom]);
        if (this.state.dateTo) domain.push([dateField, "<=", this.state.dateTo + " 23:59:59"]);
        return domain;
    }

    openExportHistory(purpose, label) {
        const domain = [["purpose", "=", purpose], ...this._activityDateDomain("export_date")];
        this.action.doAction({
            type: "ir.actions.act_window", name: `Export History — ${label}`,
            res_model: "lead.export.history", views: [[false, "list"], [false, "form"]],
            domain, target: "current",
        });
    }

    openCallLog() {
        const domain = this._activityDateDomain("call_time");
        this.action.doAction({
            type: "ir.actions.act_window", name: "Calls Made",
            res_model: "lead.call.log", views: [[false, "list"], [false, "form"]],
            domain, target: "current",
        });
    }
}

NurturingDashboard.template = "custom_leads.NurturingDashboard";
registry.category("actions").add("custom_leads.nurturing_dashboard", NurturingDashboard);
