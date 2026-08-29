from odoo import models, fields, api

class LeadOpenWizard(models.TransientModel):
    _name = "lead.unlock.wizard"
    _description = "Lead Open Wizard"

    lead_id = fields.Many2one("leads.logic", string="Lead", required=True)

    def action_call(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Lead Details",
            "res_model": "leads.logic",
            "view_mode": "form",
            "res_id": self.lead_id.id,
            "target": "current",
        }

    def action_other(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Lead Details",
            "res_model": "leads.logic",
            "view_mode": "form",
            "res_id": self.lead_id.id,
            "target": "current",
        }
