from odoo import models, fields, api
from datetime import date, datetime, time

class LeadsTodaysFollowupWizard(models.TransientModel):
    _name = 'leads.todays.followup.wizard'
    _description = "Today's Follow-up Wizard"

    lead_ids = fields.Many2many('leads.logic', string="Leads to Follow Up", readonly=True)
    count = fields.Integer(string="Count", compute='_compute_count')

    @api.depends('lead_ids')
    def _compute_count(self):
        for record in self:
            record.count = len(record.lead_ids)

    @api.model
    def default_get(self, fields_list):
        res = super(LeadsTodaysFollowupWizard, self).default_get(fields_list)
        today_date = date.today()
        
        # 1. Search leads with simple Date field 'next_follow_up_date' = today
        domain_1 = [('next_follow_up_date', '=', today_date)]
        
        # 2. Search leads with One2many 'followup_ids' having 'next_followup_date' (Datetime) within today
        start_of_day = datetime.combine(today_date, time.min)
        end_of_day = datetime.combine(today_date, time.max)
        
        # Search in lead.followup 
        # We assume 'scheduled' status is what matters, or just any entry for today? 
        # User said "have today followsups", let's assume scheduled or active ones.
        # Checking 'status' might be safer if it exists, logic was found in leads.py:
        # status = fields.Selection([('scheduled', 'Scheduled')...])
        followups = self.env['lead.followup'].search([
            ('next_followup_date', '>=', start_of_day),
            ('next_followup_date', '<=', end_of_day),
            ('status', '=', 'scheduled')
        ])
        lead_ids_from_followups = followups.mapped('lead_id.id')
        
        # Search leads matching domain_1
        leads_simple = self.env['leads.logic'].search(domain_1)
        
        # Combine IDs
        all_lead_ids = set(leads_simple.ids + lead_ids_from_followups)
        
        # Update res
        res.update({'lead_ids': [(6, 0, list(all_lead_ids))]})
        return res

    def action_open_leads_main(self):
        # Redirect to the Leads list view, filtered by the leads found
        return {
            'type': 'ir.actions.act_window',
            'name': 'Today\'s Follow-ups',
            'res_model': 'leads.logic',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.lead_ids.ids)],
            'target': 'current',
            'context': {'create': False} # Optional: prevent creating new leads from this specific view
        }
