from odoo import fields, models, api, _

class AllocationTeleCallersWizard(models.TransientModel):
    _name = 'allocation.tele_callers.wizard'
    _description = 'Allocation'

    assign_to = fields.Many2one('res.users', string='Telecaller')

    def action_add_assigned_user(self):
        print(self._context['parent_obj'], 'parent_obj')

        leads = self.env['leads.logic'].sudo().search([('id', '=', self._context['parent_obj'])])
        for rec in leads:
            print(rec, 'recccc')
            rec.sudo().write({
                'tele_caller_id': self.assign_to.id,
                # 'lead_quality': 'nil',
                # 'leads_assign': False,
                'assigned_date': fields.Datetime.now(),
                # 'over_due': False
            })
            rec.activity_schedule('custom_leads.mail_activity_lead_tasks', user_id= rec.tele_caller_id.id,
                                  note=f' You have been assigned new lead.')

    def action_add_assign_to_lead_owner(self):
        print(self._context['parent_obj'], 'parent_obj')

        leads = self.env['leads.logic'].sudo().search([('id', '=', self._context['parent_obj'])])
        for rec in leads:
            print(rec, 'recccc')
            rec.sudo().write({
                'lead_owner': self.assign_to.employee_id.id,
                # 'lead_quality': 'nil',
                # 'leads_assign': False,
                'assigned_date': fields.Datetime.now(),
                # 'over_due': False
            })
            rec.activity_schedule('custom_leads.mail_activity_lead_tasks', user_id=rec.lead_owner.user_id.id,
                                  note=f' You have been assigned new lead.')

class ReAllocationLeads(models.TransientModel):
   _name = 're.allocation.leads'
   _description = "Re Allocation Leads Wizard"

   lead_owner_id = fields.Many2one('res.users', string="Lead Owner")
   leads_ids = fields.Many2many('leads.logic', string="Leads")

   def act_re_allocation(self):
       for i in self.leads_ids:
           i.lead_owner = self.lead_owner_id.employee_id.id
           i.re_allocation_date = fields.Datetime.now()
           i.message_post(body=f"Lead re-allocated to {self.lead_owner_id.employee_id.name}")
