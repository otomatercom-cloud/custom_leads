from email.policy import default
from tokenize import String

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import date, datetime, timedelta
import logging
import requests
from urllib.parse import quote
_logger = logging.getLogger(__name__)


class LeadAssignmentHistory(models.Model):
    _name = 'lead.assignment.history'
    _description = 'Lead Assignment History'
    _order = 'create_date desc'

    lead_id = fields.Many2one('leads.logic', string='Lead', ondelete='cascade')
    owner_id = fields.Many2one('hr.employee', string='Assigned Officer')
    assigned_date = fields.Datetime(string='Assigned Date', default=fields.Datetime.now)
    assigned_by = fields.Many2one('res.users', string='Assigned By', default=lambda self: self.env.user)


class LeadQualityHistory(models.Model):
    _name = 'lead.quality.history'
    _description = 'Lead Quality History'
    _order = 'create_date desc'

    lead_id = fields.Many2one('leads.logic', string='Lead', ondelete='cascade')
    lead_quality = fields.Selection(
        [('new', '🆕  New'),('first_attempt','🎯 First Attempt'), ('waiting_for_admission', '⏳  Waiting for Admission'), ('admission', '🎓  Admission'),
         ('hot', '🔥  Hot'),
         ('warm', '🌞  Warm'), ('cold', '❄️  Cold'),
         ('bad_lead', '⚠️  Language Barrier'), ('crash_lead', '💥  Crash Lead'), ('not_responding', '🔕  Ringing Not Responding'),
         ('call_later', '📞  Call Later'),('may_be_later','🔔 May Be Later'),
         ('follow_up', '⏰  Follow Up'),('not_reachable', '🚫  Not Reachable'),('already_joined','✅ Already Joined'),('joined_other_institute','🏫 Joined Other Institute'),('wrong_number','📵 Wrong number'),('not_enquiry', '🛑 Not Enquiry'),('not_interested', '❌ Not Interested')],
        string='Lead Quality')
    user_id = fields.Many2one('res.users', string='Changed By', default=lambda self: self.env.user)
    change_date = fields.Datetime(string='Change Date', default=fields.Datetime.now)


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
    is_editable = fields.Boolean(string="Editable", default=False)

    masked_phone = fields.Char(
        string="Phone",
        compute="_compute_masked_phone"
    )

    show_phone = fields.Boolean(default=False)

    @api.depends('phone_number', 'show_phone')
    def _compute_masked_phone(self):
        for rec in self:
            if rec.show_phone:
                rec.masked_phone = rec.phone_number or ''
            else:
                if rec.phone_number and len(rec.phone_number) >= 10:
                    rec.masked_phone = 'XXXXXX' + rec.phone_number[-4:]
                else:
                    rec.masked_phone = 'Hidden'

    def action_toggle_phone(self):
        for rec in self:
            rec.show_phone = not rec.show_phone

    open_count = fields.Integer(string="Open Count", default=0)
    last_opened_on = fields.Datetime(string="Last Opened On")
    last_opened_by = fields.Many2one('res.users', string="Last Opened By")

    open_history_ids = fields.One2many(
        'lead.open.history',
        'lead_id',
        string='Open History'
    )
    # This field holds the red text
    # warm_lead_instruction = fields.Html(
    #     compute="_compute_warm_instruction",
    #     default='<p style="color: red; font-weight: bold;">what are the things do in warm lead</p>'
    # )
    #
    # @api.depends('lead_quality')
    # def _compute_warm_instruction(self):
    #     for record in self:
    #         # We set the value regardless, the XML will handle the hiding/showing
    #         record.warm_lead_instruction = '<p style="color: red; font-weight: bold;">what are the things do in warm lead gjhgasgdja asdgasgdsaj agjgda jgaj</p>'

    # campaign_tracking_ids = fields.One2many(
    #     'lead.campaign.tracking',
    #     'lead_id',
    #     string='Course Campaigns'
    # )
    #
    # progress_html = fields.Html(
    #     compute='_compute_campaign_progress_html',
    #     sanitize=False
    # )
    #
    # @api.model_create_multi
    # def create(self, vals_list):
    #     leads = super().create(vals_list)
    #
    #     for lead in leads:
    #
    #         if not lead.course_id:
    #             continue
    #
    #         templates = self.env['lead.campaign.template'].search([
    #             ('campaign_course_id', '=', lead.course_id.id),
    #             ('active', '=', True)
    #         ])
    #
    #         tracking_vals = []
    #
    #         for template in templates:
    #             tracking_vals.append({
    #                 'lead_id': lead.id,
    #                 'template_id': template.id,
    #             })
    #
    #         if tracking_vals:
    #             self.env['lead.campaign.tracking'].create(tracking_vals)
    #
    #     return leads

    def open_edit_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Enable Editing',
            'res_model': 'lead.unlock.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    def write(self, vals):
        res = super(LeadsForm, self).write(vals)
        # AFTER saving → lock the form again
        if 'is_editable' not in vals:  # only lock if user is not explicitly toggling it
            self.is_editable = False
        return res

    # touch_ids = fields.One2many('leads.own.touch.points', 'touch_id', string='Touch Points')

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, order=None):
        args = args or []
        domain = []
        if name:
            domain = ['|', ('name', operator, name), ('phone_number', operator, name)]
        return self._search(domain + args, limit=limit, order=order)

    lead_quality = fields.Selection(
        [('new', '🆕  New'),('first_attempt','🎯 First Attempt'), ('waiting_for_admission', '⏳  Waiting for Admission'), ('admission', '🎓  Admission'),
         ('hot', '🔥  Hot'),
         ('warm', '🌞  Warm'), ('cold', '❄️  Cold'),
         ('bad_lead', '⚠️  Language Barrier'), ('crash_lead', '💥  Crash Lead'), ('not_responding', '🔕  Ringing Not Responding'),
         ('call_later', '📞  Call Later'),('may_be_later','🔔 May Be Later'),
         ('follow_up', '⏰  Follow Up'),('not_reachable', '🚫  Not Reachable'),('already_joined','✅ Already Joined'),('joined_other_institute','🏫 Joined Other Institute'),('wrong_number','📵 Wrong number'),('not_enquiry', '🛑 Not Enquiry'),('not_interested', '❌ Not Interested')],
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
         ('2026-2027', '2026-2027')], string="Academic Year of Course attended",default='2025-2026')
    course_type = fields.Selection(
        [('indian', 'Indian'), ('international', 'International'), ('crash', 'Crash'), ('repeaters', 'Repeaters'),
         ('nil', 'Nil')],
        string='Course Type')

    # Touch Point Fields
    first_call = fields.Boolean(copy=False)
    first_call_dt = fields.Datetime(string="First Attempt Date", copy=False)

    whatsapp_intro = fields.Boolean(copy=False)
    whatsapp_date = fields.Datetime(string="Whatsapp Intro Date", copy=False)

    testimonials = fields.Boolean(copy=False)
    testimonials_dt = fields.Datetime(string="Testimonials Date", copy=False)

    results_highlights = fields.Boolean(copy=False)
    results_highlights_dt = fields.Datetime(string="Results Date", copy=False)

    second_follow_up = fields.Boolean(copy=False)
    second_follow_up_dt = fields.Datetime(string="Second Follow Up Date", copy=False)

    sent_webinar = fields.Boolean(copy=False)
    sent_webinar_dt = fields.Datetime(string="Webinar Date", copy=False)

    third_call = fields.Boolean(copy=False)
    third_call_dt = fields.Datetime(string="Third Call Date", copy=False)

    touches_complete = fields.Boolean(copy=False)
    touches_complete_dt = fields.Datetime(string="Touches Complete Date", copy=False)
    
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
    reassign_date = fields.Datetime(string='Reassign Date', readonly=True)
    assignment_history_ids = fields.One2many('lead.assignment.history', 'lead_id', string='Assignment History', readonly=True)
    quality_history_ids = fields.One2many('lead.quality.history', 'lead_id', string='Lead Quality History', readonly=True)
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
    stream = fields.Char(string="Stream")
    digital_head_id = fields.Many2one('res.users', string='Digital Head')
    response_ids = fields.One2many('lead.response', 'lead_id', string="Responses")
    course_inter = fields.Many2many('course.interested', string="Course Interested In")
    call_log_ids = fields.One2many("lead.call.log", "lead_id", string="Call History")
    followup_ids = fields.One2many('lead.followup', 'lead_id', string="Follow Ups")

    is_ciap_selected = fields.Boolean(compute="_compute_is_ciap_selected")
    ciap_media_sent = fields.Boolean(string="Course Launching Videos", default=False)
    ciap_media_sent_date = fields.Datetime(string="Course Launching Videos On")
    ciap_media_sent_by = fields.Many2one('res.users', string="Course Launching Videos By")

    ciap_assessment_test_sent = fields.Boolean("Assessment Test Sent")
    ciap_assessment_test_sent_date = fields.Datetime(readonly=True)

    # Update Stage 7 completion
    @api.depends(
        'ciap_career_counselling_sent',
        'ciap_assessment_test_sent',
    )
    def _compute_stage7_completed(self):
        for rec in self:
            rec.stage7_completed = bool(
                rec.ciap_career_counselling_sent
                and rec.ciap_assessment_test_sent
            )

    stage1_completed = fields.Boolean(
        string="Stage 1 Completed",
        compute="_compute_stage1_completed",
        store=True
    )

    @api.depends('ciap_media_sent', 'webinar_invite_sent')
    def _compute_stage1_completed(self):
        for rec in self:
            rec.stage1_completed = bool(
                rec.ciap_media_sent and rec.webinar_invite_sent
            )

    @api.depends('course_inter')
    def _compute_is_ciap_selected(self):
        for rec in self:
            rec.is_ciap_selected = any(course.name == 'CIAP' for course in rec.course_inter)

    def action_send_course_launch_media(self):
        self.ensure_one()

        if self.ciap_media_sent:
            return

        phone = self.phone_number  # replace with your actual phone field

        if not phone:
            return

        message = (
            f"Hi {self.name or ''},\n\n"
            "Please check our latest course launch photos and videos:\n"
            "https://yourdomain.com/course-launch-media"
        )

        whatsapp_url = "https://wa.me/%s?text=%s" % (
            phone.replace('+', '').replace(' ', ''),
            quote(message)
        )

        # Track sent status
        self.write({
            'ciap_media_sent': True,
            'ciap_media_sent_date': fields.Datetime.now(),
            'ciap_media_sent_by': self.env.user.id,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }

    webinar_invite_sent = fields.Boolean(string="Webinar Invite Sent", default=False)

    def action_open_webinar_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send Webinar Invite',
            'res_model': 'webinar.invite.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_lead_id': self.id,
            }
        }

    # Ajesh Add

    # Prgress HML

    progress_html = fields.Html(
        compute='_compute_progress_html',
        sanitize=False,
    )

    stage1_completed = fields.Boolean(
        compute='_compute_stage1_completed',
        store=True,
    )

    # @api.depends('first_call', 'webinar_invite_sent', 'ciap_media_sent')
    # def _compute_stage1_completed(self):
    #     for rec in self:
    #         rec.stage1_completed = bool(
    #             rec.first_call
    #             and rec.webinar_invite_sent
    #             and rec.ciap_media_sent
    #         )
    #
    # @api.depends(
    #     'first_call',
    #     'webinar_invite_sent',
    #     'ciap_media_sent',
    #     'stage1_completed'
    # )
    # def _compute_progress_html(self):
    #     for rec in self:
    #         stage1_done = rec.stage1_completed
    #
    #         stage1_class = 'progress-circle done' if stage1_done else 'progress-circle active'
    #         stage2_class = 'progress-circle active' if stage1_done else 'progress-circle'
    #         line1_class = 'progress-line done' if stage1_done else 'progress-line'
    #
    #         rec.progress_html = f"""
    #                <div class="crm-progress-wrapper">
    #
    #                    <div class="crm-progress-row">
    #
    #                        <div class="progress-step">
    #                            <div class="{stage1_class}">
    #                                {'✓' if stage1_done else '📞'}
    #                            </div>
    #                            <div class="progress-label">Stage 1</div>
    #                            <small>Call + Webinar + Media</small>
    #                        </div>
    #
    #                        <div class="{line1_class}"></div>
    #
    #                        <div class="progress-step">
    #                            <div class="{stage2_class}">⚙️</div>
    #                            <div class="progress-label">Stage 2</div>
    #                        </div>
    #
    #                        <div class="progress-line"></div>
    #
    #                        <div class="progress-step">
    #                            <div class="progress-circle">🚀</div>
    #                            <div class="progress-label">Stage 3</div>
    #                        </div>
    #
    #                    </div>
    #
    #                    <div class="stage-checklist">
    #                        <div>{'✅' if rec.first_call else '⬜'} First Call</div>
    #                        <div>{'✅' if rec.webinar_invite_sent else '⬜'} Webinar Invite Sent</div>
    #                        <div>{'✅' if rec.ciap_media_sent else '⬜'} CIAP Media Sent</div>
    #                    </div>
    #
    #                </div>
    #                """

    @api.depends(
        'stage1_completed',
        'stage2_completed',
        'stage3_completed',
        'stage4_completed',
        'stage5_completed',
        'stage6_completed',
        'stage7_completed',

        'first_call',
        'webinar_invite_sent',
        'ciap_media_sent',

        'ciap_roadmap_sent',
        'ciap_brochure_sent',
        'detailed_ciap_video_sent',
        'ciap_demo_class_sent',

        'ciap_faculty_pool_sent',
        'ciap_value_added_videos_sent',

        'ciap_testimonials_sent',
        'ciap_winners_meet_sent',

        'ciap_placement_media_sent',

        'ciap_starter_kit_sent',
        'ciap_key_benefits_reshared',

        'ciap_career_counselling_sent',
    )
    def _compute_progress_html(self):
        for rec in self:

            stages = [
                ('Stage 1', '📞', rec.stage1_completed),
                ('Stage 2', '📚', rec.stage2_completed),
                ('Stage 3', '🎓', rec.stage3_completed),
                ('Stage 4', '🏆', rec.stage4_completed),
                ('Stage 5', '💼', rec.stage5_completed),
                ('Stage 6', '🎁', rec.stage6_completed),
                ('Stage 7', '🤝', rec.stage7_completed),
            ]

            html = """
            <div class="crm-progress-wrapper">
                <div class="crm-progress-row">
            """

            for i, (label, icon, done) in enumerate(stages):

                if done:
                    circle_class = "progress-circle done"
                    display_icon = "✓"
                elif i == 0 or stages[i - 1][2]:
                    circle_class = "progress-circle active"
                    display_icon = icon
                else:
                    circle_class = "progress-circle"
                    display_icon = icon

                html += f"""
                    <div class="progress-step">
                        <div class="{circle_class}">
                            {display_icon}
                        </div>
                        <div class="progress-label">{label}</div>
                    </div>
                """

                if i < len(stages) - 1:
                    line_class = "progress-line done" if done else "progress-line"
                    html += f'<div class="{line_class}"></div>'

            html += "</div>"

            html += f"""
                <div class="stage-checklist">

                    <div class="stage-column">
                        <div class="stage-title">Stage 1</div>
                        <div>{'✅' if rec.first_call else '⬜'} First Call</div>
                        <div>{'✅' if rec.webinar_invite_sent else '⬜'} Webinar Invite Sent</div>
                        <div>{'✅' if rec.ciap_media_sent else '⬜'} CIAP Media Sent</div>
                    </div>

                    <div class="stage-column">
                        <div class="stage-title">Stage 2</div>
                        <div>{'✅' if rec.ciap_roadmap_sent else '⬜'} Career Roadmap</div>
                        <div>{'✅' if rec.ciap_brochure_sent else '⬜'} Course Brochure</div>
                        <div>{'✅' if rec.detailed_ciap_video_sent else '⬜'} Detailed Course Videos</div>
                        <div>{'✅' if rec.ciap_demo_class_sent else '⬜'} Free Demo Class</div>
                        <div>{'✅' if rec.ciap_assessment_test_sent else '⬜'} Assessment Test (Only for confused students)</div>
                    </div>

                    <div class="stage-column">
                        <div class="stage-title">Stage 3</div>
                        <div>{'✅' if rec.ciap_faculty_pool_sent else '⬜'} Faculty Pool</div>
                        <div>{'✅' if rec.ciap_value_added_videos_sent else '⬜'} Value Added Videos</div>
                    </div>

                </div>

                <div class="stage-checklist" style="margin-top:10px;">

                    <div class="stage-column">
                        <div class="stage-title">Stage 4</div>
                        <div>{'✅' if rec.ciap_testimonials_sent else '⬜'} Student Testimonials</div>
                        <div>{'✅' if rec.ciap_winners_meet_sent else '⬜'} Winners Meet Videos</div>
                    </div>

                    <div class="stage-column">
                        <div class="stage-title">Stage 5</div>
                        <div>{'✅' if rec.ciap_placement_media_sent else '⬜'} Placement Photos / Videos</div>
                    </div>

                    <div class="stage-column">
                        <div class="stage-title">Stage 6</div>
                        <div>{'✅' if rec.ciap_starter_kit_sent else '⬜'} Starter Kit</div>
                        <div>{'✅' if rec.ciap_key_benefits_reshared else '⬜'} Re-share Key Benefits</div>
                    </div>

                    <div class="stage-column">
                        <div class="stage-title">Stage 7</div>
                        <div>{'✅' if rec.ciap_career_counselling_sent else '⬜'} Career Counselling</div>
                    </div>

                </div>
            </div>
            """

            rec.progress_html = html


    # @api.depends(
    #     'first_call',
    #     'webinar_invite_sent',
    #     'ciap_media_sent',
    #     'stage1_completed',
    #     'ciap_roadmap_sent',
    #     'ciap_brochure_sent',
    #     'detailed_ciap_video_sent',
    #     'stage2_completed',
    # )
    # def _compute_progress_html(self):
    #     for rec in self:
    #         stage1_done = rec.stage1_completed
    #         stage2_done = rec.stage2_completed
    #
    #         stage1_class = 'progress-circle done' if stage1_done else 'progress-circle active'
    #         line1_class = 'progress-line done' if stage1_done else 'progress-line'
    #
    #         if stage2_done:
    #             stage2_class = 'progress-circle done'
    #             line2_class = 'progress-line done'
    #             stage3_class = 'progress-circle active'
    #         elif stage1_done:
    #             stage2_class = 'progress-circle active'
    #             line2_class = 'progress-line'
    #             stage3_class = 'progress-circle'
    #         else:
    #             stage2_class = 'progress-circle'
    #             line2_class = 'progress-line'
    #             stage3_class = 'progress-circle'
    #
    #         rec.progress_html = f"""
    #         <div class="crm-progress-wrapper">
    #
    #             <div class="crm-progress-row">
    #
    #                 <div class="progress-step">
    #                     <div class="{stage1_class}">
    #                         {'✓' if stage1_done else '📞'}
    #                     </div>
    #                     <div class="progress-label">Stage 1</div>
    #                     <small>Call + Webinar + Media</small>
    #                 </div>
    #
    #                 <div class="{line1_class}"></div>
    #
    #                 <div class="progress-step">
    #                     <div class="{stage2_class}">
    #                         {'✓' if stage2_done else '📚'}
    #                     </div>
    #                     <div class="progress-label">Stage 2</div>
    #                     <small>Roadmap + Brochure + Videos</small>
    #                 </div>
    #
    #                 <div class="{line2_class}"></div>
    #
    #                 <div class="progress-step">
    #                     <div class="{stage3_class}">🚀</div>
    #                     <div class="progress-label">Stage 3</div>
    #                 </div>
    #
    #             </div>
    #
    #             <div class="stage-checklist d-flex justify-content-between">
    #
    #                 <div style="width:48%;">
    #                     <div style="font-weight:600; margin-bottom:8px;">Stage 1</div>
    #                     <div>{'✅' if rec.first_call else '⬜'} First Call</div>
    #                     <div>{'✅' if rec.webinar_invite_sent else '⬜'} Webinar Invite Sent</div>
    #                     <div>{'✅' if rec.ciap_media_sent else '⬜'} CIAP Media Sent</div>
    #                 </div>
    #
    #                 <div style="width:48%;">
    #                     <div style="font-weight:600; margin-bottom:8px;">Stage 2</div>
    #                     <div>{'✅' if rec.ciap_roadmap_sent else '⬜'} Career Roadmap</div>
    #                     <div>{'✅' if rec.ciap_brochure_sent else '⬜'} Course Brochure</div>
    #                     <div>{'✅' if rec.detailed_ciap_video_sent else '⬜'} Detailed Course Videos</div>
    #                     <div>{'✅' if rec.ciap_demo_class_sent else '⬜'} Free Demo Class</div>
    #                 </div>
    #
    #             </div>
    #         </div>
    #         """

                # <div class="stage-checklist">
                #     <div style="font-weight:600; margin-bottom:6px;">Stage 1</div>
                #     <div>{'✅' if rec.first_call else '⬜'} First Call</div>
                #     <div>{'✅' if rec.webinar_invite_sent else '⬜'} Webinar Invite Sent</div>
                #     <div>{'✅' if rec.ciap_media_sent else '⬜'} CIAP Media Sent</div>
                # 
                #     <div style="margin-top:12px; font-weight:600; margin-bottom:6px;">Stage 2</div>
                #     <div>{'✅' if rec.ciap_roadmap_sent else '⬜'} Career Roadmap</div>
                #     <div>{'✅' if rec.ciap_brochure_sent else '⬜'} Course Brochure</div>
                #     <div>{'✅' if rec.detailed_ciap_video_sent else '⬜'} Detailed Course Videos</div>
                # </div>




                #Progress tml Completed

    #         Stage 2

    ciap_roadmap_sent = fields.Boolean("Career Roadmap Sent")
    ciap_roadmap_sent_date = fields.Datetime(readonly=True)

    ciap_brochure_sent = fields.Boolean("Course Brochure Sent")
    ciap_brochure_sent_date = fields.Datetime(readonly=True)

    detailed_ciap_video_sent = fields.Boolean("Detailed Course Video Sent")
    detailed_ciap_video_sent_date = fields.Datetime(readonly=True)

    ciap_demo_class_sent = fields.Boolean("CIAP Free Demo Class Sent")
    ciap_demo_class_sent_date = fields.Datetime(readonly=True)

    stage2_completed = fields.Boolean(
        compute='_compute_stage2_completed',
        store=True,
    )

    def action_send_ciap_roadmap(self):
        self.ensure_one()

        if self.ciap_roadmap_sent:
            return

        phone = self.phone_number

        if not phone:
            return

        message = (
            f"Hi {self.name or ''},\n\n"
            "Here is your Career Roadmap for the CIAP course.\n"
            "It explains the career path, salary growth and future opportunities.\n\n"
            "https://yourdomain.com/files/ciap_career_roadmap.pdf"
        )

        whatsapp_url = "https://wa.me/%s?text=%s" % (
            phone.replace('+', '').replace(' ', ''),
            quote(message)
        )

        self.write({
            'ciap_roadmap_sent': True,
            'ciap_roadmap_sent_date': fields.Datetime.now(),
        })

        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }
    def action_send_ciap_brochure(self):
        self.ensure_one()

        if self.ciap_brochure_sent:
            return

        phone = (self.phone_number or '').replace('+', '').replace(' ', '')

        if not phone:
            return

        message = (
            f"Hi {self.name or ''},\n\n"
            "Please find the CIAP Course Brochure below.\n\n"
            "https://yourdomain.com/files/ciap_course_brochure.pdf"
        )

        whatsapp_url = "https://wa.me/%s?text=%s" % (
            phone,
            quote(message)
        )

        self.write({
            'ciap_brochure_sent': True,
            'ciap_brochure_sent_date': fields.Datetime.now(),
        })

        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }

    def action_send_detailed_ciap_video(self):
        self.ensure_one()

        if self.detailed_ciap_video_sent:
            return

        phone = (self.phone_number or '').replace('+', '').replace(' ', '')

        if not phone:
            return

        message = (
            f"Hi {self.name or ''},\n\n"
            "Please watch these detailed CIAP course videos.\n\n"
            "https://yourdomain.com/files/ciap_detailed_video"
        )

        whatsapp_url = "https://wa.me/%s?text=%s" % (
            phone,
            quote(message)
        )

        self.write({
            'detailed_ciap_video_sent': True,
            'detailed_ciap_video_sent_date': fields.Datetime.now(),
        })

        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }

    def action_send_ciap_demo_class(self):
        self.ensure_one()

        if self.ciap_demo_class_sent:
            return

        phone = self.phone_number

        if not phone:
            return

        message = (
            f"Hi {self.name or ''},\n\n"
            "You can attend our FREE CIAP Demo Class to understand the course, faculty and opportunities.\n\n"
            "Demo Class Link:\n"
            "https://yourdomain.com/ciap-demo-class"
        )

        whatsapp_url = "https://wa.me/%s?text=%s" % (
            phone.replace('+', '').replace(' ', ''),
            quote(message)
        )

        self.write({
            'ciap_demo_class_sent': True,
            'ciap_demo_class_sent_date': fields.Datetime.now(),
        })

        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }

    def action_send_ciap_assessment_test(self):
        self.ensure_one()

        if self.ciap_assessment_test_sent:
            return

        phone = self.phone_number

        if not phone:
            return

        message = (
            f"Hi {self.name or ''},\n\n"
            "Please complete your FREE CIAP Assessment Test to evaluate your current level and understand the right path for your career.\n\n"
            "Assessment Test Link:\n"
            "https://yourdomain.com/ciap-assessment-test"
        )

        whatsapp_url = "https://wa.me/%s?text=%s" % (
            phone.replace('+', '').replace(' ', ''),
            quote(message)
        )

        self.write({
            'ciap_assessment_test_sent': True,
            'ciap_assessment_test_sent_date': fields.Datetime.now(),
        })

        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }


    @api.depends(
        'ciap_roadmap_sent',
        'ciap_brochure_sent',
        'detailed_ciap_video_sent',
        'ciap_demo_class_sent'
    )
    def _compute_stage2_completed(self):
        for rec in self:
            rec.stage2_completed = bool(
                rec.ciap_roadmap_sent
                and rec.ciap_brochure_sent
                and rec.detailed_ciap_video_sent
                and rec.ciap_demo_class_sent
            )

    #         Button CIAP

    # -------------------------
    # STAGE 3
    # -------------------------
    ciap_faculty_pool_sent = fields.Boolean("CIAP Faculty Pool Sent")
    ciap_faculty_pool_sent_date = fields.Datetime(readonly=True)

    ciap_value_added_videos_sent = fields.Boolean("CIAP Value Added Programs Videos Sent")
    ciap_value_added_videos_sent_date = fields.Datetime(readonly=True)

    stage3_completed = fields.Boolean(
        compute='_compute_stage3_completed',
        store=True,
    )

    @api.depends(
        'ciap_faculty_pool_sent',
        'ciap_value_added_videos_sent'
    )
    def _compute_stage3_completed(self):
        for rec in self:
            rec.stage3_completed = bool(
                rec.ciap_faculty_pool_sent and
                rec.ciap_value_added_videos_sent
            )

    # -------------------------
    # STAGE 4
    # -------------------------
    ciap_testimonials_sent = fields.Boolean("CIAP Student Testimonials Sent")
    ciap_testimonials_sent_date = fields.Datetime(readonly=True)

    ciap_winners_meet_sent = fields.Boolean("CIAP Winners Meet Videos Sent")
    ciap_winners_meet_sent_date = fields.Datetime(readonly=True)

    stage4_completed = fields.Boolean(
        compute='_compute_stage4_completed',
        store=True,
    )

    @api.depends(
        'ciap_testimonials_sent',
        'ciap_winners_meet_sent'
    )
    def _compute_stage4_completed(self):
        for rec in self:
            rec.stage4_completed = bool(
                rec.ciap_testimonials_sent and
                rec.ciap_winners_meet_sent
            )

    # -------------------------
    # STAGE 5
    # -------------------------
    ciap_placement_media_sent = fields.Boolean("CIAP Placement Photos/Videos Sent")
    ciap_placement_media_sent_date = fields.Datetime(readonly=True)

    stage5_completed = fields.Boolean(
        compute='_compute_stage5_completed',
        store=True,
    )

    @api.depends('ciap_placement_media_sent')
    def _compute_stage5_completed(self):
        for rec in self:
            rec.stage5_completed = rec.ciap_placement_media_sent

    # -------------------------
    # STAGE 6
    # -------------------------
    ciap_starter_kit_sent = fields.Boolean("CIAP Starter Kit Sent")
    ciap_starter_kit_sent_date = fields.Datetime(readonly=True)

    ciap_key_benefits_reshared = fields.Boolean("CIAP Key Benefits Re-shared")
    ciap_key_benefits_reshared_date = fields.Datetime(readonly=True)

    stage6_completed = fields.Boolean(
        compute='_compute_stage6_completed',
        store=True,
    )

    @api.depends(
        'ciap_starter_kit_sent',
        'ciap_key_benefits_reshared'
    )
    def _compute_stage6_completed(self):
        for rec in self:
            rec.stage6_completed = bool(
                rec.ciap_starter_kit_sent and
                rec.ciap_key_benefits_reshared
            )

    # -------------------------
    # STAGE 7
    # -------------------------
    ciap_career_counselling_sent = fields.Boolean("CIAP Free Career Counselling Sent")
    ciap_career_counselling_sent_date = fields.Datetime(readonly=True)

    stage7_completed = fields.Boolean(
        compute='_compute_stage7_completed',
        store=True,
    )

    @api.depends('ciap_career_counselling_sent')
    def _compute_stage7_completed(self):
        for rec in self:
            rec.stage7_completed = rec.ciap_career_counselling_sent


            #Button

    def _send_whatsapp_link(self, boolean_field, date_field, message):
        self.ensure_one()

        phone = (self.phone_number or '').replace('+', '').replace(' ', '')

        if not phone:
            return

        if getattr(self, boolean_field):
            return

        whatsapp_url = "https://wa.me/%s?text=%s" % (
            phone,
            quote(message)
        )

        self.write({
            boolean_field: True,
            date_field: fields.Datetime.now(),
        })

        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }

    # Stage 2

    def action_send_ciap_roadmap(self):
        return self._send_whatsapp_link(
            'ciap_roadmap_sent',
            'ciap_roadmap_sent_date',
            f"Hi {self.name or ''},\n\n"
            "Here is your CIAP Career Roadmap:\n"
            "https://yourdomain.com/files/ciap_career_roadmap.pdf"
        )

    def action_send_ciap_brochure(self):
        return self._send_whatsapp_link(
            'ciap_brochure_sent',
            'ciap_brochure_sent_date',
            f"Hi {self.name or ''},\n\n"
            "Please find the CIAP Course Brochure:\n"
            "https://yourdomain.com/files/ciap_course_brochure.pdf"
        )

    def action_send_detailed_ciap_video(self):
        return self._send_whatsapp_link(
            'detailed_ciap_video_sent',
            'detailed_ciap_video_sent_date',
            f"Hi {self.name or ''},\n\n"
            "Please watch the CIAP Detailed Course Videos:\n"
            "https://yourdomain.com/files/ciap_detailed_course_videos"
        )

    def action_send_ciap_demo_class(self):
        return self._send_whatsapp_link(
            'ciap_demo_class_sent',
            'ciap_demo_class_sent_date',
            f"Hi {self.name or ''},\n\n"
            "Join our FREE CIAP Demo Class:\n"
            "https://yourdomain.com/ciap-demo-class"
        )

    # Stage 3

    def action_send_ciap_faculty_pool(self):
        return self._send_whatsapp_link(
            'ciap_faculty_pool_sent',
            'ciap_faculty_pool_sent_date',
            f"Hi {self.name or ''},\n\n"
            "Meet our CIAP Faculty Pool:\n"
            "https://yourdomain.com/ciap-faculty-pool"
        )

    def action_send_ciap_value_added_videos(self):
        return self._send_whatsapp_link(
            'ciap_value_added_videos_sent',
            'ciap_value_added_videos_sent_date',
            f"Hi {self.name or ''},\n\n"
            "Watch our CIAP Value Added Programs Videos:\n"
            "https://yourdomain.com/ciap-value-added-programs"
        )

    # Stage 4

    def action_send_ciap_testimonials(self):
        return self._send_whatsapp_link(
            'ciap_testimonials_sent',
            'ciap_testimonials_sent_date',
            f"Hi {self.name or ''},\n\n"
            "Please check our CIAP Student Testimonials:\n"
            "https://yourdomain.com/ciap-student-testimonials"
        )

    def action_send_ciap_winners_meet(self):
        return self._send_whatsapp_link(
            'ciap_winners_meet_sent',
            'ciap_winners_meet_sent_date',
            f"Hi {self.name or ''},\n\n"
            "Watch our CIAP Winners Meet Videos:\n"
            "https://yourdomain.com/ciap-winners-meet"
        )

    # Stage 5

    def action_send_ciap_placement_media(self):
        return self._send_whatsapp_link(
            'ciap_placement_media_sent',
            'ciap_placement_media_sent_date',
            f"Hi {self.name or ''},\n\n"
            "Please check our CIAP Placement Photos and Videos:\n"
            "https://yourdomain.com/ciap-placement-media"
        )

    # Stage 6

    def action_send_ciap_starter_kit(self):
        return self._send_whatsapp_link(
            'ciap_starter_kit_sent',
            'ciap_starter_kit_sent_date',
            f"Hi {self.name or ''},\n\n"
            "Here is your CIAP Starter Kit:\n"
            "https://yourdomain.com/ciap-starter-kit"
        )

    def action_reshare_ciap_key_benefits(self):
        return self._send_whatsapp_link(
            'ciap_key_benefits_reshared',
            'ciap_key_benefits_reshared_date',
            f"Hi {self.name or ''},\n\n"
            "Re-sharing the key benefits of the CIAP course:\n"
            "https://yourdomain.com/ciap-benefits"
        )

    # Stage 7

    def action_send_ciap_career_counselling(self):
        return self._send_whatsapp_link(
            'ciap_career_counselling_sent',
            'ciap_career_counselling_sent_date',
            f"Hi {self.name or ''},\n\n"
            "Book your FREE CIAP Career Counselling session:\n"
            "https://yourdomain.com/ciap-career-counselling"
        )


    # Touch Point
    first_call = fields.Boolean(string="First Call", default=False)
    first_call_dt = fields.Datetime(string="First Call Date")
    # first_call_date = fields.Boolean(string="WhatsApp Intro Sent On")
    whatsapp_intro = fields.Boolean(string="WhatsApp Intro Message", default=False)
    whatsapp_date = fields.Datetime(string="WhatsApp Date")
    # whatsapp_intro_date = fields.Boolean(string="WhatsApp Intro Sent On")
    results_highlights = fields.Boolean(string="Results Highlights", default=False)
    results_highlights_dt = fields.Datetime(string="Results Highlights Date")
    second_followup = fields.Boolean(string="Second Follow Up Call", default=False)
    second_followup_dt = fields.Datetime(string="Second Follow Up Date")
    course_wise_webinar = fields.Boolean(string="Course Wise Webinar", default=False)
    course_wise_webinar_dt = fields.Datetime(string="Course Wise Webinar Date")
    webinar_followup = fields.Boolean(string="Webinar Follow Up Call", default=False)
    webinar_followup_dt = fields.Datetime(string="Webinar Follow Up Date")
    testimonials = fields.Boolean(string="Testimonials", default=False)
    testimonials_dt = fields.Datetime(string="Testimonials Date")
    placements = fields.Boolean(string="Placements", default=False)
    placements_dt = fields.Datetime(string="Placements Date")
    logic_events = fields.Boolean(string="Logic Events", default=False)
    logic_events_dt = fields.Datetime(string="Logic Events Date")
    retargeting = fields.Boolean(string="Retargeting", default=False)
    retargeting_dt = fields.Datetime(string="Retargeting Date")
    third_follow_up = fields.Boolean(string="Third Follow Up", default=False)
    third_follow_up_dt = fields.Datetime(string="Third Follow Up Date")
    fourth_follow_up = fields.Boolean(string="Fourth Follow Up", default=False)
    fourth_follow_up_dt = fields.Datetime(string="Fourth Follow Up Date")
    closing = fields.Boolean(string="Closing", default=False)
    closing_dt = fields.Datetime(string="Closing Date")

    # NEW Scheduled touch points
    zoom_schedule_dt = fields.Datetime(string="Zoom Schedule Date", tracking=True)
    walkin_schedule_dt = fields.Datetime(string="Walk-in Schedule Date", tracking=True)

    #webinar
    webinar_invite_sent = fields.Boolean(string="Webinar Invite Sent", default=False)
    webinar_invite_sent_on = fields.Datetime(string="Webinar Invite Sent On")
    webinar_invite_sent_by = fields.Many2one('res.users', string="Webinar Invite Sent By")
    webinar_zoom_link = fields.Char(string="Webinar Zoom Link")

    def action_schedule_meeting(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Schedule Meeting',
            'res_model': 'leads.schedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    def open_lead_popup(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Choose Option',
            'res_model': 'lead.open.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    def action_voxbay_call(self):
        """Trigger Voxbay Click-to-Call API to call the lead's phone number"""
        self.ensure_one()
        if not self.phone_number:
            raise UserError("Lead does not have a phone number.")
            
        company = self.env.company
        uid = company.voxbay_uid
        upin = company.voxbay_upin
        callerid = company.voxbay_callerid
        
        if not all([uid, upin, callerid]):
            raise UserError("Voxbay API credentials (UID, UPIN, Caller ID) are not configured in Company Settings.")
            
        user_no = self.env.user.voxbay_user_no
        if not user_no:
            raise UserError("Your Voxbay Extension Number is not configured. Please set it in your User Profile.")
            
        # Format the numbers (removing spaces, plus signs etc if necessary)
        destination = self.phone_number.strip().replace(" ", "").replace("+", "")
        
        # Voxbay Click-to-Call API URL (FORMAT 1: Extension to Mobile)
        url = f"https://x.voxbay.com/api/click_to_call?id_dept=0&uid={uid}&upin={upin}&user_no={user_no}&destination={destination}&callerid={callerid}&"
        
        try:
            response = requests.get(url, timeout=10)
            api_status = f"HTTP {response.status_code}\nResponse: {response.text}"
            
            # Create the Call Log entry automatically
            call_log = self.env["lead.call.log"].create({
                "lead_id": self.id,
                "user_id": self.env.user.id,
                "call_time": fields.Datetime.now(),
                "remarks": "Initiated via Voxbay"
            })
            
            # Create wizard
            wizard = self.env['voxbay.call.wizard'].create({
                'lead_id': self.id,
                'api_response': api_status,
                'call_log_id': call_log.id
            })
            
            # Open wizard
            return {
                'name': 'Voxbay Call Status',
                'type': 'ir.actions.act_window',
                'res_model': 'voxbay.call.wizard',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'new',
            }

        except Exception as e:
            raise UserError(f"Failed to connect to Voxbay API:\n{str(e)}")

    def action_bonvoice_call(self):
        """Trigger Bonvoice Click-to-Call API to call the lead's phone number"""
        self.ensure_one()
        if not self.phone_number:
            raise UserError("Lead does not have a phone number.")
            
        company = self.env.company
        username = company.bonvoice_username
        password = company.bonvoice_password
        api_url = company.bonvoice_url or 'https://backend.pbx.bonvoice.com/autoDialManagement/autoCallBridging/'
        leg_a_cid = company.bonvoice_leg_a_caller_id
        leg_b_cid = company.bonvoice_leg_b_caller_id
        
        if not all([username, password]):
            raise UserError("Bourn Voice API credentials (Username, Password) are not configured in Company Settings.")
            
        agent_no = self.env.user.bonvoice_agent_number
        if not agent_no:
            raise UserError("Your Bourn Voice Agent Number is not configured. Please set it in your User Profile.")
            
        # Format the numbers
        destination = self.phone_number.strip().replace(" ", "").replace("+", "")
        # If numbers don't start with 91, we might need to prepend it, but according to API docs formats are accepted.
        
        try:
            # 1. Auth Request
            auth_url = "https://backend.pbx.bonvoice.com/usermanagement/external-auth/"
            auth_payload = {
                "username": username,
                "password": password
            }
            auth_response = requests.post(auth_url, json=auth_payload, timeout=10)
            if auth_response.status_code != 200:
                raise UserError(f"Bourn Voice Auth Failed (HTTP {auth_response.status_code}):\n{auth_response.text}")
                
            auth_data = auth_response.json()
            if auth_data.get('status') != '1':
                raise UserError(f"Bourn Voice Auth Error:\n{auth_data.get('message', 'Unknown Error')}")
                
            token = auth_data.get('data', {}).get('token')
            if not token:
                raise UserError("Bourn Voice Auth Error: No token returned.")
                
            # 2. Auto Call Request
            headers = {
                "Authorization": f"Token {token}",
                "Content-Type": "application/json"
            }
            call_payload = {
                "autocallType": "3",
                "destination": agent_no, # Leg A (Agent)
                "ringStrategy": "ringall",
                "legACallerID": leg_a_cid or agent_no,
                "legAChannelID": "1",
                "legADialAttempts": "1",
                "legBDestination": destination, # Leg B (Lead)
                "legBCallerID": leg_b_cid or agent_no,
                "legBChannelID": "1",
                "legBDialAttempts": "1",
                "eventID": f"ld{self.id}{fields.Datetime.now().strftime('%M%S')}"[:16], # Unique ID up to 16 chars
                "callBackParams": {
                    "lead_id": str(self.id)[:50],
                    "agent_id": str(self.env.user.id)[:50]
                }
            }
            
            # Use default URL if the one in company settings still has the old guess
            if 'auto-call' in api_url:
                api_url = 'https://backend.pbx.bonvoice.com/autoDialManagement/autoCallBridging/'
                
            call_response = requests.post(api_url, json=call_payload, headers=headers, timeout=10)
            api_status = f"HTTP {call_response.status_code}\nResponse: {call_response.text}"
            
            # Create the Call Log entry automatically
            call_log = self.env["lead.call.log"].create({
                "lead_id": self.id,
                "user_id": self.env.user.id,
                "call_time": fields.Datetime.now(),
                "remarks": "Initiated via Bourn Voice"
            })
            
            # Create wizard
            wizard = self.env['voxbay.call.wizard'].create({
                'lead_id': self.id,
                'api_response': api_status,
                'call_log_id': call_log.id
            })
            
            # Open wizard
            return {
                'name': 'Bourn Voice Call Status',
                'type': 'ir.actions.act_window',
                'res_model': 'voxbay.call.wizard',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'new',
            }

        except requests.exceptions.RequestException as e:
            raise UserError(f"Failed to connect to Bourn Voice API:\n{str(e)}")
        
    # Duplicate Number

    @api.constrains('phone_number', 'academic_year_of_course_attend')
    def _check_duplicate_phone_number(self):
        for record in self:
            if record.phone_number and record.academic_year_of_course_attend:

                last_10_digits = record.phone_number[-10:]

                duplicate_leads = self.sudo().search([
                    ('id', '!=', record.id),
                    ('academic_year_of_course_attend', '=', record.academic_year_of_course_attend),
                ])

                for lead in duplicate_leads:
                    if lead.phone_number and lead.phone_number[-10:] == last_10_digits:
                        owner = lead.lead_owner.name if lead.lead_owner else "Unknown"

                        raise ValidationError(
                            _("Phone number %s already exists in Academic Year %s (Owner: %s).")
                            % (
                                record.phone_number,
                                record.academic_year_of_course_attend,
                                owner
                            )
                        )


    def action_open_funnel_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Lead Funnel',
            'res_model': 'leads.funnel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    def action_open_confirm_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Open Lead?',
            'res_model': 'leads.confirm.wizard',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'context': {'default_lead_id': self.id},
        }

    # def action_send_whatsapp_intro(self):
    #     """Mark WhatsApp Intro as sent"""
    #     for record in self:
    #         record.whatsapp_intro = True
    #         record.whatsapp_date = fields.Datetime.now()  # records current datetime
    #
    #     # Optional: Add WhatsApp API integration here
    #     return {
    #         'type': 'ir.actions.client',
    #         'tag': 'reload',
    #     }

    def action_send_whatsapp_intro(self):
        """Send WhatsApp Intro Message via AiSensy API campaign"""
        for record in self:
            if not record.phone_number:
                raise UserError("Phone number is missing!")

            # Format phone for WhatsApp (no +, country code needed)
            raw = record.phone_number.strip().replace(" ", "")
            # If your numbers already have country code, adjust accordingly
            # e.g. raw = record.phone_number[-10:] + '91'
            full_phone = raw

            # 1️⃣ Mark WhatsApp intro as sent
            record.whatsapp_intro = True
            record.whatsapp_date = fields.Datetime.now()

            # 2️⃣ AiSensy API endpoint
            url = "https://backend.aisensy.com/campaign/t1/api/v2"

            payload = {
                "apiKey": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZDQyYWJkNDM0ZTE5MTUyNTdkMDc2YSIsIm5hbWUiOiJMb2dpYyBTY2hvb2wgb2YgTWFuYWdlbWVudCA4ODkxIiwiYXBwTmFtZSI6IkFpU2Vuc3kiLCJjbGllbnRJZCI6IjY1ZDQyYWJkNDM0ZTE5MTUyNTdkMDc2NSIsImFjdGl2ZVBsYW4iOiJQUk9fTU9OVEhMWSIsImlhdCI6MTc0Mzc2NTk4NX0.9PwksixkBDCbN6CNjjBAOgRUqsM3wXfnR9OwacEO2Xo",  # ← Replace with your API Key
                "campaignName": "odoo17test",  # ← Replace with your campaign name
                "destination": full_phone,  # Phone (with country code)
                "userName": record.name or "",  # Optional variable
            }

            try:
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code != 200:
                    # Better error message on failure
                    raise UserError(f"WhatsApp API error: {response.status_code}\n{response.text}")

            except Exception as e:
                # Show Odoo popup with error
                raise UserError(f"Failed to send WhatsApp message:\n{str(e)}")

            # 3️⃣ Log in chatter
            record.message_post(body=f"📩 WhatsApp intro sent to {full_phone} via AiSensy")

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    # def action_send_results_highlights(self):
    #     """Mark WhatsApp Intro as sent"""
    #     for record in self:
    #         record.results_highlights = True
    #     # Optional: Add WhatsApp API integration here
    #     return True

    def action_send_results_highlights(self):
        """Send results highlights to selected records"""
        for record in self:
            # Your existing logic here
            record.results_highlights = True

            # Example: send WhatsApp/email or message_post
            record.message_post(body="Results Highlight sent.")
        return None

    def action_second_followup(self):
        """Send results highlights to selected records"""
        for record in self:
            # Your existing logic here
            record.second_followup = True
            record.second_followup_dt = fields.Datetime.now()  # records current datetime
            # Example: send WhatsApp/email or message_post
            record.message_post(body="Second Follow Up Completed.")
        return None

    def action_add_call_log(self):
        """Create a new call log record"""
        for record in self:
            self.env["lead.call.log"].create({
                "lead_id": record.id,
                "user_id": self.env.user.id,
                "call_time": fields.Datetime.now(),
            })
            record.message_post(
                body=f"📞 Call logged by {self.env.user.name} on {fields.Datetime.now().strftime('%d-%m-%Y %H:%M:%S')}")

    def action_add_followup(self):
        """Open popup wizard"""
        for record in self:
            if not record.id:
                raise UserError("Please save the lead before adding a follow-up.")

        return {
            'name': 'Add Follow-Up',
            'type': 'ir.actions.act_window',
            'res_model': 'lead.followup.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': record.id,
                        'default_phone_number': record.phone_number,
                        },
        }

    def action_view_fee_structure(self):
        return {
            'name': 'Course Fee Structure',
            'type': 'ir.actions.act_window',
            'res_model': 'course.fee.structure',
            'view_mode': 'tree',
            'target': 'new',
        }
    # def action_add_followup(self):
    #     """Open popup wizard"""
    #     return {
    #         'name': 'Add Follow-Up',
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'lead.followup.wizard',
    #         'view_mode': 'form',
    #         'target': 'new',
    #         'context': {'default_lead_id': self.id},
    #     }

    # Close

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

        if 'lead_owner' in vals:
            for record in self:
                if vals['lead_owner'] != record.lead_owner.id:
                    self.env['lead.assignment.history'].create({
                        'lead_id': record.id,
                        'owner_id': vals['lead_owner'],
                        'assigned_date': fields.Datetime.now(),
                        'assigned_by': self.env.uid
                    })
                    vals['reassign_date'] = fields.Datetime.now()
                    
        if 'lead_quality' in vals:
            for record in self:
                # Need to use 'if vals.get('lead_quality') != record.lead_quality:'
                # And record it
                if vals.get('lead_quality') and vals['lead_quality'] != record.lead_quality:
                    self.env['lead.quality.history'].create({
                        'lead_id': record.id,
                        'lead_quality': vals['lead_quality'],
                        'user_id': self.env.uid,
                        'change_date': fields.Datetime.now()
                    })

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

    @api.constrains('phone_number', 'academic_year_of_course_attend')
    def _check_duplicate_phone_number(self):
        for record in self:
            if record.phone_number and record.academic_year_of_course_attend:
                last_10_digits = record.phone_number[-10:]

                duplicate = self.sudo().search([
                    ('phone_number', 'like', '%' + last_10_digits),
                    ('academic_year_of_course_attend', '=', record.academic_year_of_course_attend),
                    # ✅ restrict by academic year
                    ('id', '!=', record.id)
                ], limit=1)

                if duplicate:
                    lead_owner_name = duplicate.lead_owner.name if duplicate.lead_owner else "Unknown"
                    raise ValidationError(
                        _('The phone number %s already exists in academic year %s and is owned by %s. '
                          'Please use a different number.')
                        % (record.phone_number, record.academic_year_of_course_attend, lead_owner_name)
                    )
    # @api.constrains('phone_number')
    # def _check_duplicate_phone_number(self):
    #     for record in self:
    #         if record.phone_number:
    #             last_10_digits = record.phone_number[-10:]
    #
    #             duplicate = self.sudo().search([
    #                 ('phone_number', 'like', '%' + last_10_digits),
    #                 ('id', '!=', record.id)
    #             ])
    #             if duplicate:
    #                 lead_owner_name = duplicate[0].lead_owner.name if duplicate[0].lead_owner else "Unknown"
    #                 raise ValidationError(
    #                     _('The phone number %s already exists and is owned by %s. Please use a different mber.')
    #                     % (record.phone_number, lead_owner_name)
    #                 )
# old
    # def act_attempt_to_connect(self):
    #     # self.current_status = 'not_responding'
    #     self.state = 'in_progress'

    def act_attempt_to_connect(self):
        """When button is clicked, mark state and first_call"""
        for record in self:
            record.state = 'in_progress'
            record.first_call_dt = fields.Datetime.now()
            record.first_call = True
            record.lead_quality = 'first_attempt'


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
        if lead.lead_owner:
            self.env['lead.assignment.history'].create({
                'lead_id': lead.id,
                'owner_id': lead.lead_owner.id,
                'assigned_date': fields.Datetime.now(),
                'assigned_by': self.env.uid
            })

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

class LeadResponse(models.Model):
    _name = 'lead.response'
    _description = 'Lead Comments / Responses'
    _rec_name = 'comment'  # 👈 Add this line here
    _order = 'response_time desc'

    lead_id = fields.Many2one('leads.logic', string="Lead", ondelete='cascade')
    user_id = fields.Many2one('res.users', string="Responded By", default=lambda self: self.env.user)
    comment = fields.Text(string="Response / Comment", required=True)
    response_time = fields.Datetime(string="Response Time", default=fields.Datetime.now)
    is_editable = fields.Boolean(string="Editable", default=False)

    def action_enable_edit(self):
        for rec in self:
            rec.is_editable = True


    def name_get(self):
        result = []
        for record in self:
            user = record.user_id.name or "Unknown"
            date_str = record.response_time.strftime("%d-%b %H:%M") if record.response_time else ""
            comment_preview = (record.comment[:25] + '...') if record.comment and len(record.comment) > 25 else (
                        record.comment or "")
            name = f"{user} – {comment_preview} ({date_str})"
            result.append((record.id, name))
        return result
class CourseInterested(models.Model):
    _name = "course.interested"

    name = fields.Char(string="Course Name")

class LeadCallLog(models.Model):
    _name = "lead.call.log"
    _description = "Lead Call Log"
    _order = "call_time desc"

    lead_id = fields.Many2one("leads.logic", string="Lead", ondelete="cascade")
    user_id = fields.Many2one("res.users", string="Agent", default=lambda self: self.env.user)
    call_time = fields.Datetime(string="Call Time", default=lambda self: fields.Datetime.now())
    remarks = fields.Text(string="Remarks")
    call_uuid = fields.Char(string="Call UUID")
    caller_number = fields.Char(string="Caller Number")
    call_status = fields.Char(string="Call Status")
    duration = fields.Char(string="Duration")
    recording_url = fields.Char(string="Recording URL")
    call_type = fields.Selection([('incoming', 'Incoming'), ('outgoing', 'Outgoing')], string="Call Type")

# Follow up wizard

# =============================
# 1️⃣ Main Follow-Up Model
# =============================
class LeadFollowUp(models.Model):
    _name = "lead.followup"
    _description = "Lead Follow-Up"
    _order = 'status desc, next_followup_date asc'  # ✅ Status first, then recent date

    lead_id = fields.Many2one('leads.logic', string="Lead", ondelete="cascade")
    user_id = fields.Many2one('res.users', string="Follow-Up By", default=lambda self: self.env.user)
    next_followup_date = fields.Datetime(string="Next Follow-Up Date", required=True)
    remarks = fields.Text(string="Remarks")
    phone_number = fields.Char(string="Phone Number")
    status = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string="Status", default='scheduled')

    # # 🔔 Cron method to send reminders
    # @api.model
    # def _cron_remind_upcoming_followups(self):
    #     today = fields.Datetime.now()
    #     tomorrow = today + timedelta(days=1)
    #
    #     upcoming = self.search([
    #         ('next_followup_date', '>=', today),
    #         ('next_followup_date', '<', tomorrow),
    #         ('status', '=', 'scheduled')
    #     ])
    #
    #     for followup in upcoming:
    #         followup.user_id.notify_info(
    #             message=f"📅 Reminder: Follow-up scheduled for {followup.next_followup_date.strftime('%d %b %Y %H:%M')} "
    #                     f"on lead: {followup.lead_id.name or 'Unknown Lead'}",
    #             title="Follow-Up Reminder"
    #         )
    #         followup.lead_id.message_post(
    #             body=f"🔔 Reminder: Follow-up due on {followup.next_followup_date.strftime('%d %b %Y %H:%M')} "
    #                  f"for {followup.user_id.name}.",
    #         )
    # 🔔 Cron method to send reminders safely
    @api.model
    def _cron_remind_upcoming_followups(self):
        now = fields.Datetime.now()
        upcoming = now + timedelta(hours=1)

        followups = self.search([
            ('next_followup_date', '>=', now),
            ('next_followup_date', '<=', upcoming),
            ('status', '=', 'scheduled')
        ])

        for followup in followups:
            if followup.lead_id:
                # ✅ Post reminder in chatter
                followup.lead_id.message_post(
                    body=f"🔔 Reminder: Follow-up due on "
                         f"{followup.next_followup_date.strftime('%d %b %Y %H:%M')} "
                         f"for {followup.user_id.name}.",
                )

                # ✅ Optionally create an activity reminder
                self.env['mail.activity'].create({
                    'res_model': 'leads.logic',
                    'res_id': followup.lead_id.id,
                    'user_id': followup.user_id.id,
                    'summary': 'Follow-Up Reminder',
                    'note': f"Upcoming follow-up scheduled at {followup.next_followup_date.strftime('%d %b %Y %H:%M')}",
                    'date_deadline': followup.next_followup_date.date(),
                })

# =============================
# 2️⃣ Wizard for Popup Input
# =============================
class LeadFollowUpWizard(models.TransientModel):
    _name = "lead.followup.wizard"
    _inherit = ['mail.thread', 'mail.activity.mixin']  # ✅ Add this
    _description = "Add Follow-Up Wizard"

    next_followup_date = fields.Datetime(string="Next Follow-Up Date", required=True)
    remarks = fields.Text(string="Remarks")

    def action_save_followup(self):
        """Create follow-up entry for the lead"""
        active_id = self.env.context.get('active_id')
        if not active_id:
            return

        lead = self.env['leads.logic'].browse(active_id)
        self.env['lead.followup'].create({
            'lead_id': lead.id,
            'user_id': self.env.user.id,
            'next_followup_date': self.next_followup_date,
            'remarks': self.remarks,
            'status': 'scheduled',
        })

        # Post message in chatter
        lead.message_post(body=f"📞 New follow-up added on {self.next_followup_date} by {self.env.user.name}:<br/>{self.remarks}")

        # 🕓 Create Odoo activity reminder
        self.env['mail.activity'].create({
            'res_model_id': self.env['ir.model']._get_id('leads.logic'),
            'res_id': lead.id,
            'user_id': self.env.user.id,
            'summary': 'Follow-Up Reminder',
            'note': f'Remind yourself to follow up on: {self.next_followup_date.strftime("%d %b %Y %H:%M")}',
            'date_deadline': self.next_followup_date.date(),
        })


        return {'type': 'ir.actions.act_window_close'}
class CourseFeeStructure(models.Model):
    _name = 'course.fee.structure'
    _description = 'Course Fee Structure'

    course_name = fields.Char(string="Course Name")
    level = fields.Char(string="Level")
    duration = fields.Char(string="Duration")
    amount = fields.Float(string="Fees (INR)")
    image = fields.Binary(string="Course Image", attachment=True)


from odoo import models, fields

class LeadUnlockWizard(models.TransientModel):
    _name = "lead.unlock.wizard"
    _description = "Unlock Lead Editing Wizard"

    lead_id = fields.Many2one("leads.logic", required=True)

    def action_unlock(self):
        self.lead_id.is_editable = True
        return {'type': 'ir.actions.act_window_close'}



class WebinarInviteWizard(models.TransientModel):
    _name = 'webinar.invite.wizard'
    _description = 'Webinar Invite Wizard'

    lead_id = fields.Many2one('leads.logic', required=True)
    zoom_link = fields.Char(string='Zoom Link', required=True)
    webinar_date = fields.Char(string='Webinar Date / Time')

    def action_send_whatsapp(self):
        self.ensure_one()

        phone = self.lead_id.phone_number

        if not phone:
            return {'type': 'ir.actions.act_window_close'}

        message = (
            f"Hi {self.lead_id.name or ''},\n\n"
            "You are invited to our Free Webinar.\n\n"
            f"Date & Time: {self.webinar_date or 'Will be shared shortly'}\n"
            f"Zoom Link: {self.zoom_link}\n\n"
            "Please join on time."
        )

        self.lead_id.write({
            'webinar_invite_sent': True,
            'webinar_invite_sent_on': fields.Datetime.now(),
            'webinar_invite_sent_by': self.env.user.id,
            'webinar_zoom_link': self.zoom_link,
        })

        whatsapp_url = 'https://wa.me/%s?text=%s' % (
            phone.replace('+', '').replace(' ', ''),
            quote(message)
        )

        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }


    class LeadOpenHistory(models.Model):
        _name = 'lead.open.history'
        _description = 'Lead Open History'
        _order = 'opened_on desc'

        lead_id = fields.Many2one('leads.logic', string='Lead', required=True, ondelete='cascade')
        user_id = fields.Many2one('res.users', string='Opened By', required=True)
        opened_on = fields.Datetime(string='Opened On', default=fields.Datetime.now)
        ip_address = fields.Char(string='IP Address')
        remarks = fields.Char(string='Remarks')