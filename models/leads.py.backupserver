from tokenize import String

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import date, datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


class LeadsForm(models.Model):
    _name = 'leads.logic'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Leads'
    _rec_name = 'name'
    _order = 'id desc'

    leads_source = fields.Many2one('leads.sources', string='Leads Source', required=1)
    source_name = fields.Char(string="Source", related="leads_source.name")
    name = fields.Char(string='Lead Name', required=1)
    email_address = fields.Char(string='Email')
    phone_number = fields.Char(string='Mobile', required=1)
    probability = fields.Float(string='Probability')
    admission_status = fields.Boolean(string='Admission', readonly=1)
    date_of_adding = fields.Date(string='Date of Adding', default=fields.Datetime.now, readonly=1)
    last_update_date = fields.Datetime(string='Last Updated Date', default=fields.Datetime.now)
    course_id = fields.Many2one('op.course', string='Course')
    reference_no = fields.Char("Reference", default=lambda self: _('New'),
                               copy=False, readonly=True, tracking=True)
    # touch_ids = fields.One2many('leads.own.touch.points', 'touch_id', string='Touch Points')
    lead_quality = fields.Selection(
        [('new', '🆕  New'), ('waiting_for_admission', '⏳  Waiting for Admission'), ('admission', '🎓  Admission'),
         ('hot', '🔥  Hot'),
         ('warm', '🌞  Warm'), ('cold', '❄️  Cold'),
         ('bad_lead', '⚠️  Bad Lead'), ('crash_lead', '💥  Crash Lead'), ('not_responding', '🚫  Not Responding')],
        string='Lead Quality', default='new', required=1, readonly=0, tracking=1)

    # def _get_lead_quality_color(self):
    #     _logger.info("Calling _get_lead_quality_color for lead_quality: %s", self.lead_quality)
    #     colors = {
    #         'new': 'grey',
    #         'waiting_for_admission': 'blue',
    #         'admission': 'green',
    #         'hot': 'red',
    #         'warm': 'yellow',
    #         'cold': 'lightblue',
    #         'bad_lead': 'darkred',
    #         'crash_lead': 'orange',
    #         'not_responding': 'grey',
    #     }
    #     return dict((key, colors[key]) for key in self.lead_quality)

    lost_reason = fields.Text(string="Lost Reason")
    crash_user_id = fields.Many2one('res.users', string="Crash User")
    lead_status = fields.Selection(
        [('not_responding', 'Not Responding'),
         ('already_enrolled', 'Already Enrolled'), ('joined_in_another_institute', 'Joined in another institute'),
         ('nil', 'Nil')],
        string='Lead Status',
    )
    place = fields.Char('Place')
    # leads_assign = fields.Many2one('hr.employee', string='Assign to', )
    lead_owner = fields.Many2one('hr.employee', string='Lead Owner', default=lambda self: self.env.user.employee_id.id)
    seminar_lead_id = fields.Char()

    admission_date = fields.Datetime(string="Admission Date")
    phone_number_second = fields.Char(string='Phone Number')
    branch_id = fields.Many2one('op.branch', string="Branch")
    course_interested = fields.Char(string="Course Interested")
    seminar_id = fields.Integer(string="Seminar")
    preferred_course = fields.Char(string="Preferred Course")
    academic_year_of_course_attend = fields.Selection(
        [('2023-2024', '2023-2024'), ('2024-2025', '2024-2025'), ('2025-2026', '2025-2026'),
         ('2026-2027', '2026-2027')], string="Academic Year of Course attended")
    course_type = fields.Selection(
        [('indian', 'Indian'), ('international', 'International'), ('crash', 'Crash'), ('repeaters', 'Repeaters'),
         ('nil', 'Nil')],
        string='Course Type')
    state = fields.Selection(
        [('new', 'New'), ('in_progress', 'In Progress'), ('qualified', 'Admission'),
         ('lost', 'Lost')],
        string='State',
        default='new', tracking=True)
    last_studied_course = fields.Char(string='Last Studied Course')
    incoming_source = fields.Selection(
        [('social_media', 'Social Media'), ('google', 'Google'), ('hoardings', 'Hoardings'), ('tv_ads', 'TV Ads'),
         ('through friends', 'Through Friends'), ('whatsapp', 'WhatsApp'), ('re_admission', 'Re-Admission'),
         ('other', 'Other')],
        string='Incoming Calls / Walk In Source')
    incoming_source_checking = fields.Boolean(string='Incoming Source Checking', )
    academic_year = fields.Selection(
        [('2024-2025', '2024-2025'), ('2025-2026', '2025-2026'), ('2026-2027', '2026-2027'), ('nil', 'Nil')],
        string="Academic Year")
    college_name = fields.Char(string='College/School')
    title = fields.Char(string="Title")
    lead_referral_staff_id = fields.Many2one('res.users', string='Lead Referral Staff')
    referred_by = fields.Selection([('staff', 'Staff'), ('student', 'Student'), ('other', 'Other')],
                                   string='Referred By')
    # campaign_name = fields.Char(string='Campaign Name')
    campaign = fields.Selection(
        [('CA Weekend Thrissur', 'CA Weekend Thrissur'), ('CA Weekend Ernakulam', 'CA Weekend Ernakulam'),
         ('CA Weekend Trivandrum', 'CA Weekend Trivandrum'), ('CA Weekend Calicut', 'CA Weekend Calicut'),
         ('CA Weekend Perintalmanna', 'CA Weekend Perintalmanna')], string='Campaign')
    country = fields.Selection(
        [('india', 'India'), ('germany', 'Germany'), ('canada', 'Canada'), ('usa', 'USA'), ('australia', 'Australia'),
         ('italy', 'Italy'), ('france', 'France'), ('united_kingdom', 'United Kingdom'),
         ('saudi_arabia', 'Saudi Arabia'), ('ukraine', 'Ukraine'), ('united_arab_emirates', 'United Arab Emirates'),
         ('china', 'China'), ('japan', 'Japan'), ('singapore', 'Singapore'), ('indonesia', 'Indonesia'),
         ('russia', 'Russia'), ('oman', 'Oman'), ('nepal', 'Nepal'), ('japan', 'Japan')],
        string='Country', default='india')
    referred_by_id = fields.Many2one('hr.employee', string='Referred Person')
    second_response = fields.Text(string="2nd Response")
    referred_by_name = fields.Char(string='Referred Person')
    referred_by_number = fields.Char(string='Referred Person Number')
    batch_preference = fields.Char(string='Batch Preference')
    tele_caller_id = fields.Many2one('res.users', String="Tele Caller")
    # booking_amount = fields.Float(string="Booking Amount")
    lead_qualification = fields.Selection(
        [('plus_one_science', 'Plus One Science'), ('plus_two_science', 'Plus Two Science'),
         ('plus_two_commerce', 'Plus Two Commerce'), ('plus_one_commerce', 'Plus One Commerce'),
         ('commerce_degree', 'Commerce Degree'),
         ('other_degree', 'Other Degree'), ('working_professional', 'Working Professional')],
        string='Lead qualification')
    adm_id = fields.Integer(string='Admission Id')
    student_id = fields.Many2one('op.student', string='Student Id')
    district = fields.Selection([('wayanad', 'Wayanad'), ('ernakulam', 'Ernakulam'), ('kollam', 'Kollam'),
                                 ('thiruvananthapuram', 'Thiruvananthapuram'), ('kottayam', 'Kottayam'),
                                 ('kozhikode', 'Kozhikode'), ('palakkad', 'Palakkad'), ('kannur', 'Kannur'),
                                 ('alappuzha', 'Alappuzha'), ('malappuram', 'Malappuram'), ('kasaragod', 'Kasaragod'),
                                 ('thrissur', 'Thrissur'), ('idukki', 'Idukki'), ('pathanamthitta', 'Pathanamthitta'),
                                 ('abroad', 'Abroad'), ('other', 'Other'), ('nil', 'Nil')],
                                string='District')
    referred_teacher = fields.Many2one('res.users', string='Referred Teacher')
    over_due = fields.Boolean(string='Over Due')
    next_follow_up_date = fields.Date(string="Next Follow Up Date")
    remarks = fields.Char(string='Remarks')
    parent_number = fields.Char('Parent Number')
    closing_date = fields.Date(string="Closing Date")
    call_responses = fields.Many2many('call.responses', string="Call Responses", compute='_compute_total_responses',
                                      store=1)
    third_response = fields.Text(string="Last Response")
    # amount = fields.Float(string="Amount")
    mode_of_study = fields.Selection([('online', 'Online'), ('offline', 'Offline'), ('nil', 'Nil')],
                                     string='Mode of Study')
    company_id = fields.Many2one(string='Company', comodel_name='res.company', required=True,
                                 default=lambda self: self.env.company)
    assigned_date = fields.Date(string='Assigned Date', compute="_compute_lead_owner", store=1)
    digital_lead = fields.Boolean(string="Digital Lead")
    digital_lead_source = fields.Selection(
        [('just_dial', 'Just Dial'), ('youtube_google', 'Youtube - Google'), ('whatsapp_campaign', 'Whatsapp Campaign'),
         ('messenger', 'Messenger'), ('facebook', 'Facebook'), ('linkedin', 'Linkedin'), ('instagram', 'Instagram'),
         ('whatsapp_meta', 'Whatsapp Meta'), ('website', 'Website'), ('google', 'Google')],
        string="Digital Lead Source")
    platform = fields.Selection(
        [('facebook', 'Facebook'), ('instagram', 'Instagram'), ('website', 'Website'), ('just_dial', 'Just Dial'),
         ('other', 'Other')],
        string='Platform')
    expected_joining_date = fields.Date(string="Expected Joining Date")
    not_response_note = fields.Text(string="Not Respond Reason")
    # lead_type = fields.Selection([('regular_lead', 'Regular Lead'), ('crash_lead','Crash Lead')], default='regular_lead', required=1)
    current_status = fields.Selection(
        [('new_lead', 'New Lead'), ('not_responding', 'Not Responding'), ('need_follow_up', 'Need Follow-Up'),
         ('admission', 'Admission'), ('lost', 'Lost')], string="Current Status", default="new_lead")
    call_response = fields.Text(string="Response")
    transitions = fields.Selection(
        [('future_lead', 'Future Lead'), ('junk_lead', 'Junk Lead'), ('not_qualified', 'Not Qualified'),
         ('qualified', 'Qualified')], string="Transitions", tracking=1)
    sample = fields.Char(string='Sample', compute='get_phone_number_for_whatsapp')
    sended_welcome_mail = fields.Boolean(string="Sended Welcome Mail")
    receipt_no = fields.Char(string="Receipt No.")
    admission_amount = fields.Float(string="Admission Fee")
    date_of_receipt = fields.Date(string="Date of Receipt")
    student_profile_created = fields.Boolean(string="Student Profile Created")
    crash_lead = fields.Boolean(string="Crash Lead")

    @api.onchange('call_response')
    def _onchange_call_response(self):
        for record in self:
            if record.call_response:
                # Search or create the response object
                response_obj = self.env['call.responses'].search([('name', '=', record.call_response)], limit=1)
                if not response_obj:
                    response_obj = self.env['call.responses'].create({'name': record.call_response})
                # Ensure the Many2many field includes the new response
                record.call_responses = [(4, response_obj.id)]  # Append to existing Many2many
                # Reset the single response field
                # record.call_response = False

    def write(self, vals):
        # print(vals['call_responses'], 'res')
        if 'phone_number' in vals:
            vals['phone_number'] = vals['phone_number'].replace(" ", "")

        if 'call_response' in vals and vals['call_response']:
            print(vals['call_response'], 'res')
            response_obj = self.env['call.responses'].search([('name', '=', vals['call_response'])], limit=1)
            if not response_obj:
                response_obj = self.env['call.responses'].create({'name': vals['call_response']})

            # Add to Many2many
            if 'call_responses' in vals:
                vals['call_responses'].append((4, response_obj.id))
            else:
                vals['call_responses'] = [(4, response_obj.id)]

            vals['call_response'] = False  # Clear the field after saving

        return super(LeadsForm, self).write(vals)

    @api.onchange('leads_source')
    def _onchange_leads_source(self):
        if self.leads_source:
            self.source_name = self.leads_source.name
            if 'incoming' in self.source_name.lower() or 'walk in' in self.source_name.lower():
                # Do something when 'incoming' is in the source name
                self.incoming_source_checking = True

            else:
                self.incoming_source_checking = 0
                self.incoming_source = False
            if self.leads_source.digital_lead == 1:
                self.digital_lead = 1
            else:
                self.digital_lead = 0
                self.digital_lead_source = False

    @api.depends('sample')
    def _compute_display_value(self):
        for record in self:
            if record.sample:
                # Modify the display value as needed based on the original field's value
                modified_value = "Modified: "
                record.sample = modified_value

    def get_current_student_profile(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Student',
            'view_mode': 'tree,form',
            'res_model': 'op.student',
            'domain': [('id', '=', self.student_id.id)],
            'context': "{'create': False}"
        }
    def compute_count_student(self):
        for record in self:
            record.student_smart_count = self.env['op.student'].sudo().search_count(
                [('id', '=', self.student_id.id)])

    student_smart_count = fields.Integer(compute='compute_count_student')

    def get_phone_number_for_whatsapp(self):
        for rec in self:
            # modified_value = "Modified: "
            # rec.sample = 'modified_value'
            if rec.phone_number:
                rec.sample = "https://web.whatsapp.com/send?phone=" + rec.phone_number or "https://api.whatsapp.com/send?phone=" + rec.phone_number
            else:
                rec.sample = ''

    def whatsapp_click_button(self):
        return {
            'type': 'ir.actions.act_url',
            'name': "Leads Whatsapp",
            'target': 'new',
            'url': self.sample,
        }

    batch_id = fields.Many2one('op.batch', string="Batch", domain="[('branch', '=', branch_id),('total_lump_sum_fee', '!=', 0)]")
    batch_fee = fields.Float(string="Expected Revenue", related="batch_id.lump_fee_excluding_tax")

    def act_call_back(self):
        return {'type': 'ir.actions.act_window',
                'name': _('Connect'),
                'res_model': 'connect.form',
                'target': 'new',
                'view_mode': 'form',
                'context': {'default_lead_id': self.id, 'default_task_owner_id': self.lead_owner.user_id.id}, }

    @api.depends('lead_owner')
    def _compute_lead_owner(self):
        print('changed lead owner')
        if self.lead_owner:
            self.assigned_date = fields.Datetime.now()

    @api.onchange('phone_number')
    def _onchange_duplicate_phone_number(self):
        print('hiii')
        active_id = self.env.context.get('active_id')
        for record in self:
            if record.phone_number:
                # Extract last 10 digits
                last_10_digits = record.phone_number[-10:]
                print(last_10_digits, 'last', self._origin.id)
                # Search for any existing records with the same last 10 digits
                duplicate = self.sudo().search([
                    ('phone_number', 'like', '%' + last_10_digits),
                    ('id', '!=', self._origin.id)
                ])

                if duplicate:
                    # Get the lead owner name (fallback to 'Unknown' if not set)
                    lead_owner_name = duplicate[0].lead_owner.name if duplicate[0].lead_owner else 'Unknown'

                    return {
                        'warning': {
                            'title': _("Duplicate Phone Number"),
                            'message': _(
                                "The phone number %s already exists in the system and is owned by %s."
                            ) % (record.phone_number, lead_owner_name),
                        }
                    }

    admission_fee_paid = fields.Boolean(string="Admission Fee Paid")
    re_allocation_date = fields.Date(string="Re Allocation Date")

    def create_invoice(self):
        return {'type': 'ir.actions.act_window',
                'name': _('Create Invoice'),
                'res_model': 'fee.collection.wizard',
                'target': 'new',
                'view_mode': 'form',
                'view_type': 'form',
                'context': {'default_collection_id': self.student_id.id, 'default_fee_type': 'Other Fee', 'default_other_fee': 'Admission Fee',
                            'default_wallet_amount': self.student_id.wallet_balance, 'default_fee_plan': self.student_id.fee_type, 'default_amount_inc_tax': self.batch_id.admission_fee}, }

    @api.constrains('phone_number')
    def _check_duplicate_phone_number(self):
        for record in self:
            if record.phone_number:
                last_10_digits = record.phone_number[-10:]

                duplicate = self.sudo().search([
                    ('phone_number', 'like', '%' + last_10_digits),
                    ('id', '!=', record.id)
                ])
                if duplicate:
                    lead_owner_name = duplicate[0].lead_owner.name if duplicate[0].lead_owner else "Unknown"
                    raise ValidationError(
                        _('The phone number %s already exists and is owned by %s. Please use a different number.')
                        % (record.phone_number, lead_owner_name)
                    )

    def act_attempt_to_connect(self):
        # self.current_status = 'not_responding'
        self.state = 'in_progress'

    def act_connected(self):
        print('hi')
        return {'type': 'ir.actions.act_window',
                'name': _('Connect'),
                'res_model': 'connect.form',
                'target': 'new',
                'view_mode': 'form',
                'context': {'default_lead_id': self.id, 'default_task_owner_id': self.lead_owner.user_id.id}, }

    def act_not_connected(self):
        act = self.env['mail.activity'].search([('res_model', '=', 'leads.logic')])
        for i in act:
            print(i.res_model, 'model')
        return {'type': 'ir.actions.act_window',
                'name': _('Connect'),
                'res_model': 'not.connect.form',
                'target': 'new',
                'view_mode': 'form',
                'view_type': 'form',
                'context': {'default_lead_id': self.id, }, }

    @api.onchange('name', 'phone_number', 'call_response', 'leads_source', 'lead_quality', 'admission_status',
                  'lead_owner', 'assign_to', 'course_id', 'batch_id', 'branch_id')
    def _onchange_updated_date(self):
        print('hiii')
        if self.batch_id:
            self.course_id = self.batch_id.course_id.id
            self.branch_id = self.batch_id.branch.id
        if self:
            self.last_update_date = datetime.now()
        if self.lead_quality == 'waiting_for_admission':
            raise ValidationError(
                "⚠️ Please complete the 'Waiting for Admission Payment' form before setting status to 'Waiting for Admission'.")
        if self.lead_quality == 'admission':
            print("is it admission")
            if self.admission_status == 0:
                raise ValidationError(
                    "⚠️ First, you need to transfer to 'Waiting for Admission Payment.' After the admission fee is paid, you can transfer to 'Admission'.")
        if self.lead_quality == 'crash_lead':
            if self.crash_lead == 0:
                raise ValidationError("This lead is about to be transferred to the Crash Team. Are you sure you want to proceed with this action? Please enable 'Crash Lead' before proceeding with this action ")

    def act_lost_lead(self):
        return {'type': 'ir.actions.act_window',
                'name': _('Lost'),
                'res_model': 'lost.lead.form',
                'target': 'new',
                'view_mode': 'form',
                'view_type': 'form',
                'context': {'default_lead_id': self.id, }, }

    def act_convert(self):
        print('hi')
        if self.batch_id and self.branch_id and self.course_id:
            return {'type': 'ir.actions.act_window',
                    'name': _('Deal'),
                    'res_model': 'convert.lead',
                    'target': 'new',
                    'view_mode': 'form',
                    'view_type': 'form',
                    'context': {'default_lead_id': self.id, 'default_lead_owner_id': self.lead_owner.user_id.id, }, }
        else:
            raise UserError(_('Please ensure that Batch, Branch, and Course are selected before proceeding.'))

    def act_admission(self):
        print()
        if self.batch_id.name != 'Nil':
            if self.batch_id and self.branch_id and self.course_id:
                return {'type': 'ir.actions.act_window',
                        'name': _('Admission'),
                        'res_model': 'qualified.lead.form',
                        'target': 'new',
                        'view_mode': 'form',
                        'view_type': 'form',
                        'context': {'default_lead_id': self.id,
                                    'default_batch_id': self.batch_id.id,
                                    'default_course_id': self.course_id.id,
                                    'default_branch_id': self.branch_id.id,
                                    'default_mobile': self.phone_number,
                                    'default_email': self.email_address}, }
            else:
                raise UserError(_('Please ensure that Batch, Branch, and Course are selected before proceeding.'))
        else:
            raise UserError(_('Nil batch is not allowed. Please select a valid batch.'))

    def act_transfer_to_waiting_for_admission(self):
        self.lead_quality = 'waiting_for_admission'

    def act_return_to_new_lead(self):
        self.state = 'new'

    # @api.model
    # def allocate_leads(self, lead_ids):
    #     # Fetch tele-callers who can handle leads
    #     tele_caller_group = self.env.ref('custom_leads.group_lead_tele_callers')
    #     if tele_caller_group:  # Update the module name
    #         tele_callers = self.env['res.users'].search([('groups_id', 'in', [tele_caller_group.id])])
    #     else:
    #         return []
    #     # Fetch lead users for inbound source
    #     lead_user_group = self.env.ref('custom_leads.group_lead_users')  # Update the module name
    #     if lead_user_group:
    #         lead_users = self.env['res.users'].search([('groups_id', 'in', [lead_user_group.id])])
    #     else:
    #         return []
    #     lead_objects = self.browse(lead_ids)
    #     if not tele_callers and not lead_users:
    #         raise ValueError("No users available to allocate leads.")
    #
    #     # Logic for outbound and inbound leads
    #     for lead in lead_objects:
    #         if lead.leads_source.source == 'outbound_source':
    #             print('out')
    #             # Assign to tele-callers in FIFO order
    #             tele_caller_list = tele_callers.sorted(key=lambda tc: tc.create_date)
    #             tele_caller_count = len(tele_caller_list)
    #             tele_caller_id = tele_caller_list[lead.id % tele_caller_count].id
    #             lead.write({'tele_caller_id': tele_caller_id})
    #
    #         elif lead.leads_source.source == 'inbound_source':
    #             print('in')
    #             # Assign to lead users in FIFO order
    #             lead_user_list = lead_users.sorted(key=lambda user: user.create_date)
    #             lead_user_count = len(lead_user_list)
    #             lead_user_id = lead_user_list[lead.id % lead_user_count].id
    #             print(lead_user_id, 'user_id')
    #             user = self.env['res.users'].search([('id', '=', lead_user_id)])
    #             lead.write({'lead_owner': user.employee_id.id})

    def act_re_allocation_leads(self):
        selected_ids = self.env.context.get('active_ids', [])
        print('re assignment', selected_ids)
        return {'type': 'ir.actions.act_window',
                'name': _('Re Allocation'),
                'res_model': 're.allocation.leads',
                'target': 'new',
                'view_mode': 'form',
                'view_type': 'form',
                'context': {
                    'default_leads_ids': [(6, 0, selected_ids)]
                }, }

    @api.model
    def create(self, values):
        if values.get('reference_no', _('New')) == _('New'):
            values['reference_no'] = self.env['ir.sequence'].next_by_code(
                'leads.logic') or _('New')
        # Create the lead
        if 'phone_number' in values:
            values['phone_number'] = values['phone_number'].replace(" ", "")

        lead = super(LeadsForm, self).create(values)

        # Allocate the lead to tele-callers or lead users
        # self.allocate_leads([lead.id])

        # Notify the assigned tele-caller, if any
        if lead.tele_caller_id:
            # Create the notification
            notification_ids = [(0, 0, {
                'res_partner_id': lead.tele_caller_id.partner_id.id,
                'notification_type': 'inbox'
            })]

            # Create the mail message
            self.env['mail.message'].create({
                'message_type': "notification",
                'body': f"Lead '{lead.name}' has been assigned to you.",
                'subject': "Lead Assigned",
                'model': 'leads.logic',
                'res_id': lead.id,
                'partner_ids': [(4, lead.tele_caller_id.partner_id.id)],
                'author_id': self.env.user.partner_id.id,
                'notification_ids': notification_ids,
            })

        return lead

    updated_remarks = fields.Text(string="Updated Remarks")

    truncated_call_response = fields.Char(
        string="Truncated Response", compute="_compute_truncated_response"
    )

    def act_print_invoice(self):
        return self.env.ref('custom_leads.action_report_lead_payment_history_receipt').report_action(self)

    def _compute_truncated_response(self):
        for record in self:
            record.truncated_call_response = (
                (record.call_response[:20] + "...") if record.call_response else ""
            )

    is_team_leader = fields.Boolean(compute="_compute_team_leader")

    @api.depends()
    def _compute_team_leader(self):
        for record in self:
            record.is_team_leader = self.env.user.has_group('custom_leads.group_lead_team_lead')

            # record.admission_date = False

    @api.constrains('updated_remarks', 'lead_quality')
    def _check_updated_remarks(self):
        for record in self:
            if record.lead_quality:
                if record.lead_quality == 'bad_lead':
                    if not record.updated_remarks:
                        raise ValidationError("Updated Remarks is required when Lead Quality is 'Bad Lead'.")
                    if len(record.updated_remarks) < 140:
                        raise ValidationError("Updated Remarks must be at least 140 characters long.")

    def action_bulk_lead_allocation_tele_callers(self):
        active_ids = self.env.context.get('active_ids', [])
        print(active_ids, 'current rec')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Allocation',
            'res_model': 'allocation.tele_callers.wizard',
            'view_mode': 'form',
            'view_type': 'form',
            'target': 'new',
            'context': {'parent_obj': active_ids}

        }


class CallResponses(models.Model):
    _name = "call.responses"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Text(string="Call Responses")
