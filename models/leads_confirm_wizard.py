from odoo import models, fields, api

class LeadsConfirmWizard(models.TransientModel):
    _name = "leads.confirm.wizard"
    _description = "Convert Lead Wizard"

    lead_id = fields.Many2one("leads.logic", string="Lead", required=True)
    name = fields.Char(string="Lead Name", readonly=True)
    phone_number = fields.Char(string="Mobile Number", readonly=True)
    lead_quality = fields.Char(string="Lead Quality", readonly=True)
    
    # Touch points status
    first_call_dt = fields.Datetime(string="First Attempt", readonly=True)
    whatsapp_intro = fields.Boolean(copy=False)
    whatsapp_date = fields.Datetime(string="WhatsApp Intro", readonly=True)
    testimonials = fields.Boolean(copy=False)
    testimonials_dt = fields.Datetime(string="Testimonials", readonly=True)
    results_highlights = fields.Boolean(copy=False)
    results_highlights_dt = fields.Datetime(string="Results", readonly=True)
    second_follow_up = fields.Boolean(copy=False)
    second_follow_up_dt = fields.Datetime(string="Second Follow Up", readonly=True)
    sent_webinar = fields.Boolean(copy=False)
    sent_webinar_dt = fields.Datetime(string="Webinar", readonly=True)
    third_call = fields.Boolean(copy=False)
    third_call_dt = fields.Datetime(string="Third Call", readonly=True)
    touches_complete = fields.Boolean(copy=False)
    touches_complete_dt = fields.Datetime(string="Touches Complete", readonly=True)
    zoom_schedule_dt = fields.Datetime(string="Zoom Schedule Date", readonly=True)
    walkin_schedule_dt = fields.Datetime(string="Walk-in Schedule Date", readonly=True)

    lead_owner_id = fields.Many2one('hr.employee', string="Lead Owner", readonly=True)
    created_by_id = fields.Many2one('res.users', string="Created By", readonly=True)
    
    today_followup_message = fields.Text(string="Today's Follow-up Message", readonly=True)
    team_lead_remarks = fields.Text(string="Team Lead Remarks")

    @api.model
    def default_get(self, fields_list):
        res = super(LeadsConfirmWizard, self).default_get(fields_list)
        
        # Fetch global remarks
        global_remarks = self.env['ir.config_parameter'].sudo().get_param('custom_leads.global_team_lead_remarks', default='')
        res.update({'team_lead_remarks': global_remarks})

        if self.env.context.get('default_lead_id'):
            lead = self.env['leads.logic'].browse(self.env.context['default_lead_id'])
            if lead.exists():
                res.update({
                    'name': lead.name,
                    'phone_number': lead.phone_number,
                    'lead_quality': lead.lead_quality,
                    'lead_owner_id': lead.lead_owner.id,
                    'created_by_id': lead.create_uid.id,
                    'first_call_dt': lead.first_call_dt,
                    'whatsapp_intro': lead.whatsapp_intro,
                    'whatsapp_date': lead.whatsapp_date,
                    'testimonials': lead.testimonials,
                    'testimonials_dt': lead.testimonials_dt,
                    'results_highlights': lead.results_highlights,
                    'results_highlights_dt': lead.results_highlights_dt,
                    'second_follow_up': lead.second_follow_up,
                    'second_follow_up_dt': lead.second_follow_up_dt,
                    'sent_webinar': lead.sent_webinar,
                    'sent_webinar_dt': lead.sent_webinar_dt,
                    'third_call_dt': lead.third_call_dt,
                    'touches_complete': lead.touches_complete,
                    'touches_complete_dt': lead.touches_complete_dt,
                    'zoom_schedule_dt': lead.zoom_schedule_dt,
                    'walkin_schedule_dt': lead.walkin_schedule_dt,
                })

                # Check for Today's Follow-up Message from lead.followup
                today_start = fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                today_end = fields.Datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)
                
                # Fetch ANY scheduled follow-up for THIS USER today, for ANY lead
                followup_domain = [
                    ('user_id', '=', self.env.user.id),
                    ('status', '=', 'scheduled'),
                    ('next_followup_date', '>=', today_start),
                    ('next_followup_date', '<=', today_end)
                ]
                
                followups = self.env['lead.followup'].sudo().search(followup_domain)
                
                if followups:
                    msgs = []
                    for f in followups:
                        lead_name = f.lead_id.name or 'Unknown Lead'
                        time_str = f.next_followup_date.strftime('%H:%M') if f.next_followup_date else ''
                        msgs.append(f"⏰ [{time_str}] {f.remarks or 'No Remarks'} (Lead: {lead_name})")
                    res['today_followup_message'] = "\n".join(msgs)

        return res

    def action_first_attempt(self):
        self.ensure_one()
        self.lead_id.write({
            'state': 'in_progress',
            'first_call_dt': fields.Datetime.now(),
            'first_call': True,
            'lead_quality': 'first_attempt'
        })
        # Log note
        self.lead_id.message_post(body=f"First Attempt status updated via wizard by {self.env.user.name}")
        return {
            "type": "ir.actions.act_window",
            "name": "Lead Details",
            "res_model": "leads.logic",
            "view_mode": "form",
            "views": [[False, 'form']],
            "res_id": self.lead_id.id,
            "target": "current",
        }

    def action_send_whatsapp(self):
        self.ensure_one()
        if not self.phone_number:
            return {'type': 'ir.actions.act_window_close'}
        
        # Update lead
        self.lead_id.write({
            'whatsapp_intro': True,
            'whatsapp_date': fields.Datetime.now()
        })
        self.lead_id.message_post(body=f"WhatsApp Intro sent via wizard by {self.env.user.name}")

        url = "https://web.whatsapp.com/send?phone=" + self.phone_number
        return {
            'type': 'ir.actions.act_url',
            'name': "Leads Whatsapp",
            'target': 'new',
            'url': url,
        }

    def action_send_testimonials(self):
        self.ensure_one()
        if not self.phone_number:
            return {'type': 'ir.actions.act_window_close'}

        # Update lead
        self.lead_id.write({
            'testimonials': True,
            'testimonials_dt': fields.Datetime.now()
        })
        self.lead_id.message_post(body=f"Testimonials sent via wizard by {self.env.user.name}")

        url = "https://web.whatsapp.com/send?phone=" + self.phone_number
        return {
            'type': 'ir.actions.act_url',
            'name': "Leads Whatsapp (Testimonials)",
            'target': 'new',
            'url': url,
        }

    def action_send_results(self):
        self.ensure_one()
        if not self.phone_number:
            return {'type': 'ir.actions.act_window_close'}

        # Update lead
        self.lead_id.write({
            'results_highlights': True,
            'results_highlights_dt': fields.Datetime.now()
        })
        self.lead_id.message_post(body=f"Results sent via wizard by {self.env.user.name}")

        url = "https://web.whatsapp.com/send?phone=" + self.phone_number
        return {
            'type': 'ir.actions.act_url',
            'name': "Leads Whatsapp (Results)",
            'target': 'new',
            'url': url,
        }

    def action_second_follow_up(self):
        self.ensure_one()
        # Update lead
        self.lead_id.write({
            'second_follow_up': True,
            'second_follow_up_dt': fields.Datetime.now()
        })
        self.lead_id.message_post(body=f"Second Follow Up initiated via wizard by {self.env.user.name}")

        return {
            "type": "ir.actions.act_window",
            "name": "Lead Details",
            "res_model": "leads.logic",
            "view_mode": "form",
            "views": [[False, 'form']],
            "res_id": self.lead_id.id,
            "target": "current",
        }

    def action_send_webinar(self):
        self.ensure_one()
        if not self.phone_number:
             return {'type': 'ir.actions.act_window_close'}
        
        # Update lead
        self.lead_id.write({
            'sent_webinar': True,
            'sent_webinar_dt': fields.Datetime.now()
        })
        self.lead_id.message_post(body=f"Webinar sent via wizard by {self.env.user.name}")

        url = "https://web.whatsapp.com/send?phone=" + self.phone_number
        return {
            'type': 'ir.actions.act_url',
            'name': "Leads Whatsapp (Webinar)",
            'target': 'new',
            'url': url,
        }

    def action_third_call(self):
        self.ensure_one()
        # Update lead
        self.lead_id.write({
            'third_call': True,
            'third_call_dt': fields.Datetime.now()
        })
        self.lead_id.message_post(body=f"Third Call initiated via wizard by {self.env.user.name}")

        return {
            "type": "ir.actions.act_window",
            "name": "Lead Details",
            "res_model": "leads.logic",
            "view_mode": "form",
            "views": [[False, 'form']],
            "res_id": self.lead_id.id,
            "target": "current",
        }

    def action_touches_complete(self):
        self.ensure_one()
        # Update lead
        self.lead_id.write({
            'touches_complete': True,
            'touches_complete_dt': fields.Datetime.now()
        })
        self.lead_id.message_post(body=f"Touches Completed via wizard by {self.env.user.name}")

        return {
            "type": "ir.actions.act_window",
            "name": "Lead Details",
            "res_model": "leads.logic",
            "view_mode": "form",
            "views": [[False, 'form']],
            "res_id": self.lead_id.id,
            "target": "current",
        }

    def action_waiting_for_admission(self):
        self.ensure_one()
        return self.lead_id.act_admission()

    def action_schedule_meeting(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Schedule Meeting',
            'res_model': 'leads.schedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.lead_id.id},
        }

    def action_save_remarks(self):
        # Save to global config parameter
        self.env['ir.config_parameter'].sudo().set_param('custom_leads.global_team_lead_remarks', self.team_lead_remarks or '')
        
        # Optional: Log to the current lead's chatter that the global message was viewed/updated? 
        # Or just notify.
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'Global Team Message Updated!',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'} # Close wizard after save? Or let them stay?
            }
        }

    def action_confirm(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Lead Details",
            "res_model": "leads.logic",
            "view_mode": "form",
            "res_id": self.lead_id.id,
            "target": "current",
        }

    def action_dismiss_message(self):
        self.ensure_one()
        self.write({'today_followup_message': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'leads.confirm.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
             # Ensure we don't open a new empty wizard, but the existing one
        }

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}

    def action_confirm(self):
        self.ensure_one()

        # create history record
        self.env['lead.open.history'].create({
            'lead_id': self.lead_id.id,
            'user_id': self.env.user.id,
            'remarks': 'Lead opened from confirm wizard',
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'leads.logic',
            'res_id': self.lead_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
