/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const QUALITY_LABELS = {
    new: "🆕 New", hot: "🔥 Hot", warm: "🌞 Warm", cold: "❄️ Cold",
    first_attempt: "🎯 First Attempt", waiting_for_admission: "⏳ Waiting",
    admission: "🎓 Admission", not_responding: "🔕 Not Responding",
    call_later: "📞 Call Later", may_be_later: "🔔 May Be Later",
    follow_up: "⏰ Follow Up", not_reachable: "🚫 Not Reachable",
    bad_lead: "⚠️ Language Barrier", crash_lead: "💥 Crash Lead",
    already_joined: "✅ Already Joined", joined_other_institute: "🏫 Other Institute",
    wrong_number: "📵 Wrong Number", not_enquiry: "🛑 Not Enquiry",
};

const QUALITY_OPTIONS = Object.entries(QUALITY_LABELS).map(([v, l]) => ({ value: v, label: l }));

class CallCampaignRunner extends Component {
    static template = "custom_leads.CallCampaignRunner";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            campaignName: "",
            leads: [],
            currentIndex: 0,
            total: 0,
            calledCount: 0,
            showResponseForm: false,
            callActive: false,
            selectedQuality: "",
            responseText: "",
            submitting: false,
            done: false,
            showSidebar: false,
        });

        const params = this.props.action.params || {};
        this.campaignId = params.campaign_id || null;

        onWillStart(async () => {
            if (this.campaignId) {
                await this.loadLeads();
            } else {
                this.state.loading = false;
            }
        });
    }

    async loadLeads() {
        const data = await this.orm.call("call.campaign", "get_campaign_leads", [this.campaignId]);
        this.state.leads = data.leads;
        this.state.campaignName = data.campaign_name;
        this.state.total = data.total || 0;
        this.state.calledCount = data.called || 0;

        const firstPending = data.leads.findIndex(l => !l.called);
        this.state.currentIndex = firstPending >= 0 ? firstPending : 0;
        this.state.loading = false;
        this.state.done = data.leads.every(l => l.called);
    }

    get currentLead() {
        return this.state.leads[this.state.currentIndex] || null;
    }

    get progress() {
        if (!this.state.total) return 0;
        return Math.round((this.state.calledCount / this.state.total) * 100);
    }

    get qualityOptions() {
        return QUALITY_OPTIONS;
    }

    onClickCall() {
        const lead = this.currentLead;
        if (!lead) return;
        window.open("tel:" + lead.phone, "_blank");
        this.state.callActive = true;
        this.state.showResponseForm = true;
        this.state.selectedQuality = lead.quality || "new";
        this.state.responseText = "";
    }

    onQualityChange(ev) {
        this.state.selectedQuality = ev.target.value;
    }

    onResponseInput(ev) {
        this.state.responseText = ev.target.value;
    }

    async onSubmitResponse() {
        const lead = this.currentLead;
        if (!lead) return;
        this.state.submitting = true;

        try {
            await this.orm.call("call.campaign", "submit_call_response", [
                this.campaignId,
                lead.id,
                this.state.selectedQuality,
                this.state.responseText,
            ]);

            this.state.leads[this.state.currentIndex].called = true;
            this.state.leads[this.state.currentIndex].quality = this.state.selectedQuality;
            this.state.leads[this.state.currentIndex].call_response = this.state.responseText;
            this.state.calledCount++;
            this.state.showResponseForm = false;
            this.state.callActive = false;

            const nextIndex = this.state.leads.findIndex(
                (l, i) => i > this.state.currentIndex && !l.called
            );

            if (nextIndex >= 0) {
                this.state.currentIndex = nextIndex;
            } else {
                const anyPending = this.state.leads.find(l => !l.called);
                if (!anyPending) {
                    this.state.done = true;
                    this.notification.add("🎉 Campaign completed! All leads called.", { type: "success" });
                }
            }
        } catch (e) {
            this.notification.add("Error saving response: " + e.message, { type: "danger" });
        } finally {
            this.state.submitting = false;
        }
    }

    onSkip() {
        const nextIndex = this.state.leads.findIndex(
            (l, i) => i > this.state.currentIndex && !l.called
        );
        if (nextIndex >= 0) {
            this.state.currentIndex = nextIndex;
        }
        this.state.showResponseForm = false;
        this.state.callActive = false;
    }

    onSelectLead(index) {
        this.state.currentIndex = index;
        this.state.showResponseForm = false;
        this.state.callActive = false;
    }

    toggleSidebar() {
        this.state.showSidebar = !this.state.showSidebar;
    }

    onBackToCampaign() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "call.campaign",
            res_id: this.campaignId,
            views: [[false, "form"]],
            target: "main",
        });
    }
}

registry.category("actions").add("call_campaign_runner", CallCampaignRunner);
