from datetime import date, datetime, timedelta
import logging
import csv
import io
import base64
import requests
from urllib.parse import quote
from email.policy import default
from tokenize import String
from odoo.http import request
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import html_escape
from markupsafe import Markup

_logger = logging.getLogger(__name__)


def _format_user_datetime(record, value, fmt='%d %b %Y %H:%M'):
    if not value:
        return ''
    return fields.Datetime.context_timestamp(record, value).strftime(fmt)


# --------------------------------------------------------------------------
# Model: lead.assignment.history
# Description: Tracks the history of lead assignments to different owners.
# --------------------------------------------------------------------------
class LeadAssignmentHistory(models.Model):
    _name = 'lead.assignment.history'
    _description = 'Lead Assignment History'
    _order = 'create_date desc'

    lead_id = fields.Many2one('leads.logic', string='Lead', ondelete='cascade')
    owner_id = fields.Many2one('hr.employee', string='Assigned Officer')
    assigned_date = fields.Datetime(string='Assigned Date', default=fields.Datetime.now)
    assigned_by = fields.Many2one('res.users', string='Assigned By', default=lambda self: self.env.user)


# --------------------------------------------------------------------------
# Model: lead.quality.history
# Description: Tracks the history of changes made to the quality status of a lead.
# --------------------------------------------------------------------------
class LeadQualityHistory(models.Model):
    _name = 'lead.quality.history'
    _description = 'Lead Quality History'
    _order = 'create_date desc'

    lead_id = fields.Many2one('leads.logic', string='Lead', ondelete='cascade')
    lead_quality = fields.Selection(
        [
            ('new', '🆕  New'),
            ('first_attempt', '🎯 First Attempt'),
            ('waiting_for_admission', '⏳  Waiting for Admission'),
            ('admission', '🎓  Admission'),
            ('hot', '🔥  Hot'),
            ('warm', '🌞  Warm'),
            ('cold', '❄️  Cold'),
            ('bad_lead', '⚠️  Language Barrier'),
            ('crash_lead', '💥  Crash Lead'),
            ('not_responding', '🔕  Ringing Not Responding'),
            ('call_later', '📞  Call Later'),
            ('may_be_later', '🔔 May Be Later'),
            ('follow_up', '⏰  Follow Up'),
            ('not_reachable', '🚫  Not Reachable'),
            # ('already_joined', '✅ Already Joined'),
            ('joined_other_institute', '🏫 Joined Other Institute'),
            ('wrong_number', '📵 Wrong number'),
            ('not_enquiry', '🛑 Not Enquiry'),
            ('not_interested', 'Not Interested'),
        ],
        string='Lead Quality'
    )
    user_id = fields.Many2one('res.users', string='Changed By', default=lambda self: self.env.user)
    change_date = fields.Datetime(string='Change Date', default=fields.Datetime.now)


# --------------------------------------------------------------------------
# Model: leads.logic
# Description: Main Lead Management model containing all business logic,
# fields for tracking, and API integrations for calls and messaging.
# --------------------------------------------------------------------------
class LeadsForm(models.Model):
    _name = 'leads.logic'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Leads'
    _rec_name = 'name'
    _order = 'id desc'

    # Basic Information
    leads_source = fields.Many2one('leads.sources', string='Leads Source', required=1, tracking=1)
    source_name = fields.Char(string="Source", related="leads_source.name")
    source_campaign_id = fields.Many2one('lead.source.campaign', string='Source Campaign', tracking=1)
    # Helper field (not shown on the form) used purely so the Lead Source
    # dropdown can be filtered down to just the parent of whichever
    # Campaign is currently selected, e.g. picking "Urban Chat Leads Meta"
    # narrows the Lead Source field to only "Digital".
    campaign_parent_source_id = fields.Many2one(
        'leads.sources', string='Campaign Parent Source',
        related='source_campaign_id.lead_source_id', store=False
    )
    name = fields.Char(string='Lead Name', required=1, tracking=1)
    email_address = fields.Char(string='Email', tracking=1)
    phone_number = fields.Char(string='Mobile', required=1, tracking=1)
    probability = fields.Float(string='Probability')
    admission_status = fields.Boolean(string='Admission', readonly=1)
    date_of_adding = fields.Date(string='Date of Adding', default=fields.Datetime.now, readonly=1)
    last_update_date = fields.Datetime(string='Last Updated Date', default=fields.Datetime.now)
    course_id = fields.Many2one('op.course', string='Course', tracking=1)
    reference_no = fields.Char(
        "Reference",
        default=lambda self: _('New'),
        copy=False,
        readonly=True,
        tracking=True
    )
    is_editable = fields.Boolean(string="Editable", default=False)

    # Phone Masking Logic
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

    # ── Duplicate phone warning (shown inline while user types) ───────────
    is_duplicate_phone = fields.Boolean(
        string='Duplicate Phone',
        compute='_compute_is_duplicate_phone',
        store=False,
    )

    @api.depends('phone_number', 'academic_year_of_course_attend')
    def _compute_is_duplicate_phone(self):
        for rec in self:
            if rec.phone_number and rec.academic_year_of_course_attend and not rec.id:
                last_10 = rec.phone_number.replace(' ', '')[-10:]
                rec.is_duplicate_phone = bool(self.sudo().search([
                    ('phone_number', 'like', '%' + last_10),
                    ('academic_year_of_course_attend', '=', rec.academic_year_of_course_attend),
                ], limit=1))
            else:
                rec.is_duplicate_phone = False

    duplicate_lead_info = fields.Char(
        string='Duplicate Lead Info',
        compute='_compute_duplicate_lead_info',
        store=False,
    )

    @api.depends('phone_number', 'academic_year_of_course_attend')
    def _compute_duplicate_lead_info(self):
        for rec in self:
            if rec.phone_number and rec.academic_year_of_course_attend and not rec.id:
                last_10 = rec.phone_number.replace(' ', '')[-10:]
                existing = self.sudo().search([
                    ('phone_number', 'like', '%' + last_10),
                    ('academic_year_of_course_attend', '=', rec.academic_year_of_course_attend),
                ], limit=1)
                if existing:
                    owner = existing.lead_owner.name if existing.lead_owner else 'Unknown'
                    rec.duplicate_lead_info = _(
                        '⚠️ This number already has a lead (Ref: %s) assigned to %s. '
                        'Saving will create a Re-Enquiry instead of a new lead.'
                    ) % (existing.reference_no, owner)
                else:
                    rec.duplicate_lead_info = False
            else:
                rec.duplicate_lead_info = False

    # Tracking Lead

    open_count = fields.Integer(string="Open Count", default=0)
    last_opened_on = fields.Datetime(string="Last Opened On")
    last_opened_by = fields.Many2one('res.users', string="Last Opened By")
    open_history_ids = fields.One2many('lead.open.history', 'lead_id', string='Open History')

    # FIX: Rename the 'fields' argument to 'requested_fields' to avoid naming conflict
    def web_read(self, specification):
        res = super(LeadsForm, self).web_read(specification)

        # Log the access only when opening a single record
        if len(self) == 1:
            try:
                # 2. Use request.httprequest.remote_addr to get the IP
                ip_addr = 'Internal/Unknown'
                if request:
                    # remote_addr will capture the real IP if proxy_mode = True in odoo.conf
                    ip_addr = request.httprequest.remote_addr or 'Internal/Unknown'

                # Create the log entry
                self.env['lead.open.history'].sudo().create({
                    'lead_id': self.id,
                    'user_id': self.env.user.id,
                    'opened_on': fields.Datetime.now(),
                    'ip_address': ip_addr,
                    'remarks': _('Lead Form Accessed via Web Client')
                })

                # Update the main lead record counters
                self.sudo().write({
                    'last_opened_on': fields.Datetime.now(),
                    'last_opened_by': self.env.user.id,
                    'open_count': self.open_count + 1
                })

            except Exception as e:
                _logger.error("AUDIT ERROR: %s", str(e))

        return res

    def write(self, vals):
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
                if vals.get('lead_quality') and vals['lead_quality'] != record.lead_quality:
                    self.env['lead.quality.history'].create({
                        'lead_id': record.id,
                        'lead_quality': vals['lead_quality'],
                        'user_id': self.env.uid,
                        'change_date': fields.Datetime.now()
                    })

        if 'call_response' in vals and vals['call_response']:
            response_obj = self.env['call.responses'].search([('name', '=', vals['call_response'])], limit=1)
            if not response_obj:
                response_obj = self.env['call.responses'].create({'name': vals['call_response']})
            if 'call_responses' in vals:
                vals['call_responses'].append((4, response_obj.id))
            else:
                vals['call_responses'] = [(4, response_obj.id)]
            vals['call_response'] = False

        if vals.get('source_campaign_id') and 'leads_source' not in vals:
            campaign = self.env['lead.source.campaign'].browse(vals['source_campaign_id'])
            if campaign.lead_source_id:
                vals['leads_source'] = campaign.lead_source_id.id

        res = super(LeadsForm, self).write(vals)
        if 'is_editable' not in vals:
            self.is_editable = False

        # ── Auto student_category when Lead Source / Campaign changes ──────
        # Only fills leads that don't already have a category set manually
        # or from a previous auto-guess — never overrides an existing value.
        if 'leads_source' in vals or 'source_campaign_id' in vals:
            for record in self:
                if not record.student_category:
                    guess = self._guess_student_category(
                        record.leads_source.name if record.leads_source else '',
                        record.source_campaign_id.name if record.source_campaign_id else '',
                    )
                    if guess:
                        record.student_category = guess
        return res

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, order=None):
        args = args or []
        domain = []
        if name:
            domain = ['|', ('name', operator, name), ('phone_number', operator, name)]
        # referral_search: use a superuser env so ir.rule filters are fully bypassed.
        # We call the BASE _search on a sudo env to avoid re-entering our own override.
        if self.env.context.get('referral_search'):
            sudo_model = self.sudo().with_context(skip_leads_logic_search_override=True)
            return sudo_model._search(domain + args, limit=limit, order=order)
        return self._search(domain + args, limit=limit, order=order)

    # Lead Quality and Status
    lead_quality = fields.Selection(
        [
            ('new', '🆕  New'), ('first_attempt', '🎯 First Attempt'),
            ('waiting_for_admission', '⏳  Waiting for Admission'), ('admission', '🎓  Admission'),
            ('hot', '🔥  Hot'), ('warm', '🌞  Warm'), ('cold', '❄️  Cold'),
            ('bad_lead', '⚠️  Language Barrier'), ('crash_lead', '💥  Crash Lead'),
            ('not_responding', '🔕  Ringing Not Responding'),
            ('call_later', '📞  Call Later'), ('may_be_later', '🔔 May Be Later'),
            ('follow_up', '⏰  Follow Up'), ('not_reachable', '🚫  Not Reachable'),
            ('logic_students', 'Logic Students'),
            ('already_joined', '✅ Already Joined'), ('joined_other_institute', '🏫 Joined Other Institute'),
            ('wrong_number', '📵 Wrong number'), ('not_enquiry', '🛑 Not Enquiry')
        ],
        string='Lead Quality', default='new', required=1, readonly=0, tracking=1
    )

    lead_stage_category = fields.Selection([
        ('funnel', 'FUNNEL'),
        ('prospects', 'PROSPECTS'),
        ('rnr_dnp', 'RNR / DNP'),
        ('admission_done', 'ADMISSION DONE'),
        ('re_try', 'RE-TRY'),
        ('alumni', 'ALUMNI'),
        ('junk', 'JUNK')
    ], string='Stage Category', compute='_compute_lead_stage', store=True)

    @api.depends('lead_quality')
    def _compute_lead_stage(self):
        for record in self:
            quality = record.lead_quality

            if quality in ['hot', 'warm', 'cold', 'call_later',
                           'waiting_for_admission',
                           'crash_lead', 'already_joined']:
                record.lead_stage_category = 'prospects'

            elif quality in ['new', 'first_attempt', 'follow_up']:
                record.lead_stage_category = 'funnel'

            elif quality in ['not_interested', 'joined_other_institute']:
                record.lead_stage_category = 're_try'

            elif quality in ['logic_students']:
                record.lead_stage_category = 'alumni'

            elif quality in ['not_responding', 'not_reachable']:
                record.lead_stage_category = 'rnr_dnp'

            elif quality in ['admission', 'converted']:
                record.lead_stage_category = 'admission_done'

            elif quality in ['bad_lead', 'not_enquiry',
                             'wrong_number']:
                record.lead_stage_category = 'junk'
            else:
                record.lead_stage_category = False

        # The actual toggle

    # hide_marketing_stages = fields.Boolean(default=False)
    hide_marketing_stages = fields.Boolean(string="Hide Toggle", default=False)

    marketing_button_label = fields.Char(compute="_compute_marketing_button_label")

    @api.depends('hide_marketing_stages')
    def _compute_marketing_button_label(self):
        for record in self:
            record.marketing_button_label = "Show Sales Guide" if record.hide_marketing_stages else "Hide Sales Guide"

    def action_toggle_marketing_info(self):
        for record in self:
            # We use write so Odoo acknowledges the change immediately in the UI
            record.write({'hide_marketing_stages': not record.hide_marketing_stages})

    lost_reason = fields.Text(string="Lost Reason")
    crash_user_id = fields.Many2one('res.users', string="Crash User")
    # lead_status = fields.Selection(
    #     [
    #         ('not_responding', 'Not Responding'),
    #         ('already_enrolled', 'Already Enrolled'),
    #         ('joined_in_another_institute', 'Joined in another institute'),
    #         ('nil', 'Nil')
    #     ],
    #     string='Lead Status',
    # )
    place = fields.Char('Place')
    lead_owner = fields.Many2one('hr.employee', string='Lead Owner', default=lambda self: self.env.user.employee_id.id,
                                 tracking=1)
    seminar_lead_id = fields.Char()
    admission_date = fields.Datetime(string="Admission Date")
    phone_number_second = fields.Char(string='Phone Number')
    branch_id = fields.Many2one('op.branch', string="Branch")
    course_interested = fields.Char(string="Course Interested")
    seminar_id = fields.Integer(string="Seminar")
    preferred_course = fields.Char(string="Preferred Course")
    academic_year_of_course_attend = fields.Selection(
        [
            ('2023-2024', '2023-2024'), ('2024-2025', '2024-2025'),
            ('2025-2026', '2025-2026'), ('2026-2027', '2026-2027')
        ],
        string="Academic Year of Course attended", default='2025-2026'
    )
    course_type = fields.Selection(
        [
            ('indian', 'Indian'), ('international', 'International'),
            ('crash', 'Crash'), ('repeaters', 'Repeaters'), ('nil', 'Nil')
        ],
        string='Course Type'
    )

    # State and Lifecycle
    state = fields.Selection(
        [
            ('new', 'New'), ('in_progress', 'In Progress'),
            ('qualified', 'Admission'), ('lost', 'Lost')
        ],
        string='State',
        default='new', tracking=True
    )
    last_studied_course = fields.Char(string='Last Studied Course')
    incoming_source = fields.Selection(
        [
            ('social_media', 'Social Media'), ('google', 'Google'), ('hoardings', 'Hoardings'),
            ('tv_ads', 'TV Ads'), ('through friends', 'Through Friends'), ('whatsapp', 'WhatsApp'),
            ('re_admission', 'Re-Admission'), ('other', 'Other')
        ],
        string='Incoming Calls / Walk In Source'
    )
    incoming_source_checking = fields.Boolean(string='Incoming Source Checking')
    academic_year = fields.Selection(
        [('2024-2025', '2024-2025'), ('2025-2026', '2025-2026'), ('2026-2027', '2026-2027'), ('2027-2028', '2027-2028'),
         ('nil', 'Nil')],
        string="Academic Year", tracking=1
    )
    college_name = fields.Char(string='College/School')
    title = fields.Char(string="Title")
    lead_referral_staff_id = fields.Many2one('res.users', string='Lead Referral Staff')
    referred_by = fields.Selection([('staff', 'Staff'), ('student', 'Student'), ('other', 'Other')],
                                   string='Referred By')
    campaign = fields.Selection(
        [
            ('CA Weekend Thrissur', 'CA Weekend Thrissur'), ('CA Weekend Ernakulam', 'CA Weekend Ernakulam'),
            ('CA Weekend Trivandrum', 'CA Weekend Trivandrum'), ('CA Weekend Calicut', 'CA Weekend Calicut'),
            ('CA Weekend Perintalmanna', 'CA Weekend Perintalmanna')
        ],
        string='Campaign'
    )
    country = fields.Selection(
        [
            ('india', 'India'), ('germany', 'Germany'), ('canada', 'Canada'), ('usa', 'USA'),
            ('australia', 'Australia'),
            ('italy', 'Italy'), ('france', 'France'), ('united_kingdom', 'United Kingdom'),
            ('saudi_arabia', 'Saudi Arabia'), ('ukraine', 'Ukraine'), ('united_arab_emirates', 'United Arab Emirates'),
            ('china', 'China'), ('japan', 'Japan'), ('singapore', 'Singapore'), ('indonesia', 'Indonesia'),
            ('russia', 'Russia'), ('oman', 'Oman'), ('nepal', 'Nepal'), ('japan', 'Japan')
        ],
        string='Country', default='india'
    )
    referred_by_id = fields.Many2one('hr.employee', string='Referred Person')
    second_response = fields.Text(string="2nd Response")
    referred_by_name = fields.Char(string='Referred Person')
    referred_by_number = fields.Char(string='Referred Person Number')
    batch_preference = fields.Char(string='Batch Preference')
    tele_caller_id = fields.Many2one('res.users', String="Tele Caller")
    lead_qualification = fields.Selection(
        [
            ('plus_one_science', 'Plus One Science'), ('plus_two_science', 'Plus Two Science'),
            ('plus_two_commerce', 'Plus Two Commerce'), ('plus_one_commerce', 'Plus One Commerce'),
            ('commerce_degree', 'Commerce Degree'), ('other_degree', 'Other Degree'),
            ('working_professional', 'Working Professional')
        ],
        string='Lead qualification'
    )
    student_category = fields.Selection(
        [
            ('plus_one', 'Plus One'), ('plus_two', 'Plus Two'),
            ('bcom_1', 'B.Com 1st Year'), ('bcom_2', 'B.Com 2nd Year'),
            ('bcom_3', 'B.Com 3rd Year'), ('meta_leads', 'Meta Leads'),
            ('others', 'Others'),
        ],
        string='Student Category', tracking=1,
        help="Nurturing segment for this lead. Auto-guessed from the Lead "
             "Source / Source Campaign name (see _guess_student_category), "
             "but can always be corrected manually — a manual value is "
             "never overwritten by the auto-guess. 'Others' catches every "
             "lead with a Lead Source / Campaign that doesn't match one of "
             "the named categories."
    )

    # Checked in order — first keyword match wins. Longer/more specific
    # patterns are listed before the shorter ones they could be confused
    # with (e.g. 'bcom 3' before a bare 'bcom'). Anything with a Lead
    # Source / Campaign that matches none of these falls through to
    # 'others' in _guess_student_category below.
    _STUDENT_CATEGORY_KEYWORDS = [
        ('bcom_3', ['bcom 3', 'b.com 3', 'bcom3', 'b com 3', 'bcom iii', 'bcom-3']),
        ('bcom_2', ['bcom 2', 'b.com 2', 'bcom2', 'b com 2', 'bcom ii', 'bcom-2']),
        ('bcom_1', ['bcom 1', 'b.com 1', 'bcom1', 'b com 1', 'bcom i', 'bcom-1']),
        ('plus_two', ['plus two', 'plus 2', 'plustwo', 'plus-two', '+2']),
        ('plus_one', ['plus one', 'plus 1', 'plusone', 'plus-one', '+1']),
        ('meta_leads', ['meta', 'facebook', 'instagram', 'whatsapp', ' fb ', 'fb ads']),
    ]

    @api.model
    def _guess_student_category(self, source_name, campaign_name):
        """Return a student_category key guessed from the Lead Source /
        Source Campaign names. Falls back to 'others' when there IS a
        source/campaign name to go on but none of the specific keywords
        match, so every categorisable lead lands somewhere on the
        Nurturing Dashboard. Returns False only when there's nothing at
        all to guess from (no source, no campaign)."""
        source_name = (source_name or '').strip()
        campaign_name = (campaign_name or '').strip()
        text = f" {source_name} {campaign_name} ".lower()
        for key, keywords in self._STUDENT_CATEGORY_KEYWORDS:
            for kw in keywords:
                if kw in text:
                    return key
        if source_name or campaign_name:
            return 'others'
        return False

    @api.onchange('leads_source', 'source_campaign_id')
    def _onchange_source_guess_student_category(self):
        if not self.student_category:
            guess = self._guess_student_category(
                self.leads_source.name if self.leads_source else '',
                self.source_campaign_id.name if self.source_campaign_id else '',
            )
            if guess:
                self.student_category = guess

    def action_recalculate_student_category(self):
        """Bulk action (list view, multi-select): force re-guess the
        Student Category from each lead's current Lead Source / Campaign,
        overwriting whatever is there — used to backfill legacy leads."""
        for record in self:
            guess = record._guess_student_category(
                record.leads_source.name if record.leads_source else '',
                record.source_campaign_id.name if record.source_campaign_id else '',
            )
            if guess:
                record.student_category = guess

    whatsapp_sent_count = fields.Integer(string='WhatsApp Sent', default=0, readonly=True,
                                         help="Number of times this lead was included in a "
                                              "WhatsApp nurturing export.")
    sms_sent_count = fields.Integer(string='SMS Sent', default=0, readonly=True,
                                    help="Number of times this lead was included in an "
                                         "SMS nurturing export.")
    adm_id = fields.Integer(string='Admission Id')
    student_id = fields.Many2one('op.student', string='Student Id')
    district = fields.Selection(
        [
            ('wayanad', 'Wayanad'), ('ernakulam', 'Ernakulam'), ('kollam', 'Kollam'),
            ('thiruvananthapuram', 'Thiruvananthapuram'), ('kottayam', 'Kottayam'),
            ('kozhikode', 'Kozhikode'), ('palakkad', 'Palakkad'), ('kannur', 'Kannur'),
            ('alappuzha', 'Alappuzha'), ('malappuram', 'Malappuram'), ('kasaragod', 'Kasaragod'),
            ('thrissur', 'Thrissur'), ('idukki', 'Idukki'), ('pathanamthitta', 'Pathanamthitta'),
            ('abroad', 'Abroad'), ('other', 'Other'), ('nil', 'Nil')
        ],
        string='District'
    )
    referred_teacher = fields.Many2one('res.users', string='Referred Teacher')
    over_due = fields.Boolean(string='Over Due')
    next_follow_up_date = fields.Date(string="Next Follow Up Date")
    remarks = fields.Char(string='Remarks')
    parent_number = fields.Char('Parent Number')
    closing_date = fields.Date(string="Closing Date")
    call_responses = fields.Many2many('call.responses', string="Call Responses", compute='_compute_total_responses',
                                      store=1)
    third_response = fields.Text(string="Last Response")
    mode_of_study = fields.Selection([('online', 'Online'), ('offline', 'Offline'), ('nil', 'Nil')],
                                     string='Mode of Study')
    company_id = fields.Many2one(string='Company', comodel_name='res.company', required=True,
                                 default=lambda self: self.env.company)
    assigned_date = fields.Date(string='Assigned Date', compute="_compute_lead_owner", store=1)
    reassign_date = fields.Datetime(string='Reassign Date', readonly=True)
    assignment_history_ids = fields.One2many('lead.assignment.history', 'lead_id', string='Assignment History',
                                             readonly=True)
    quality_history_ids = fields.One2many('lead.quality.history', 'lead_id', string='Lead Quality History',
                                          readonly=True)
    digital_lead = fields.Boolean(string="Digital Lead")
    digital_lead_source = fields.Selection(
        [
            ('just_dial', 'Just Dial'), ('youtube_google', 'Youtube - Google'),
            ('whatsapp_campaign', 'Whatsapp Campaign'),
            ('messenger', 'Messenger'), ('facebook', 'Facebook'), ('linkedin', 'Linkedin'), ('instagram', 'Instagram'),
            ('whatsapp_meta', 'Whatsapp Meta'), ('website', 'Website'), ('google', 'Google')
        ],
        string="Digital Lead Source"
    )
    platform = fields.Selection(
        [('facebook', 'Facebook'), ('instagram', 'Instagram'), ('website', 'Website'), ('just_dial', 'Just Dial'),
         ('other', 'Other')],
        string='Platform'
    )
    expected_joining_date = fields.Date(string="Expected Joining Date")
    not_response_note = fields.Text(string="Not Respond Reason")
    current_status = fields.Selection(
        [('new_lead', 'New Lead'), ('not_responding', 'Not Responding'), ('need_follow_up', 'Need Follow-Up'),
         ('admission', 'Admission'), ('lost', 'Lost')],
        string="Current Status", default="new_lead"
    )
    # call_response = fields.Text(string="Response")
    transitions = fields.Selection(
        [('future_lead', 'Future Lead'), ('junk_lead', 'Junk Lead'), ('not_qualified', 'Not Qualified'),
         ('qualified', 'Qualified')],
        string="Transitions", tracking=1
    )
    sample = fields.Char(string='Sample', compute='get_phone_number_for_whatsapp')
    sended_welcome_mail = fields.Boolean(string="Sended Welcome Mail")
    receipt_no = fields.Char(string="Receipt No.")
    admission_amount = fields.Float(string="Admission Fee")
    date_of_receipt = fields.Date(string="Date of Receipt")
    student_profile_created = fields.Boolean(string="Student Profile Created")
    crash_lead = fields.Boolean(string="Crash Lead")
    stream = fields.Char(string="Stream")
    digital_head_id = fields.Many2one('res.users', string='Digital Head')
    response_ids = fields.One2many('lead.response', 'lead_id', string="Responses", tracking=False)
    course_inter = fields.Many2many('course.interested', string="Course Interested In")
    call_log_ids = fields.One2many("lead.call.log", "lead_id", string="Call History")
    followup_ids = fields.One2many('lead.followup', 'lead_id', string="Follow Ups")

    # ── Step notification helpers ──────────────────────────────────────────
    has_followup = fields.Boolean(
        string='Has Follow-Up',
        compute='_compute_step_flags',
        store=True,
    )
    # Exempt qualities: no step notification needed
    _STEP_EXEMPT_QUALITIES = {
        'already_joined', 'admission', 'waiting_for_admission',
        'bad_lead', 'crash_lead', 'joined_other_institute',
        'wrong_number', 'not_enquiry',
    }

    @api.depends('followup_ids', 'next_follow_up_date')
    def _compute_step_flags(self):
        for rec in self:
            rec.has_followup = bool(rec.followup_ids) or bool(rec.next_follow_up_date)

    # CIAP and Media Tracking Fields
    is_ciap_selected = fields.Boolean(compute="_compute_is_ciap_selected")
    is_acca_selected = fields.Boolean(compute="_compute_course_selection")
    is_cma_india_cat_selected = fields.Boolean(compute="_compute_course_selection")
    is_cma_usa_selected = fields.Boolean(compute="_compute_course_selection")
    is_ca_inter_selected = fields.Boolean(compute="_compute_course_selection")
    is_ca_selected = fields.Boolean(compute="_compute_course_selection")
    ciap_media_sent = fields.Boolean(string="Course Launching Videos", default=False)
    ciap_media_sent_date = fields.Datetime(string="Course Launching Videos On")
    ciap_media_sent_by = fields.Many2one('res.users', string="Course Launching Videos By")
    ciap_assessment_test_sent = fields.Boolean("Assessment Test Sent")
    ciap_assessment_test_sent_date = fields.Datetime(readonly=True)

    # CMA USA Tracking
    # --- CMA USA STAGE 1 ---
    cma_usa_short_video_sent = fields.Boolean("CMA Short Video Sent")
    cma_usa_short_video_date = fields.Datetime("CMA Short Video Date", readonly=True)
    cma_usa_starter_kit_sent = fields.Boolean("CMA Starter Kit Sent")
    cma_usa_starter_kit_date = fields.Datetime("CMA Starter Kit Date", readonly=True)
    cma_usa_webinar_invite_sent = fields.Boolean("CMA Webinar Sent")
    cma_usa_webinar_invite_date = fields.Datetime("CMA Webinar Date", readonly=True)

    # --- CMA USA STAGE 2 ---
    cma_usa_brochure_sent = fields.Boolean("CMA Brochure Sent")
    cma_usa_brochure_date = fields.Datetime("CMA Brochure Date", readonly=True)
    cma_usa_detailed_videos_sent = fields.Boolean("CMA Detailed Videos Sent")
    cma_usa_detailed_videos_date = fields.Datetime("CMA Detailed Videos Date", readonly=True)
    cma_usa_demo_class_sent = fields.Boolean("CMA Demo Class Sent")
    cma_usa_demo_class_date = fields.Datetime("CMA Demo Class Date", readonly=True)

    # --- CMA USA STAGE 3 ---
    cma_usa_results_posters_sent = fields.Boolean("CMA Results Sent")
    cma_usa_results_posters_date = fields.Datetime("CMA Results Date", readonly=True)
    cma_usa_rank_holders_sent = fields.Boolean("CMA Rank Holders Sent")
    cma_usa_rank_holders_date = fields.Datetime("CMA Rank Holders Date", readonly=True)
    cma_usa_faculty_pool_sent = fields.Boolean("CMA Faculty Pool Sent")
    cma_usa_faculty_pool_date = fields.Datetime("CMA Faculty Pool Date", readonly=True)

    # --- CMA USA STAGE 4 ---
    cma_usa_testimonials_sent = fields.Boolean("CMA Testimonials Sent")
    cma_usa_testimonials_date = fields.Datetime("CMA Testimonials Date", readonly=True)
    cma_usa_winners_meet_sent = fields.Boolean("CMA Winners Meet Sent")
    cma_usa_winners_meet_date = fields.Datetime("CMA Winners Meet Date", readonly=True)

    # --- CMA USA STAGE 5 ---
    cma_usa_placements_sent = fields.Boolean("CMA Placements Sent")
    cma_usa_placements_date = fields.Datetime("CMA Placements Date", readonly=True)

    # --- CMA USA STAGE 6 ---
    cma_usa_value_added_sent = fields.Boolean("CMA Value Added Sent")
    cma_usa_value_added_date = fields.Datetime("CMA Value Added Date", readonly=True)
    cma_usa_study_materials_sent = fields.Boolean("CMA Study Materials Sent")
    cma_usa_study_materials_date = fields.Datetime("CMA Study Materials Date", readonly=True)

    # --- CMA USA STAGE 7 ---
    cma_usa_counselling_done = fields.Boolean("CMA Counselling Done")
    cma_usa_counselling_date = fields.Datetime("CMA Counselling Date", readonly=True)

    # ACCA

    # --- ACCA STAGE 1 ---
    acca_short_video_sent = fields.Boolean("ACCA Short Video Sent")
    acca_short_video_date = fields.Datetime("ACCA Short Video Date", readonly=True)
    acca_starter_kit_sent = fields.Boolean("ACCA Starter Kit Sent")
    acca_starter_kit_date = fields.Datetime("ACCA Starter Kit Date", readonly=True)
    acca_webinar_invite_sent = fields.Boolean("ACCA Webinar Sent")
    acca_webinar_invite_date = fields.Datetime("ACCA Webinar Date", readonly=True)

    # --- ACCA STAGE 2 ---
    acca_brochure_sent = fields.Boolean("ACCA Brochure Sent")
    acca_brochure_date = fields.Datetime("ACCA Brochure Date", readonly=True)
    acca_detailed_videos_sent = fields.Boolean("ACCA Detailed Videos Sent")
    acca_detailed_videos_date = fields.Datetime("ACCA Detailed Videos Date", readonly=True)
    acca_demo_class_sent = fields.Boolean("ACCA Demo Class Sent")
    acca_demo_class_date = fields.Datetime("ACCA Demo Class Date", readonly=True)

    # --- ACCA STAGE 3 ---
    acca_results_posters_sent = fields.Boolean("ACCA Results Sent")
    acca_results_posters_date = fields.Datetime("ACCA Results Date", readonly=True)
    acca_rank_holders_sent = fields.Boolean("ACCA Rank Holders Sent")
    acca_rank_holders_date = fields.Datetime("ACCA Rank Holders Date", readonly=True)
    acca_faculty_pool_sent = fields.Boolean("ACCA Faculty Pool Sent")
    acca_faculty_pool_date = fields.Datetime("ACCA Faculty Pool Date", readonly=True)

    # --- ACCA STAGE 4 ---
    acca_testimonials_sent = fields.Boolean("ACCA Testimonials Sent")
    acca_testimonials_date = fields.Datetime("ACCA Testimonials Date", readonly=True)
    acca_winners_meet_sent = fields.Boolean("ACCA Winners Meet Sent")
    acca_winners_meet_date = fields.Datetime("ACCA Winners Meet Date", readonly=True)

    # --- ACCA STAGE 5 ---
    acca_placements_sent = fields.Boolean("ACCA Placements Sent")
    acca_placements_date = fields.Datetime("ACCA Placements Date", readonly=True)

    # --- ACCA STAGE 6 ---
    acca_value_added_sent = fields.Boolean("ACCA Value Added Sent")
    acca_value_added_date = fields.Datetime("ACCA Value Added Date", readonly=True)
    acca_study_materials_sent = fields.Boolean("ACCA Study Materials Sent")
    acca_study_materials_date = fields.Datetime("ACCA Study Materials Date", readonly=True)

    # --- ACCA STAGE 7 ---
    acca_counselling_done = fields.Boolean("ACCA Counselling Done")
    acca_counselling_date = fields.Datetime("ACCA Counselling Date", readonly=True)

    # Stages Completion Tracking

    @api.depends('course_inter')
    def _compute_is_ciap_selected(self):
        for rec in self:
            rec.is_ciap_selected = any(course.name == 'CIAP' for course in rec.course_inter)

    @api.depends('course_inter.name')
    def _compute_course_selection(self):
        for rec in self:
            # Get all selected course names into a set for easy checking
            selected_names = set(rec.course_inter.mapped('name'))

            # Map each boolean to a check against the set
            # rec.is_ciap_selected = 'CIAP' in selected_names
            rec.is_acca_selected = any(course in selected_names for course in ['ACCA', 'BCom + ACCA', 'MBA + ACCA'])
            rec.is_cma_india_cat_selected = 'CMA India - CAT' in selected_names
            rec.is_cma_usa_selected = 'CMA USA' in selected_names
            rec.is_ca_inter_selected = 'CA INTER' in selected_names
            rec.is_ca_selected = 'CA' in selected_names

    def action_send_course_launch_media(self):
        self.ensure_one()
        if self.ciap_media_sent:
            return
        phone = self.phone_number
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

    # Progress Visualization Logic
    progress_html = fields.Html(compute='_compute_progress_html', sanitize=False)

    def action_send_cma_usa_video(self):
        """Sends CMA USA Short Course Details Video via WhatsApp"""
        self.ensure_one()

        # Replace this with your actual video link
        video_link = "https://yourdomain.com/cma-usa-details-video"
        message = (
            f"Hi {self.name or ''},\n\n"
            "Watch this short video to understand the CMA USA course structure, "
            "syllabus, and career opportunities:\n\n"
            f"{video_link}\n\n"
            "Let me know if you have any questions!"
        )

        # Use your existing helper or direct logic
        return self._send_whatsapp_link(
            'cma_usa_video_sent',
            'cma_usa_video_sent_date',
            message
        )

    @api.depends(
        'course_inter', 'course_inter.name', 'first_call', 'webinar_invite_sent', 'ciap_media_sent',
        'stage1_completed', 'stage2_completed', 'stage3_completed', 'stage4_completed',
        'stage5_completed', 'stage6_completed', 'stage7_completed',

        # --- CIAP Dependencies ---
        'ciap_roadmap_sent', 'ciap_brochure_sent', 'detailed_ciap_video_sent',
        'ciap_demo_class_sent', 'ciap_assessment_test_sent', 'ciap_faculty_pool_sent',
        'ciap_value_added_videos_sent', 'ciap_testimonials_sent', 'ciap_winners_meet_sent',
        'ciap_placement_media_sent', 'ciap_starter_kit_sent', 'ciap_key_benefits_reshared',
        'ciap_career_counselling_sent',

        # --- CMA USA Dependencies ---
        'cma_usa_short_video_sent', 'cma_usa_starter_kit_sent', 'cma_usa_webinar_invite_sent',
        'cma_usa_brochure_sent', 'cma_usa_detailed_videos_sent', 'cma_usa_demo_class_sent',
        'cma_usa_results_posters_sent', 'cma_usa_rank_holders_sent', 'cma_usa_faculty_pool_sent',
        'cma_usa_testimonials_sent', 'cma_usa_winners_meet_sent', 'cma_usa_placements_sent',
        'cma_usa_value_added_sent', 'cma_usa_study_materials_sent', 'cma_usa_counselling_done',

        # --- ACCA Dependencies ---
        'is_acca_selected',
        'acca_short_video_sent', 'acca_starter_kit_sent', 'acca_webinar_invite_sent',
        'acca_brochure_sent', 'acca_detailed_videos_sent', 'acca_demo_class_sent',
        'acca_results_posters_sent', 'acca_rank_holders_sent', 'acca_faculty_pool_sent',
        'acca_testimonials_sent', 'acca_winners_meet_sent', 'acca_placements_sent',
        'acca_value_added_sent', 'acca_study_materials_sent', 'acca_counselling_done',
    )
    def _compute_progress_html(self):
        for rec in self:
            names = set(rec.course_inter.mapped('name'))

            # --- 1. Top Progress Bar (Circles) ---
            stages = [
                ('Stage 1', '📞', rec.stage1_completed),
                ('Stage 2', '📚', rec.stage2_completed),
                ('Stage 3', '🎓', rec.stage3_completed),
                ('Stage 4', '🏆', rec.stage4_completed),
                ('Stage 5', '💼', rec.stage5_completed),
                ('Stage 6', '🎁', rec.stage6_completed),
                ('Stage 7', '🤝', rec.stage7_completed),
            ]

            html = '<div class="crm-progress-wrapper"><div class="crm-progress-row">'
            for i, (label, icon, done) in enumerate(stages):
                circle_class = "progress-circle done" if done else (
                    "progress-circle active" if (i == 0 or stages[i - 1][2]) else "progress-circle")
                html += f'<div class="progress-step"><div class="{circle_class}">{"✓" if done else icon}</div><div class="progress-label">{label}</div></div>'
                if i < len(stages) - 1:
                    line_class = "progress-line done" if done else "progress-line"
                    html += f'<div class="{line_class}"></div>'
            html += '</div><div class="stage-checklist-container">'

            # --- 2. CIAP FULL TRACK ---
            if 'CIAP' in names:
                html += f"""
                    <div style="font-weight:bold; color:#1e3a8a; margin-top:15px; border-bottom:2px solid #1e3a8a;">CIAP TRACK</div>
                    <div class="stage-checklist">
                        <div class="stage-column">
                            <div class="stage-title">Stage 1</div>
                            <div>{'✅' if rec.first_call else '⬜'} First Call</div>
                            <div>{'✅' if rec.webinar_invite_sent else '⬜'} Webinar Sent</div>
                            <div>{'✅' if rec.ciap_media_sent else '⬜'} CIAP Media</div>
                        </div>
                        <div class="stage-column">
                            <div class="stage-title">Stage 2</div>
                            <div>{'✅' if rec.ciap_roadmap_sent else '⬜'} Roadmap</div>
                            <div>{'✅' if rec.ciap_brochure_sent else '⬜'} Brochure</div>
                            <div>{'✅' if rec.detailed_ciap_video_sent else '⬜'} Detailed Videos</div>
                            <div>{'✅' if rec.ciap_demo_class_sent else '⬜'} Demo Class</div>
                        </div>
                        <div class="stage-column">
                            <div class="stage-title">Stage 3</div>
                            <div>{'✅' if rec.ciap_faculty_pool_sent else '⬜'} Faculty Pool</div>
                            <div>{'✅' if rec.ciap_value_added_videos_sent else '⬜'} Value Added</div>
                        </div>
                    </div>
                    <div class="stage-checklist" style="margin-top:10px;">
                        <div class="stage-column">
                            <div class="stage-title">Stage 4</div>
                            <div>{'✅' if rec.ciap_testimonials_sent else '⬜'} Testimonials</div>
                            <div>{'✅' if rec.ciap_winners_meet_sent else '⬜'} Winners Meet</div>
                        </div>
                        <div class="stage-column">
                            <div class="stage-title">Stage 5</div>
                            <div>{'✅' if rec.ciap_placement_media_sent else '⬜'} Placements</div>
                        </div>
                        <div class="stage-column">
                            <div class="stage-title">Stage 6</div>
                            <div>{'✅' if rec.ciap_starter_kit_sent else '⬜'} Starter Kit</div>
                            <div>{'✅' if rec.ciap_key_benefits_reshared else '⬜'} Benefits Sent</div>
                        </div>
                        <div class="stage-column">
                            <div class="stage-title">Stage 7</div>
                            <div>{'✅' if rec.ciap_career_counselling_sent else '⬜'} Counselling</div>
                        </div>
                    </div>"""

            # --- 3. CMA USA TRACK ---
            if 'CMA USA' in names:
                html += f"""
                    <div style="font-weight:bold; color:#b91c1c; margin-top:15px; border-bottom:2px solid #b91c1c;">CMA USA TRACK</div>
                    <div class="stage-checklist">
                        <div class="stage-column">
                            <div class="stage-title">Stage 1: Attention</div>
                            <div>{'✅' if rec.cma_usa_short_video_sent else '⬜'} Short Video</div>
                            <div>{'✅' if rec.cma_usa_starter_kit_sent else '⬜'} Starter Kit</div>
                            <div>{'✅' if rec.cma_usa_webinar_invite_sent else '⬜'} Webinar Invite</div>
                        </div>
                        <div class="stage-column">
                            <div class="stage-title">Stage 2: Clarity</div>
                            <div>{'✅' if rec.cma_usa_brochure_sent else '⬜'} Brochure</div>
                            <div>{'✅' if rec.cma_usa_detailed_videos_sent else '⬜'} Detailed Videos</div>
                            <div>{'✅' if rec.cma_usa_demo_class_sent else '⬜'} Demo Class</div>
                        </div>
                        <div class="stage-column">
                            <div class="stage-title">Stage 3: Trust</div>
                            <div>{'✅' if rec.cma_usa_results_posters_sent else '⬜'} Results Posters</div>
                            <div>{'✅' if rec.cma_usa_rank_holders_sent else '⬜'} Rank Holders List</div>
                            <div>{'✅' if rec.cma_usa_faculty_pool_sent else '⬜'} Faculty Pool</div>
                        </div>
                    </div>
                    <div class="stage-checklist" style="margin-top:10px;">
                        <div class="stage-column">
                            <div class="stage-title">Stage 4: Proof</div>
                            <div>{'✅' if rec.cma_usa_testimonials_sent else '⬜'} Testimonials</div>
                            <div>{'✅' if rec.cma_usa_winners_meet_sent else '⬜'} Winners Meet Videos</div>
                        </div>
                        <div class="stage-column">
                            <div class="stage-title">Stage 5: Outcome Proof</div>
                            <div>{'✅' if rec.cma_usa_placements_sent else '⬜'} Placements</div>
                        </div>

                        <div class="stage-column">
                            <div class="stage-title">Stage 6 & 7: Closing</div>
                            <div>{'✅' if rec.cma_usa_value_added_sent else '⬜'} Value Added</div>
                            <div>{'✅' if rec.cma_usa_counselling_done else '⬜'} 1-on-1 Counselling</div>
                            <div>{'✅' if rec.cma_usa_study_materials_sent else '⬜'} Study Material Preview</div>
                        </div>
                    </div>"""

            # --- 4. ACCA TRACK ---
            if any(course in names for course in ['ACCA', 'BCom + ACCA', 'MBA + ACCA']):
                html += f"""
                    <div style="font-weight:bold; color:#1e40af; margin-top:15px; border-bottom:2px solid #1e40af;">ACCA TRACK</div>
                    <div class="stage-checklist">
                        <div class="stage-column">
                            <div class="stage-title">Stage 1: Attention</div>
                            <div>{'✅' if rec.acca_short_video_sent else '⬜'} Short Video</div>
                            <div>{'✅' if rec.acca_starter_kit_sent else '⬜'} Starter Kit</div>
                            <div>{'✅' if rec.acca_webinar_invite_sent else '⬜'} Webinar Invite</div>
                        </div>
                        <div class="stage-column">
                            <div class="stage-title">Stage 2: Clarity</div>
                            <div>{'✅' if rec.acca_brochure_sent else '⬜'} Brochure</div>
                            <div>{'✅' if rec.acca_detailed_videos_sent else '⬜'} Detailed Videos</div>
                            <div>{'✅' if rec.acca_demo_class_sent else '⬜'} Demo Class</div>
                        </div>
                        <div class="stage-column">
                            <div class="stage-title">Stage 3: Trust</div>
                            <div>{'✅' if rec.acca_results_posters_sent else '⬜'} Results Posters</div>
                            <div>{'✅' if rec.acca_rank_holders_sent else '⬜'} Rank Holders List</div>
                            <div>{'✅' if rec.acca_faculty_pool_sent else '⬜'} Faculty Pool</div>
                        </div>
                    </div>
                    <div class="stage-checklist" style="margin-top:10px;">
                        <div class="stage-column">
                            <div class="stage-title">Stage 4: Proof</div>
                            <div>{'✅' if rec.acca_testimonials_sent else '⬜'} Testimonials</div>
                            <div>{'✅' if rec.acca_winners_meet_sent else '⬜'} Winners Meet Videos</div>
                        </div>
                        <div class="stage-column">
                            <div class="stage-title">Stage 5: Outcome Proof</div>
                            <div>{'✅' if rec.acca_placements_sent else '⬜'} Placements</div>
                        </div>

                        <div class="stage-column">
                            <div class="stage-title">Stage 6 & 7: Closing</div>
                            <div>{'✅' if rec.acca_value_added_sent else '⬜'} Value Added</div>
                            <div>{'✅' if rec.acca_counselling_done else '⬜'} 1-on-1 Counselling</div>
                            <div>{'✅' if rec.acca_study_materials_sent else '⬜'} Study Material Preview</div>
                        </div>
                    </div>"""
            # # --- 5. CA / CA INTER TRACK ---
            # if 'CA' in names or 'CA INTER' in names:
            #     html += f"""
            #         <div style="font-weight:bold; color:#7c3aed; margin-top:15px; border-bottom:2px solid #7c3aed;">CA / CA INTER TRACK</div>
            #         <div class="stage-checklist">
            #             <div class="stage-column">
            #                 <div class="stage-title">Stage 1</div>
            #                 <div>{'✅' if rec.first_call else '⬜'} First Call</div>
            #                 <div>{'✅' if rec.ca_roadmap_sent else '⬜'} Roadmap Sent</div>
            #             </div>
            #         </div>"""

            if not names:
                html += '<div style="text-align:center; color:#999; padding:20px;">Please select a course to see the track checklist.</div>'

            html += '</div></div>'
            rec.progress_html = html

    # Stage 1 Complete
    stage1_completed = fields.Boolean(compute='_compute_stage1_completed', store=True)

    @api.depends(
        'is_ciap_selected', 'ciap_media_sent', 'webinar_invite_sent',
        'is_cma_usa_selected', 'cma_usa_short_video_sent', 'cma_usa_starter_kit_sent', 'cma_usa_webinar_invite_sent',
        'is_acca_selected', 'acca_short_video_sent', 'acca_starter_kit_sent', 'acca_webinar_invite_sent'
    )
    def _compute_stage1_completed(self):
        for rec in self:
            if rec.is_ciap_selected:
                rec.stage1_completed = bool(rec.ciap_media_sent and rec.webinar_invite_sent)
            elif rec.is_cma_usa_selected:
                rec.stage1_completed = bool(
                    rec.cma_usa_short_video_sent and
                    rec.cma_usa_starter_kit_sent and
                    rec.cma_usa_webinar_invite_sent
                )
            elif rec.is_acca_selected:
                rec.stage1_completed = bool(
                    rec.acca_short_video_sent and
                    rec.acca_starter_kit_sent and
                    rec.acca_webinar_invite_sent
                )
            else:
                rec.stage1_completed = False

    # Stage 2 Complete
    stage2_completed = fields.Boolean(compute='_compute_stage2_completed', store=True)

    @api.depends(
        'is_ciap_selected', 'ciap_roadmap_sent', 'ciap_brochure_sent', 'detailed_ciap_video_sent',
        'ciap_demo_class_sent',
        'is_cma_usa_selected', 'cma_usa_brochure_sent', 'cma_usa_detailed_videos_sent', 'cma_usa_demo_class_sent',
        'is_acca_selected', 'acca_brochure_sent', 'acca_detailed_videos_sent', 'acca_demo_class_sent'
    )
    def _compute_stage2_completed(self):
        for rec in self:
            if rec.is_ciap_selected:
                rec.stage2_completed = all([rec.ciap_roadmap_sent, rec.ciap_brochure_sent, rec.detailed_ciap_video_sent,
                                            rec.ciap_demo_class_sent])
            elif rec.is_cma_usa_selected:
                rec.stage2_completed = all(
                    [rec.cma_usa_brochure_sent, rec.cma_usa_detailed_videos_sent, rec.cma_usa_demo_class_sent])
            elif rec.is_acca_selected:
                rec.stage2_completed = all(
                    [rec.acca_brochure_sent, rec.acca_detailed_videos_sent, rec.acca_demo_class_sent])
            else:
                rec.stage2_completed = False

    # Stage 3 Complete
    stage3_completed = fields.Boolean(compute='_compute_stage3_completed', store=True)

    @api.depends(
        'is_ciap_selected', 'ciap_faculty_pool_sent', 'ciap_value_added_videos_sent',
        'is_cma_usa_selected', 'cma_usa_results_posters_sent', 'cma_usa_rank_holders_sent', 'cma_usa_faculty_pool_sent',
        'is_acca_selected', 'acca_results_posters_sent', 'acca_rank_holders_sent', 'acca_faculty_pool_sent'
    )
    def _compute_stage3_completed(self):
        for rec in self:
            if rec.is_ciap_selected:
                rec.stage3_completed = bool(rec.ciap_faculty_pool_sent and rec.ciap_value_added_videos_sent)
            elif rec.is_cma_usa_selected:
                rec.stage3_completed = all(
                    [rec.cma_usa_results_posters_sent, rec.cma_usa_rank_holders_sent, rec.cma_usa_faculty_pool_sent])
            elif rec.is_acca_selected:
                rec.stage3_completed = all(
                    [rec.acca_results_posters_sent, rec.acca_rank_holders_sent, rec.acca_faculty_pool_sent])
            else:
                rec.stage3_completed = False

    # Stage 4 Complete
    stage4_completed = fields.Boolean(compute='_compute_stage4_completed', store=True)

    @api.depends(
        'is_ciap_selected', 'ciap_testimonials_sent', 'ciap_winners_meet_sent',
        'is_cma_usa_selected', 'cma_usa_testimonials_sent', 'cma_usa_winners_meet_sent',
        'is_acca_selected', 'acca_testimonials_sent', 'acca_winners_meet_sent'
    )
    def _compute_stage4_completed(self):
        for rec in self:
            if rec.is_ciap_selected:
                rec.stage4_completed = bool(rec.ciap_testimonials_sent and rec.ciap_winners_meet_sent)
            elif rec.is_cma_usa_selected:
                rec.stage4_completed = bool(rec.cma_usa_testimonials_sent and rec.cma_usa_winners_meet_sent)
            elif rec.is_acca_selected:
                rec.stage4_completed = bool(rec.acca_testimonials_sent and rec.acca_winners_meet_sent)
            else:
                rec.stage4_completed = False

    # Stage 5 Complete
    stage5_completed = fields.Boolean(compute='_compute_stage5_completed', store=True)

    @api.depends(
        'is_ciap_selected', 'ciap_placement_media_sent',
        'is_cma_usa_selected', 'cma_usa_placements_sent',
        'is_acca_selected', 'acca_placements_sent'
    )
    def _compute_stage5_completed(self):
        for rec in self:
            if rec.is_ciap_selected:
                rec.stage5_completed = rec.ciap_placement_media_sent
            elif rec.is_cma_usa_selected:
                rec.stage5_completed = rec.cma_usa_placements_sent
            elif rec.is_acca_selected:
                rec.stage5_completed = rec.acca_placements_sent
            else:
                rec.stage5_completed = False

    # Stage 6 Complete
    stage6_completed = fields.Boolean(compute='_compute_stage6_completed', store=True)

    @api.depends(
        'is_ciap_selected', 'ciap_starter_kit_sent', 'ciap_key_benefits_reshared',
        'is_cma_usa_selected', 'cma_usa_value_added_sent', 'cma_usa_study_materials_sent',
        'is_acca_selected', 'acca_value_added_sent', 'acca_study_materials_sent'
    )
    def _compute_stage6_completed(self):
        for rec in self:
            if rec.is_ciap_selected:
                rec.stage6_completed = bool(rec.ciap_starter_kit_sent and rec.ciap_key_benefits_reshared)
            elif rec.is_cma_usa_selected:
                rec.stage6_completed = bool(rec.cma_usa_value_added_sent and rec.cma_usa_study_materials_sent)
            elif rec.is_acca_selected:
                rec.stage6_completed = bool(rec.acca_value_added_sent and rec.acca_study_materials_sent)
            else:
                rec.stage6_completed = False

    # Stage 7 Complete
    stage7_completed = fields.Boolean(compute='_compute_stage7_completed', store=True)

    @api.depends(
        'is_ciap_selected', 'ciap_career_counselling_sent',
        'is_cma_usa_selected', 'cma_usa_counselling_done',
        'is_acca_selected', 'acca_counselling_done'
    )
    def _compute_stage7_completed(self):
        for rec in self:
            if rec.is_ciap_selected:
                rec.stage7_completed = rec.ciap_career_counselling_sent
            elif rec.is_cma_usa_selected:
                rec.stage7_completed = rec.cma_usa_counselling_done
            elif rec.is_acca_selected:
                rec.stage7_completed = rec.acca_counselling_done
            else:
                rec.stage7_completed = False

    # Stage 2 Fields and Logic
    ciap_roadmap_sent = fields.Boolean("Career Roadmap Sent")
    ciap_roadmap_sent_date = fields.Datetime(readonly=True)
    ciap_brochure_sent = fields.Boolean("Course Brochure Sent")
    ciap_brochure_sent_date = fields.Datetime(readonly=True)
    detailed_ciap_video_sent = fields.Boolean("Detailed Course Video Sent")
    detailed_ciap_video_sent_date = fields.Datetime(readonly=True)
    ciap_demo_class_sent = fields.Boolean("CIAP Free Demo Class Sent")
    ciap_demo_class_sent_date = fields.Datetime(readonly=True)

    # Stage 3 Fields and Logic
    ciap_faculty_pool_sent = fields.Boolean("CIAP Faculty Pool Sent")
    ciap_faculty_pool_sent_date = fields.Datetime(readonly=True)
    ciap_value_added_videos_sent = fields.Boolean("CIAP Value Added Programs Videos Sent")
    ciap_value_added_videos_sent_date = fields.Datetime(readonly=True)

    # Stage 4 Fields and Logic
    ciap_testimonials_sent = fields.Boolean("CIAP Student Testimonials Sent")
    ciap_testimonials_sent_date = fields.Datetime(readonly=True)
    ciap_winners_meet_sent = fields.Boolean("CIAP Winners Meet Videos Sent")
    ciap_winners_meet_sent_date = fields.Datetime(readonly=True)

    # Stage 5 Fields and Logic
    ciap_placement_media_sent = fields.Boolean("CIAP Placement Photos/Videos Sent")
    ciap_placement_media_sent_date = fields.Datetime(readonly=True)

    # Stage 6 Fields and Logic
    ciap_starter_kit_sent = fields.Boolean("CIAP Starter Kit Sent")
    ciap_starter_kit_sent_date = fields.Datetime(readonly=True)
    ciap_key_benefits_reshared = fields.Boolean("CIAP Key Benefits Re-shared")
    ciap_key_benefits_reshared_date = fields.Datetime(readonly=True)

    # Stage 7 Fields and Logic
    ciap_career_counselling_sent = fields.Boolean("CIAP Free Career Counselling Sent")
    ciap_career_counselling_sent_date = fields.Datetime(readonly=True)

    # WhatsApp Generic Sender
    def _send_whatsapp_link(self, boolean_field, date_field, message):
        self.ensure_one()
        phone = (self.phone_number or '').replace('+', '').replace(' ', '')
        if not phone:
            return
        if getattr(self, boolean_field):
            return
        whatsapp_url = "https://wa.me/%s?text=%s" % (phone, quote(message))
        self.write({boolean_field: True, date_field: fields.Datetime.now()})
        return {'type': 'ir.actions.act_url', 'url': whatsapp_url, 'target': 'new'}

    # Action Methods for Messaging
    def action_send_ciap_roadmap(self):
        return self._send_whatsapp_link(
            'ciap_roadmap_sent', 'ciap_roadmap_sent_date',
            f"Hi {self.name or ''},\n\nHere is your CIAP Career Roadmap:\nhttps://yourdomain.com/files/ciap_career_roadmap.pdf"
        )

    def action_send_ciap_brochure(self):
        return self._send_whatsapp_link(
            'ciap_brochure_sent', 'ciap_brochure_sent_date',
            f"Hi {self.name or ''},\n\nPlease find the CIAP Course Brochure:\nhttps://yourdomain.com/files/ciap_course_brochure.pdf"
        )

    def action_send_detailed_ciap_video(self):
        return self._send_whatsapp_link(
            'detailed_ciap_video_sent', 'detailed_ciap_video_sent_date',
            f"Hi {self.name or ''},\n\nPlease watch the CIAP Detailed Course Videos:\nhttps://yourdomain.com/files/ciap_detailed_course_videos"
        )

    def action_send_ciap_demo_class(self):
        return self._send_whatsapp_link(
            'ciap_demo_class_sent', 'ciap_demo_class_sent_date',
            f"Hi {self.name or ''},\n\nJoin our FREE CIAP Demo Class:\nhttps://yourdomain.com/ciap-demo-class"
        )

    def action_send_ciap_faculty_pool(self):
        return self._send_whatsapp_link(
            'ciap_faculty_pool_sent', 'ciap_faculty_pool_sent_date',
            f"Hi {self.name or ''},\n\nMeet our CIAP Faculty Pool:\nhttps://yourdomain.com/ciap-faculty-pool"
        )

    def action_send_ciap_value_added_videos(self):
        return self._send_whatsapp_link(
            'ciap_value_added_videos_sent', 'ciap_value_added_videos_sent_date',
            f"Hi {self.name or ''},\n\nWatch our CIAP Value Added Programs Videos:\nhttps://yourdomain.com/ciap-value-added-programs"
        )

    def action_send_ciap_testimonials(self):
        return self._send_whatsapp_link(
            'ciap_testimonials_sent', 'ciap_testimonials_sent_date',
            f"Hi {self.name or ''},\n\nPlease check our CIAP Student Testimonials:\nhttps://yourdomain.com/ciap-student-testimonials"
        )

    def action_send_ciap_winners_meet(self):
        return self._send_whatsapp_link(
            'ciap_winners_meet_sent', 'ciap_winners_meet_sent_date',
            f"Hi {self.name or ''},\n\nWatch our CIAP Winners Meet Videos:\nhttps://yourdomain.com/ciap-winners-meet"
        )

    def action_send_ciap_placement_media(self):
        return self._send_whatsapp_link(
            'ciap_placement_media_sent', 'ciap_placement_media_sent_date',
            f"Hi {self.name or ''},\n\nPlease check our CIAP Placement Photos and Videos:\nhttps://yourdomain.com/ciap-placement-media"
        )

    def action_send_ciap_starter_kit(self):
        return self._send_whatsapp_link(
            'ciap_starter_kit_sent', 'ciap_starter_kit_sent_date',
            f"Hi {self.name or ''},\n\nHere is your CIAP Starter Kit:\nhttps://yourdomain.com/ciap-starter-kit"
        )

    def action_reshare_ciap_key_benefits(self):
        return self._send_whatsapp_link(
            'ciap_key_benefits_reshared', 'ciap_key_benefits_reshared_date',
            f"Hi {self.name or ''},\n\nRe-sharing the key benefits of the CIAP course:\nhttps://yourdomain.com/ciap-benefits"
        )

    def action_send_ciap_career_counselling(self):
        return self._send_whatsapp_link(
            'ciap_career_counselling_sent', 'ciap_career_counselling_sent_date',
            f"Hi {self.name or ''},\n\nBook your FREE CIAP Career Counselling session:\nhttps://yourdomain.com/ciap-career-counselling"
        )

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
            "Assessment Test Link:\nhttps://yourdomain.com/ciap-assessment-test"
        )
        whatsapp_url = "https://wa.me/%s?text=%s" % (phone.replace('+', '').replace(' ', ''), quote(message))
        self.write({'ciap_assessment_test_sent': True, 'ciap_assessment_test_sent_date': fields.Datetime.now()})
        return {'type': 'ir.actions.act_url', 'url': whatsapp_url, 'target': 'new'}

    # Helper Method to avoid CMA USA redundancy
    def _send_cma_whatsapp(self, bool_field, date_field, message):
        self.ensure_one()
        phone = (self.phone_number or '').replace('+', '').replace(' ', '')
        if not phone:
            raise UserError("Lead has no phone number!")

        # Update the tracking fields
        self.write({
            bool_field: True,
            date_field: fields.Datetime.now(),
        })

        whatsapp_url = f"https://wa.me/{phone}?text={quote(message)}"
        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }

    # --- STAGE 1 BUTTONS ---
    def action_send_cma_short_video(self):
        msg = f"Hi {self.name},\n\nCheck out this short video regarding CMA USA details:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_short_video_sent', 'cma_usa_short_video_date', msg)

    def action_send_cma_starter_kit(self):
        msg = f"Hi {self.name},\n\nHere is your Free CMA USA Starter Kit to get started:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_starter_kit_sent', 'cma_usa_starter_kit_date', msg)

    def action_send_cma_webinar_invite(self):
        msg = f"Hi {self.name},\n\nYou are invited to our Free CMA USA Webinar/Demo Class. Join here:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_webinar_invite_sent', 'cma_usa_webinar_invite_date', msg)

    # --- STAGE 2 BUTTONS ---
    def action_send_cma_brochure(self):
        msg = f"Hi {self.name},\n\nPlease find the detailed CMA USA Course Brochure here:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_brochure_sent', 'cma_usa_brochure_date', msg)

    def action_send_cma_detailed_videos(self):
        msg = f"Hi {self.name},\n\nWatch these detailed videos about CMA structure and career paths:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_detailed_videos_sent', 'cma_usa_detailed_videos_date', msg)

    def action_send_cma_demo_class(self):
        msg = f"Hi {self.name},\n\nExperience our teaching style! Here is the link to a Free CMA USA Demo Class:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_demo_class_sent', 'cma_usa_demo_class_date', msg)

    # --- STAGE 3 BUTTONS ---
    def action_send_cma_results(self):
        msg = f"Hi {self.name},\n\nTake a look at our recent CMA USA results and rank holders:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_results_posters_sent', 'cma_usa_results_posters_date', msg)

    def action_send_cma_rank_holders(self):
        msg = f"Hi {self.name},\n\nCheck out our CMA USA Rank Holders and their success stories:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_rank_holders_sent', 'cma_usa_rank_holders_date', msg)

    def action_send_cma_faculty(self):
        msg = f"Hi {self.name},\n\nMeet our expert faculty pool for CMA USA:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_faculty_pool_sent', 'cma_usa_faculty_pool_date', msg)

    # --- STAGE 4 & 5 BUTTONS ---
    def action_send_cma_testimonials(self):
        msg = f"Hi {self.name},\n\nSee what our students and parents say about us:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_testimonials_sent', 'cma_usa_testimonials_date', msg)

    def action_send_cma_winners_meet(self):
        msg = f"Hi {self.name},\n\nWatch our recent Winners Meet event where we celebrate our CMA achievers:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_winners_meet_sent', 'cma_usa_winners_meet_date', msg)

    def action_send_cma_placements(self):
        msg = f"Hi {self.name},\n\nCheck out our recent CMA USA placement success stories:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_placements_sent', 'cma_usa_placements_date', msg)

    # --- STAGE 6 & 7 BUTTONS ---
    def action_send_cma_value_added(self):
        msg = f"Hi {self.name},\n\nWatch our Value Added Program videos for CMA USA:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_value_added_sent', 'cma_usa_value_added_date', msg)

    def action_send_cma_study_materials(self):
        msg = f"Hi {self.name},\n\nHere is a preview of the premium CMA USA study materials we provide:\n[Link Here]"
        return self._send_cma_whatsapp('cma_usa_study_materials_sent', 'cma_usa_study_materials_date', msg)

    def action_cma_counselling_done(self):
        msg = f"Hi {self.name},\n\nThank you for attending the career counselling session. Let's start your journey!"
        return self._send_cma_whatsapp('cma_usa_counselling_done', 'cma_usa_counselling_date', msg)

    # ACCA

    def _send_acca_whatsapp(self, bool_field, date_field, message):
        self.ensure_one()
        # Using phone_number as per your CMA logic
        phone = (self.phone_number or '').replace('+', '').replace(' ', '')
        if not phone:
            raise UserError("Lead has no phone number!")

        # Update the ACCA tracking fields
        self.write({
            bool_field: True,
            date_field: fields.Datetime.now(),
        })

        whatsapp_url = f"https://wa.me/{phone}?text={quote(message)}"
        return {
            'type': 'ir.actions.act_url',
            'url': whatsapp_url,
            'target': 'new',
        }

    # Stage 1

    def action_send_acca_short_video(self):
        msg = f"Hi {self.name},\n\nCheck out this short video regarding ACCA details and global opportunities:\n[Link Here]"
        return self._send_acca_whatsapp('acca_short_video_sent', 'acca_short_video_date', msg)

    def action_send_acca_starter_kit(self):
        msg = f"Hi {self.name},\n\nHere is your Free ACCA Starter Kit to help you plan your journey:\n[Link Here]"
        return self._send_acca_whatsapp('acca_starter_kit_sent', 'acca_starter_kit_date', msg)

    def action_send_acca_webinar_invite(self):
        msg = f"Hi {self.name},\n\nYou are invited to our Free ACCA Webinar/Demo Class. Join here:\n[Link Here]"
        return self._send_acca_whatsapp('acca_webinar_invite_sent', 'acca_webinar_invite_date', msg)

    # Stage 2

    def action_send_acca_brochure(self):
        msg = f"Hi {self.name},\n\nPlease find the detailed ACCA Course Brochure here:\n[Link Here]"
        return self._send_acca_whatsapp('acca_brochure_sent', 'acca_brochure_date', msg)

    def action_send_acca_detailed_videos(self):
        msg = f"Hi {self.name},\n\nWatch these detailed videos about ACCA papers, exemptions, and structure:\n[Link Here]"
        return self._send_acca_whatsapp('acca_detailed_videos_sent', 'acca_detailed_videos_date', msg)

    def action_send_acca_demo_class(self):
        msg = f"Hi {self.name},\n\nExperience our ACCA teaching style! Here is the link to a Free Demo Class:\n[Link Here]"
        return self._send_acca_whatsapp('acca_demo_class_sent', 'acca_demo_class_date', msg)

    # Stage 3

    def action_send_acca_results(self):
        msg = f"Hi {self.name},\n\nTake a look at our recent ACCA results and global pass rates:\n[Link Here]"
        return self._send_acca_whatsapp('acca_results_posters_sent', 'acca_results_posters_date', msg)

    def action_send_acca_rank_holders(self):
        msg = f"Hi {self.name},\n\nCheck out our ACCA Global Rank Holders and their success stories:\n[Link Here]"
        return self._send_acca_whatsapp('acca_rank_holders_sent', 'acca_rank_holders_date', msg)

    def action_send_acca_faculty(self):
        msg = f"Hi {self.name},\n\nMeet our expert faculty pool for ACCA:\n[Link Here]"
        return self._send_acca_whatsapp('acca_faculty_pool_sent', 'acca_faculty_pool_date', msg)

    # Stage 4 & 5

    def action_send_acca_testimonials(self):
        msg = f"Hi {self.name},\n\nSee what our ACCA students say about their learning experience:\n[Link Here]"
        return self._send_acca_whatsapp('acca_testimonials_sent', 'acca_testimonials_date', msg)

    def action_send_acca_winners_meet(self):
        msg = f"Hi {self.name},\n\nWatch our recent ACCA Winners Meet event where we celebrate our achievers:\n[Link Here]"
        return self._send_acca_whatsapp('acca_winners_meet_sent', 'acca_winners_meet_date', msg)

    def action_send_acca_placements(self):
        msg = f"Hi {self.name},\n\nCheck out our recent ACCA placement success stories with Big 4 firms:\n[Link Here]"
        return self._send_acca_whatsapp('acca_placements_sent', 'acca_placements_date', msg)

    # Stage 6 & 7

    def action_send_acca_value_added(self):
        msg = f"Hi {self.name},\n\nWatch our Value Added Program videos specifically for ACCA students:\n[Link Here]"
        return self._send_acca_whatsapp('acca_value_added_sent', 'acca_value_added_date', msg)

    def action_send_acca_study_materials(self):
        msg = f"Hi {self.name},\n\nHere is a preview of the ACCA Approved study materials we provide:\n[Link Here]"
        return self._send_acca_whatsapp('acca_study_materials_sent', 'acca_study_materials_date', msg)

    def action_acca_counselling_done(self):
        msg = f"Hi {self.name},\n\nThank you for attending the ACCA career counselling session. Let's start your global career!"
        return self._send_acca_whatsapp('acca_counselling_done', 'acca_counselling_date', msg)

    # Touch Point Management
    first_call = fields.Boolean(string="First Call", default=False)
    first_call_dt = fields.Datetime(string="First Call Date")
    whatsapp_intro = fields.Boolean(string="WhatsApp Intro Message", default=False)
    whatsapp_date = fields.Datetime(string="WhatsApp Date")
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
    zoom_schedule_dt = fields.Datetime(string="Zoom Schedule Date", tracking=True)
    walkin_schedule_dt = fields.Datetime(string="Walk-in Schedule Date", tracking=True)

    # Webinar Information
    webinar_invite_sent_on = fields.Datetime(string="Webinar Invite Sent On")
    webinar_invite_sent_by = fields.Many2one('res.users', string="Webinar Invite Sent By")
    webinar_zoom_link = fields.Char(string="Webinar Zoom Link")

    # Call and Meeting Wizards
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
        destination = self.phone_number.strip().replace(" ", "").replace("+", "")
        url = f"https://x.voxbay.com/api/click_to_call?id_dept=0&uid={uid}&upin={upin}&user_no={user_no}&destination={destination}&callerid={callerid}&"
        try:
            response = requests.get(url, timeout=10)
            api_status = f"HTTP {response.status_code}\nResponse: {response.text}"
            call_log = self.env["lead.call.log"].create(
                {"lead_id": self.id, "user_id": self.env.user.id, "call_time": fields.Datetime.now(),
                 "remarks": "Initiated via Voxbay"})
            wizard = self.env['voxbay.call.wizard'].create(
                {'lead_id': self.id, 'api_response': api_status, 'call_log_id': call_log.id})
            return {'name': 'Voxbay Call Status', 'type': 'ir.actions.act_window', 'res_model': 'voxbay.call.wizard',
                    'res_id': wizard.id, 'view_mode': 'form', 'target': 'new'}
        except Exception as e:
            raise UserError(f"Failed to connect to Voxbay API:\n{str(e)}")

    def action_bonvoice_call(self):
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
        destination = self.phone_number.strip().replace(" ", "").replace("+", "")
        try:
            auth_url = "https://backend.pbx.bonvoice.com/usermanagement/external-auth/"
            auth_payload = {"username": username, "password": password}
            auth_response = requests.post(auth_url, json=auth_payload, timeout=10)
            if auth_response.status_code != 200:
                raise UserError(f"Bourn Voice Auth Failed (HTTP {auth_response.status_code}):\n{auth_response.text}")
            auth_data = auth_response.json()
            if auth_data.get('status') != '1':
                raise UserError(f"Bourn Voice Auth Error:\n{auth_data.get('message', 'Unknown Error')}")
            token = auth_data.get('data', {}).get('token')
            if not token:
                raise UserError("Bourn Voice Auth Error: No token returned.")
            headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
            call_payload = {
                "autocallType": "3", "destination": agent_no, "ringStrategy": "ringall",
                "legACallerID": leg_a_cid or agent_no,
                "legAChannelID": "1", "legADialAttempts": "1", "legBDestination": destination,
                "legBCallerID": leg_b_cid or agent_no,
                "legBChannelID": "1", "legBDialAttempts": "1",
                "eventID": f"ld{self.id}{fields.Datetime.now().strftime('%M%S')}"[:16],
                "callBackParams": {"lead_id": str(self.id)[:50], "agent_id": str(self.env.user.id)[:50]}
            }
            if 'auto-call' in api_url:
                api_url = 'https://backend.pbx.bonvoice.com/autoDialManagement/autoCallBridging/'
            call_response = requests.post(api_url, json=call_payload, headers=headers, timeout=10)
            api_status = f"HTTP {call_response.status_code}\nResponse: {call_response.text}"
            call_log = self.env["lead.call.log"].create(
                {"lead_id": self.id, "user_id": self.env.user.id, "call_time": fields.Datetime.now(),
                 "remarks": "Initiated via Bourn Voice"})
            wizard = self.env['voxbay.call.wizard'].create(
                {'lead_id': self.id, 'api_response': api_status, 'call_log_id': call_log.id})
            return {'name': 'Bourn Voice Call Status', 'type': 'ir.actions.act_window',
                    'res_model': 'voxbay.call.wizard', 'res_id': wizard.id, 'view_mode': 'form', 'target': 'new'}
        except requests.exceptions.RequestException as e:
            raise UserError(f"Failed to connect to Bourn Voice API:\n{str(e)}")

    # ── Nurturing Dashboard ─────────────────────────────────────────────────
    @api.model
    def _seminar_table_exists(self):
        """True if the (optional) seminar_17 module's `seminar.leads` table
        is present in this database. custom_leads does NOT depend on
        seminar_17 — it's the other way around — so any SQL that touches
        seminar_leads must be guarded by this check first."""
        cr = self.env.cr
        cr.execute("SELECT to_regclass('public.seminar_leads') IS NOT NULL")
        return bool(cr.fetchone()[0])

    @api.model
    def get_seminar_conductors(self):
        """
        List of {id, name} for every user who has ever conducted a seminar
        (`seminar.leads.attended_by`), for the Nurturing Dashboard's
        "Seminar Conducted By" filter dropdown.

        Returns [] when the seminar_17 module isn't installed — the filter
        simply doesn't appear on the dashboard in that case.
        """
        if not self._seminar_table_exists():
            return []
        cr = self.env.cr
        # res_users has no real `name` column (it's related through
        # partner_id, not a stored table column) — get the distinct user
        # ids by plain SQL, then resolve display names via the ORM, which
        # follows that relation correctly regardless of Odoo version.
        cr.execute(
            """
            SELECT DISTINCT attended_by
            FROM   seminar_leads
            WHERE  attended_by IS NOT NULL
            """
        )
        user_ids = [row[0] for row in cr.fetchall()]
        users = self.env['res.users'].sudo().browse(user_ids).exists()
        people = [{'id': u.id, 'name': u.name} for u in users]
        people.sort(key=lambda p: (p['name'] or '').lower())
        return people

    @api.model
    def get_seminar_ids_for_conductor(self, attended_by_id):
        """
        List of `seminar.leads` ids conducted by the given user. Used
        client-side to build drill-through list-view domains (e.g.
        ['seminar_id', 'in', ids]) when the Nurturing Dashboard's "Seminar
        Conducted By" filter is active — `seminar_id` on leads.logic is a
        plain Integer (not a Many2one), so it can't be dot-traversed in an
        Odoo domain and has to be resolved to concrete ids first.
        """
        if not attended_by_id or not self._seminar_table_exists():
            return []
        cr = self.env.cr
        cr.execute("SELECT id FROM seminar_leads WHERE attended_by = %s", (attended_by_id,))
        return [row[0] for row in cr.fetchall()]

    @api.model
    def get_nurturing_dashboard_counts(self, date_from=False, date_to=False, attended_by_id=False):
        """
        Counts of leads per `student_category`, for the Nurturing Dashboard.
        The Plus One/Two and B.Com 1st-3rd Year categories count all leads
        in that segment. Meta Leads (and its Hot/Warm/Cold breakdown) counts
        Prospects-stage leads only, since that's the stage being actively
        worked for those.

        The 'Meta Leads' bucket is additionally broken down by `lead_quality`
        into Hot / Warm / Cold so telecallers can jump straight into the
        segment they need to nurture next.

        date_from / date_to: 'YYYY-MM-DD' strings, filtered on
        `date_of_adding`. Both optional — an open end means "to present".

        attended_by_id: when set, restricts everything to leads that came
        from a seminar CONDUCTED BY that user (leads_logic.seminar_id →
        seminar.leads.attended_by). Requires seminar_17 to be installed;
        silently ignored otherwise.

        Role logic mirrors get_dashboard_stage_counts(): Admission Officers
        only see their own leads; everyone else sees all leads.
        """
        cr = self.env.cr
        user = self.env.user
        table = self._table  # 'leads_logic'

        is_admission_officer = (
                user.has_group('custom_leads.group_lead_users')
                and not user.has_group('custom_leads.group_lead_team_lead')
                and not user.has_group('custom_leads.group_lead_manager')
                and not user.has_group('custom_leads.group_super_admin')
                and not user.has_group('custom_leads.group_lead_digital_head')
                and not user.has_group('custom_leads.group_lead_branch_head')
        )

        where = ["student_category IS NOT NULL"]
        args = []
        if date_from:
            where.append("date_of_adding >= %s")
            args.append(date_from)
        if date_to:
            where.append("date_of_adding <= %s")
            args.append(date_to)

        if attended_by_id and self._seminar_table_exists():
            where.append(
                "seminar_id IN (SELECT id FROM seminar_leads WHERE attended_by = %s)"
            )
            args.append(attended_by_id)

        owner_id = False
        if is_admission_officer:
            employee = user.employee_id
            if not employee:
                return {'counts': {}, 'meta_quality': {}, 'total': 0,
                        'is_admission_officer': True}
            owner_id = employee.id
            where.append("lead_owner = %s")
            args.append(owner_id)

        where_sql = " AND ".join(where)

        # ── Category counts (all stages) ─────────────────────────────────
        cr.execute(
            f"""
            SELECT student_category, COUNT(*) AS cnt
            FROM   {table}
            WHERE  {where_sql}
            GROUP  BY student_category
            """,
            args,
        )
        counts = {row[0]: row[1] for row in cr.fetchall()}

        # ── Meta Leads: Prospects-stage only, plus Hot/Warm/Cold breakdown ─
        meta_where = where_sql + " AND student_category = 'meta_leads' AND lead_stage_category = 'prospects'"
        cr.execute(
            f"""
            SELECT COUNT(*) FROM {table} WHERE {meta_where}
            """,
            args,
        )
        counts['meta_leads'] = cr.fetchone()[0]

        meta_quality_where = meta_where + " AND lead_quality IN ('hot','warm','cold')"
        cr.execute(
            f"""
            SELECT lead_quality, COUNT(*) AS cnt
            FROM   {table}
            WHERE  {meta_quality_where}
            GROUP  BY lead_quality
            """,
            args,
        )
        meta_quality = {row[0]: row[1] for row in cr.fetchall()}

        return {
            'counts': counts,
            'meta_quality': meta_quality,
            'total': sum(counts.values()),
            'is_admission_officer': is_admission_officer,
        }

    @api.model
    def recalculate_all_student_categories(self, force=False):
        """
        Bulk-backfill `student_category` for ALL leads in one shot, straight
        via SQL (no ORM loop) so it stays fast even across tens of thousands
        of records.

        force=False (default): only fills leads where student_category is
        currently empty — never touches a manually-set or already-guessed
        value. force=True: re-guesses and overwrites every lead that has a
        Lead Source or Campaign, useful after fixing a source/campaign name.

        Called from the "Backfill All" button on the Nurturing Dashboard.
        Restricted to non-Admission-Officer roles (same roles that can see
        all leads on the dashboard), since this touches every lead in the
        system, not just the caller's own.
        """
        user = self.env.user
        if not (user.has_group('custom_leads.group_lead_team_lead')
                or user.has_group('custom_leads.group_lead_manager')
                or user.has_group('custom_leads.group_super_admin')
                or user.has_group('custom_leads.group_lead_digital_head')
                or user.has_group('custom_leads.group_lead_branch_head')):
            raise UserError(_("You don't have permission to backfill all leads."))

        cr = self.env.cr
        empty_clause = "" if force else "AND l.student_category IS NULL"
        cr.execute(
            f"""
            SELECT l.id, COALESCE(s.name, '') AS source_name, COALESCE(c.name, '') AS campaign_name
            FROM   leads_logic l
            LEFT   JOIN leads_sources s ON s.id = l.leads_source
            LEFT   JOIN lead_source_campaign c ON c.id = l.source_campaign_id
            WHERE  (l.leads_source IS NOT NULL OR l.source_campaign_id IS NOT NULL)
                   {empty_clause}
            """
        )
        rows = cr.fetchall()

        buckets = {}
        for lead_id, source_name, campaign_name in rows:
            guess = self._guess_student_category(source_name, campaign_name)
            if guess:
                buckets.setdefault(guess, []).append(lead_id)

        updated = 0
        for category, ids in buckets.items():
            cr.execute(
                "UPDATE leads_logic SET student_category = %s WHERE id = ANY(%s)",
                (category, ids),
            )
            updated += len(ids)

        return {'scanned': len(rows), 'updated': updated}

    @api.model
    def get_nurturing_activity_counts(self, date_from=False, date_to=False, attended_by_id=False):
        """
        Counts how many WhatsApp / SMS exports and calls were made in the
        given date range, for the Nurturing Dashboard's activity strip.

        - WhatsApp / SMS counts come from `lead.export.history`, grouped by
          `purpose` (each row = one export batch; record_count = leads in it).
        - Calls come from the existing `lead.call.log`.

        attended_by_id: when set, restricts everything to activity on leads
        that came from a seminar CONDUCTED BY that user (same meaning as on
        get_nurturing_dashboard_counts). Requires seminar_17 to be
        installed; silently ignored otherwise. Filtering exports this way
        switches 'leads_sent' from the batch's stored record_count to an
        exact count of the leads in that batch that match the conductor,
        via the lead_ids m2m — a bit more work, only paid when this filter
        is actually used.

        Role logic mirrors the other dashboard methods: Admission Officers
        only see their own activity; everyone else sees everything.
        """
        cr = self.env.cr
        user = self.env.user

        is_admission_officer = (
                user.has_group('custom_leads.group_lead_users')
                and not user.has_group('custom_leads.group_lead_team_lead')
                and not user.has_group('custom_leads.group_lead_manager')
                and not user.has_group('custom_leads.group_super_admin')
                and not user.has_group('custom_leads.group_lead_digital_head')
                and not user.has_group('custom_leads.group_lead_branch_head')
        )

        filter_by_conductor = bool(attended_by_id) and self._seminar_table_exists()

        exp_where = ["1=1"]
        exp_args = []
        if date_from:
            exp_where.append("export_date >= %s")
            exp_args.append(date_from)
        if date_to:
            exp_where.append("export_date <= %s")
            exp_args.append(date_to + " 23:59:59")
        if is_admission_officer:
            exp_where.append("user_id = %s")
            exp_args.append(user.id)

        if filter_by_conductor:
            # lead_ids is a Many2many on lead.export.history — look up its
            # actual relation table/columns via the ORM rather than
            # hardcoding Odoo's auto-generated name.
            m2m = self.env['lead.export.history']._fields['lead_ids']
            rel_table, col_batch, col_lead = m2m.relation, m2m.column1, m2m.column2
            cr.execute(
                f"""
                SELECT eh.purpose, COUNT(DISTINCT eh.id) AS batches,
                       COUNT(DISTINCT rel.{col_lead}) AS leads_sent
                FROM   lead_export_history eh
                JOIN   {rel_table} rel ON rel.{col_batch} = eh.id
                JOIN   leads_logic l ON l.id = rel.{col_lead}
                WHERE  {" AND ".join(exp_where).replace('export_date', 'eh.export_date').replace('user_id', 'eh.user_id')}
                       AND l.seminar_id IN (SELECT id FROM seminar_leads WHERE attended_by = %s)
                GROUP  BY eh.purpose
                """,
                exp_args + [attended_by_id],
            )
        else:
            cr.execute(
                f"""
                SELECT purpose, COUNT(*) AS batches, COALESCE(SUM(record_count), 0) AS leads_sent
                FROM   lead_export_history
                WHERE  {" AND ".join(exp_where)}
                GROUP  BY purpose
                """,
                exp_args,
            )
        export_rows = {row[0]: {'batches': row[1], 'leads_sent': row[2]} for row in cr.fetchall()}

        call_where = ["1=1"]
        call_args = []
        if date_from:
            call_where.append("call_time >= %s")
            call_args.append(date_from)
        if date_to:
            call_where.append("call_time <= %s")
            call_args.append(date_to + " 23:59:59")
        if is_admission_officer:
            call_where.append("user_id = %s")
            call_args.append(user.id)
        if filter_by_conductor:
            call_where.append(
                "lead_id IN (SELECT id FROM leads_logic WHERE seminar_id IN "
                "(SELECT id FROM seminar_leads WHERE attended_by = %s))"
            )
            call_args.append(attended_by_id)

        cr.execute(
            f"""
            SELECT COUNT(*) FROM lead_call_log WHERE {" AND ".join(call_where)}
            """,
            call_args,
        )
        call_count = cr.fetchone()[0]

        return {
            'whatsapp': export_rows.get('whatsapp', {'batches': 0, 'leads_sent': 0}),
            'sms': export_rows.get('sms', {'batches': 0, 'leads_sent': 0}),
            'call_exports': export_rows.get('call', {'batches': 0, 'leads_sent': 0}),
            'calls_made': call_count,
        }

    # ── Re-Enquiry smart button ────────────────────────────────────────────
    re_enquiry_count = fields.Integer(
        string='Re-Enquiries',
        compute='_compute_re_enquiry_count',
    )

    def _compute_re_enquiry_count(self):
        for rec in self:
            rec.re_enquiry_count = self.env['lead.re.enquiry'].search_count(
                [('lead_id', '=', rec.id)]
            )

    # ── Dashboard stage counts ─────────────────────────────────────────────
    @api.model
    def get_dashboard_stage_counts(self, date_filter='month'):
        """
        Returns stage counts + per-officer breakdown + performer spotlights.

        Optimised: replaces N×search_count() ORM loops with 4 raw SQL
        GROUP BY queries so the entire dashboard loads in a single round-trip
        regardless of dataset size.

        date_filter: 'today' | 'week' | 'month' | 'all'
        Role logic:
          - Admission Officers → their own leads only
          - Everyone else → all leads
        """
        from datetime import date, timedelta

        user = self.env.user
        today = date.today()
        cr = self.env.cr

        is_admission_officer = (
                user.has_group('custom_leads.group_lead_users')
                and not user.has_group('custom_leads.group_lead_team_lead')
                and not user.has_group('custom_leads.group_lead_manager')
                and not user.has_group('custom_leads.group_super_admin')
                and not user.has_group('custom_leads.group_lead_digital_head')
                and not user.has_group('custom_leads.group_lead_branch_head')
        )

        # ── Helper: build (sql_fragment, params) for date filter ─────────
        def _date_sql(col, df):
            """Returns (WHERE clause snippet, params list) for a date filter."""
            if df == 'today':
                nxt = today + timedelta(days=1)
                return f"{col} >= %s AND {col} < %s", [str(today), str(nxt)]
            if df == 'week':
                days_since_sunday = (today.weekday() + 1) % 7
                wk_start = today - timedelta(days=days_since_sunday)
                wk_end = wk_start + timedelta(days=7)
                return f"{col} >= %s AND {col} < %s", [str(wk_start), str(wk_end)]
            if df == 'month':
                mo_start = today.replace(day=1)
                mo_end = (mo_start.replace(month=mo_start.month % 12 + 1, day=1)
                          if mo_start.month < 12
                          else mo_start.replace(year=mo_start.year + 1, month=1, day=1))
                return f"{col} >= %s AND {col} < %s", [str(mo_start), str(mo_end)]
            return "TRUE", []  # 'all'

        table = self._table  # 'leads_logic'

        # ── 1. Overall stage counts — ONE query ───────────────────────────
        owner_filter_sql = ""
        owner_filter_args = []
        if is_admission_officer:
            employee = user.employee_id
            if employee:
                owner_filter_sql = "AND lead_owner = %s"
                owner_filter_args = [employee.id]
            else:
                # No employee linked → return empty counts
                empty = {s: 0 for s in ['funnel', 'prospects', 'rnr_dnp', 'admission_done', 're_try', 'alumni', 'junk']}
                return {'counts': empty, 'is_admission_officer': True,
                        'officers': [], 'performers': {'day': None, 'week': None, 'month': None},
                        'date_filter': date_filter}

        cr.execute(
            f"""
            SELECT lead_stage_category, COUNT(*) AS cnt
            FROM   {table}
            WHERE  lead_stage_category IS NOT NULL
                   {owner_filter_sql}
            GROUP  BY lead_stage_category
            """,
            owner_filter_args,
        )
        counts = {row[0]: row[1] for row in cr.fetchall()}

        # ── 2. Per-officer breakdown — ONE query ──────────────────────────
        # NOTE: this is a *current snapshot* of leads each officer is holding
        # right now (their "in-hand" workload), so it is intentionally NOT
        # filtered by create_date — that previously caused the per-officer
        # "Total" column to show only leads created within the selected
        # period (e.g. just today's leads) while the "All Officers" footer
        # row showed lifetime totals, making the numbers look inconsistent.
        # Only currently active employees are included (resigned/inactive
        # staff are excluded).
        officers_data = []
        performers = {'day': None, 'week': None, 'month': None}

        if not is_admission_officer:
            cr.execute(
                f"""
                SELECT e.id          AS emp_id,
                       e.name        AS emp_name,
                       l.lead_stage_category,
                       COUNT(*)      AS cnt
                FROM   {table} l
                JOIN   hr_employee e ON e.id = l.lead_owner
                WHERE  l.lead_owner IS NOT NULL
                       AND l.lead_stage_category IS NOT NULL
                       AND e.active = TRUE
                GROUP  BY e.id, e.name, l.lead_stage_category
                ORDER  BY e.name
                """
            )
            rows = cr.fetchall()

            # Aggregate into per-officer dict
            emp_map = {}  # emp_id -> {id, name, counts, total, calls}
            emp_order = []
            for emp_id, emp_name, stage, cnt in rows:
                if emp_id not in emp_map:
                    emp_map[emp_id] = {'id': emp_id, 'name': emp_name,
                                       'counts': {}, 'total': 0, 'calls': 0}
                    emp_order.append(emp_id)
                emp_map[emp_id]['counts'][stage] = cnt
                emp_map[emp_id]['total'] += cnt

            # ── 2b. Calls made per officer — respects the date filter ─────
            # This is where the Today / This Week / This Month / All Time
            # tabs are actually meaningful: how many calls did each (active)
            # officer log in that period.
            call_date_sql, call_date_args = _date_sql("cl.call_time", date_filter)
            cr.execute(
                f"""
                SELECT e.id AS emp_id, COUNT(*) AS cnt
                FROM   lead_call_log cl
                JOIN   hr_employee e ON e.user_id = cl.user_id
                WHERE  e.active = TRUE
                       AND {call_date_sql}
                GROUP  BY e.id
                """,
                call_date_args,
            )
            for emp_id, cnt in cr.fetchall():
                if emp_id not in emp_map:
                    # Officer made calls in this period but currently has no
                    # leads assigned — still show them so the call activity
                    # isn't silently dropped.
                    emp_map[emp_id] = {'id': emp_id, 'name': None,
                                       'counts': {}, 'total': 0, 'calls': 0}
                    emp_order.append(emp_id)
                emp_map[emp_id]['calls'] = cnt

            # Fill in names for any call-only entries picked up above
            missing_names = [eid for eid in emp_order if emp_map[eid]['name'] is None]
            if missing_names:
                for emp in self.env['hr.employee'].sudo().browse(missing_names):
                    if emp.id in emp_map:
                        emp_map[emp.id]['name'] = emp.name

            officers_data = sorted(
                (emp_map[eid] for eid in emp_order),
                key=lambda o: (o['name'] or '').lower()
            )

            # ── 3. Performers: best admission count per period — ONE query ─
            # Pull (emp_id, emp_name, period_label, count) for all three
            # windows in a single SQL CASE/GROUP BY.
            today_str = str(today)
            tmrw_str = str(today + timedelta(days=1))
            days_sun = (today.weekday() + 1) % 7
            wk_start_str = str(today - timedelta(days=days_sun))
            wk_end_str = str(today - timedelta(days=days_sun) + timedelta(days=7))
            mo_start = today.replace(day=1)
            mo_end = (mo_start.replace(month=mo_start.month % 12 + 1, day=1)
                      if mo_start.month < 12
                      else mo_start.replace(year=mo_start.year + 1, month=1, day=1))
            mo_start_str = str(mo_start)
            mo_end_str = str(mo_end)

            cr.execute(
                f"""
                SELECT e.id,
                       e.name,
                       CASE
                           WHEN l.admission_date >= %s AND l.admission_date < %s THEN 'day'
                           WHEN l.admission_date >= %s AND l.admission_date < %s THEN 'week'
                           WHEN l.admission_date >= %s AND l.admission_date < %s THEN 'month'
                       END AS period,
                       COUNT(*) AS cnt
                FROM   {table} l
                JOIN   hr_employee e ON e.id = l.lead_owner
                WHERE  l.lead_stage_category = 'admission_done'
                       AND l.admission_date IS NOT NULL
                       AND l.lead_owner IS NOT NULL
                       AND e.active = TRUE
                       AND l.admission_date >= %s
                       AND l.admission_date  < %s
                GROUP  BY e.id, e.name, period
                HAVING COUNT(*) > 0
                ORDER  BY cnt DESC
                """,
                [
                    today_str, tmrw_str,  # day
                    wk_start_str, wk_end_str,  # week
                    mo_start_str, mo_end_str,  # month
                    mo_start_str, tmrw_str,  # outer filter (month start → tomorrow covers all)
                ],
            )
            perf_rows = cr.fetchall()

            # Keep only the top performer per period
            for emp_id, emp_name, period, cnt in perf_rows:
                if period and performers.get(period) is None:
                    performers[period] = {'id': emp_id, 'name': emp_name, 'count': cnt}

        return {
            'counts': counts,
            'is_admission_officer': is_admission_officer,
            'officers': officers_data,
            'performers': performers,
            'date_filter': date_filter,
        }

    def action_open_re_enquiries(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Re-Enquiries'),
            'res_model': 'lead.re.enquiry',
            'view_mode': 'tree,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {'default_lead_id': self.id},
        }

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

    def action_send_whatsapp_intro(self):
        for record in self:
            if not record.phone_number:
                raise UserError("Phone number is missing!")
            full_phone = record.phone_number.strip().replace(" ", "")
            record.whatsapp_intro = True
            record.whatsapp_date = fields.Datetime.now()
            url = "https://backend.aisensy.com/campaign/t1/api/v2"
            payload = {
                "apiKey": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY1ZDQyYWJkNDM0ZTE5MTUyNTdkMDc2YSIsIm5hbWUiOiJMb2dpYyBTY2hvb2wgb2YgTWFuYWdlbWVudCA4ODkxIiwiYXBwTmFtZSI6IkFpU2Vuc3kiLCJjbGllbnRJZCI6IjY1ZDQyYWJkNDM0ZTE5MTUyNTdkMDc2NSIsImFjdGl2ZVBsYW4iOiJQUk9fTU9OVEhMWSIsImlhdCI6MTc0Mzc2NTk4NX0.9PwksixkBDCbN6CNjjBAOgRUqsM3wXfnR9OwacEO2Xo",
                "campaignName": "odoo17test",
                "destination": full_phone,
                "userName": record.name or "",
            }
            try:
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code != 200:
                    raise UserError(f"WhatsApp API error: {response.status_code}\n{response.text}")
            except Exception as e:
                raise UserError(f"Failed to send WhatsApp message:\n{str(e)}")
            record.message_post(body=f"📩 WhatsApp intro sent to {full_phone} via AiSensy")
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_send_results_highlights(self):
        for record in self:
            record.results_highlights = True
            record.message_post(body="Results Highlight sent.")
        return None

    def action_second_followup(self):
        for record in self:
            record.second_followup = True
            record.second_followup_dt = fields.Datetime.now()
            record.message_post(body="Second Follow Up Completed.")
        return None

    def action_add_call_log(self):
        for record in self:
            self.env["lead.call.log"].create(
                {"lead_id": record.id, "user_id": self.env.user.id, "call_time": fields.Datetime.now()})
            record.message_post(
                body=f"📞 Call logged by {self.env.user.name} on {fields.Datetime.now().strftime('%d-%m-%Y %H:%M:%S')}")

    def action_add_followup(self):
        for record in self:
            if not record.id:
                raise UserError("Please save the lead before adding a follow-up.")
        return {
            'name': 'Add Follow-Up',
            'type': 'ir.actions.act_window',
            'res_model': 'lead.followup.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_id': record.id, 'default_phone_number': record.phone_number},
        }

    def action_view_fee_structure(self):
        return {'name': 'Course Fee Structure', 'type': 'ir.actions.act_window', 'res_model': 'course.fee.structure',
                'view_mode': 'tree', 'target': 'new'}

    @api.onchange('call_response')
    def _onchange_call_response(self):
        for record in self:
            if record.call_response:
                response_obj = self.env['call.responses'].search([('name', '=', record.call_response)], limit=1)
                if not response_obj:
                    response_obj = self.env['call.responses'].create({'name': record.call_response})
                record.call_responses = [(4, response_obj.id)]

    @api.onchange('leads_source')
    def _onchange_leads_source(self):
        if self.leads_source:
            self.source_name = self.leads_source.name
            if 'incoming' in self.source_name.lower() or 'walk in' in self.source_name.lower():
                self.incoming_source_checking = True
            else:
                self.incoming_source_checking = 0
                self.incoming_source = False
            if self.leads_source.digital_lead == 1:
                self.digital_lead = 1
            else:
                self.digital_lead = 0
                self.digital_lead_source = False
            # Lead Source is the PARENT (e.g. "Digital"). If the currently
            # selected Source Campaign no longer belongs to this Lead
            # Source, clear it so stale parent/child combinations can't be
            # saved (e.g. switching Lead Source from "Digital" to
            # "Offline" while "Urban Chat Leads Meta" is still selected).
            if self.source_campaign_id and self.source_campaign_id.lead_source_id != self.leads_source:
                self.source_campaign_id = False

    @api.onchange('source_campaign_id')
    def _onchange_source_campaign_id(self):
        # Source Campaign is the CHILD (e.g. "Urban Chat Leads Meta").
        # Picking it auto-fills its parent Lead Source (e.g. "Digital") —
        # so the user only has to pick the Campaign and Lead Source fills
        # itself in.
        if self.source_campaign_id and self.source_campaign_id.lead_source_id:
            if self.leads_source != self.source_campaign_id.lead_source_id:
                self.leads_source = self.source_campaign_id.lead_source_id

    def get_current_student_profile(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Student', 'view_mode': 'tree,form', 'res_model': 'op.student',
                'domain': [('id', '=', self.student_id.id)], 'context': "{'create': False}"}

    def compute_count_student(self):
        for record in self:
            record.student_smart_count = self.env['op.student'].sudo().search_count([('id', '=', self.student_id.id)])

    student_smart_count = fields.Integer(compute='compute_count_student')

    def get_phone_number_for_whatsapp(self):
        for rec in self:
            if rec.phone_number:
                rec.sample = "https://web.whatsapp.com/send?phone=" + rec.phone_number or "https://api.whatsapp.com/send?phone=" + rec.phone_number
            else:
                rec.sample = ''

    def whatsapp_click_button(self):
        return {'type': 'ir.actions.act_url', 'name': "Leads Whatsapp", 'target': 'new', 'url': self.sample}

    batch_id = fields.Many2one('op.batch', string="Batch",
                               domain="[('branch', '=', branch_id),('total_lump_sum_fee', '!=', 0)]")
    batch_fee = fields.Float(string="Expected Revenue", related="batch_id.lump_fee_excluding_tax")

    def act_call_back(self):
        return {'type': 'ir.actions.act_window', 'name': _('Connect'), 'res_model': 'connect.form', 'target': 'new',
                'view_mode': 'form',
                'context': {'default_lead_id': self.id, 'default_task_owner_id': self.lead_owner.user_id.id}}

    @api.depends('lead_owner')
    def _compute_lead_owner(self):
        if self.lead_owner:
            self.assigned_date = fields.Datetime.now()

    @api.onchange('phone_number')
    def _onchange_duplicate_phone_number(self):
        for record in self:
            if record.phone_number:
                last_10_digits = record.phone_number[-10:]
                duplicate = self.sudo().search(
                    [('phone_number', 'like', '%' + last_10_digits), ('id', '!=', self._origin.id)])
                if duplicate:
                    lead_owner_name = duplicate[0].lead_owner.name if duplicate[0].lead_owner else 'Unknown'
                    return {'warning': {'title': _("Duplicate Phone Number"), 'message': _(
                        "The phone number %s already exists in the system and is owned by %s.") % (record.phone_number,
                                                                                                   lead_owner_name)}}

    admission_fee_paid = fields.Boolean(string="Admission Fee Paid")
    re_allocation_date = fields.Date(string="Re Allocation Date")

    def create_invoice(self):
        return {'type': 'ir.actions.act_window', 'name': _('Create Invoice'), 'res_model': 'fee.collection.wizard',
                'target': 'new', 'view_mode': 'form', 'view_type': 'form',
                'context': {'default_collection_id': self.student_id.id, 'default_fee_type': 'Other Fee',
                            'default_other_fee': 'Admission Fee',
                            'default_wallet_amount': self.student_id.wallet_balance,
                            'default_fee_plan': self.student_id.fee_type,
                            'default_amount_inc_tax': self.batch_id.admission_fee}}

    def act_attempt_to_connect(self):
        for record in self:
            record.state = 'in_progress'
            record.first_call_dt = fields.Datetime.now()
            record.first_call = True
            record.lead_quality = 'first_attempt'

    def act_connected(self):
        return {'type': 'ir.actions.act_window', 'name': _('Connect'), 'res_model': 'connect.form', 'target': 'new',
                'view_mode': 'form',
                'context': {'default_lead_id': self.id, 'default_task_owner_id': self.lead_owner.user_id.id}}

    def act_not_connected(self):
        return {'type': 'ir.actions.act_window', 'name': _('Connect'), 'res_model': 'not.connect.form', 'target': 'new',
                'view_mode': 'form', 'view_type': 'form', 'context': {'default_lead_id': self.id}}

    @api.onchange('name', 'phone_number', 'call_response', 'leads_source', 'lead_quality', 'admission_status',
                  'lead_owner', 'assign_to', 'course_id', 'batch_id', 'branch_id',
                  'course_inter', 'next_follow_up_date')
    def _onchange_updated_date(self):
        if self.batch_id:
            self.course_id = self.batch_id.course_id.id
            self.branch_id = self.batch_id.branch.id
        if self:
            self.last_update_date = datetime.now()
        if self.lead_quality == 'waiting_for_admission':
            raise ValidationError(
                "⚠️ Please complete the 'Waiting for Admission Payment' form before setting status to 'Waiting for Admission'.")
        if self.lead_quality == 'admission':
            if self.admission_status == 0:
                raise ValidationError(
                    "⚠️ First, you need to transfer to 'Waiting for Admission Payment.' After the admission fee is paid, you can transfer to 'Admission'.")
        if self.lead_quality == 'crash_lead':
            if self.crash_lead == 0:
                raise ValidationError(
                    "This lead is about to be transferred to the Crash Team. Are you sure you want to proceed with this action? Please enable 'Crash Lead' before proceeding with this action ")

    @api.constrains('course_inter', 'next_follow_up_date', 'lead_quality')
    def _check_course_and_followup_required(self):
        # Super Admin bulk quality-change wizard deliberately overrides this
        # check (see lead.quality.bulk.wizard.action_apply) — the wizard
        # itself is group-restricted, so this flag is not a general bypass.
        if self.env.context.get('skip_lead_quality_validation'):
            return
        # Course Interested In + Follow-Up are required for all statuses EXCEPT these terminal/junk ones
        _FOLLOWUP_EXEMPT = {
            'already_joined', 'admission', 'waiting_for_admission',
            'bad_lead', 'crash_lead', 'joined_other_institute',
            'wrong_number', 'not_enquiry',
            'new',  # exempt 'new' so a fresh lead can be saved without course
        }
        for rec in self:
            if rec.lead_quality and rec.lead_quality not in _FOLLOWUP_EXEMPT:
                if not rec.course_inter:
                    raise ValidationError(
                        "⚠️ 'Course Interested In' is required. Please select at least one course before saving."
                    )
                if not rec.next_follow_up_date and not rec.followup_ids:
                    raise ValidationError(
                        "⚠️ A Follow-Up date is required for this lead. "
                        "Please set a 'Next Follow Up Date' or add a follow-up entry before saving."
                    )

    def act_lost_lead(self):
        return {'type': 'ir.actions.act_window', 'name': _('Lost'), 'res_model': 'lost.lead.form', 'target': 'new',
                'view_mode': 'form', 'view_type': 'form', 'context': {'default_lead_id': self.id}}

    def act_convert(self):
        if self.batch_id and self.branch_id and self.course_id:
            return {'type': 'ir.actions.act_window', 'name': _('Deal'), 'res_model': 'convert.lead', 'target': 'new',
                    'view_mode': 'form', 'view_type': 'form',
                    'context': {'default_lead_id': self.id, 'default_lead_owner_id': self.lead_owner.user_id.id}}
        else:
            raise UserError(_('Please ensure that Batch, Branch, and Course are selected before proceeding.'))

    def act_admission(self):
        if self.batch_id.name != 'Nil':
            if self.batch_id and self.branch_id and self.course_id:
                return {'type': 'ir.actions.act_window', 'name': _('Admission'), 'res_model': 'qualified.lead.form',
                        'target': 'new', 'view_mode': 'form', 'view_type': 'form',
                        'context': {'default_lead_id': self.id, 'default_batch_id': self.batch_id.id,
                                    'default_course_id': self.course_id.id, 'default_branch_id': self.branch_id.id,
                                    'default_mobile': self.phone_number, 'default_email': self.email_address}}
            else:
                raise UserError(_('Please ensure that Batch, Branch, and Course are selected before proceeding.'))
        else:
            raise UserError(_('Nil batch is not allowed. Please select a valid batch.'))

    def act_transfer_to_waiting_for_admission(self):
        self.lead_quality = 'waiting_for_admission'

    def act_return_to_new_lead(self):
        self.state = 'new'

    def act_re_allocation_leads(self):
        selected_ids = self.env.context.get('active_ids', [])
        return {'type': 'ir.actions.act_window', 'name': _('Re Allocation'), 'res_model': 're.allocation.leads',
                'target': 'new', 'view_mode': 'form', 'view_type': 'form',
                'context': {'default_leads_ids': [(6, 0, selected_ids)]}}

    @api.model
    def create(self, values):
        # ── Duplicate detection: same mobile + same academic year → Re-Enquiry ──
        # Both ValidationError and UserError trigger a full PostgreSQL transaction
        # rollback — savepoints inside the same transaction are rolled back too.
        # Solution: open a SEPARATE database cursor (independent transaction)
        # to write the re-enquiry, commit it, then raise UserError in the
        # original cursor. The separate cursor's commit is unaffected by the
        # rollback of the original request transaction.
        phone_raw = (values.get('phone_number') or '').replace(' ', '')
        academic_year = values.get('academic_year_of_course_attend', '2025-2026')

        if phone_raw and academic_year:
            last_10 = phone_raw[-10:]
            existing = self.sudo().search([
                ('phone_number', 'like', '%' + last_10),
                ('academic_year_of_course_attend', '=', academic_year),
            ], limit=1)
            if existing:
                re_vals = {
                    'lead_id': existing.id,
                    'review_required': True,
                    'review_state': 'pending',
                }
                for fld in ('leads_source', 'campaign', 'digital_lead_source',
                            'course_interested', 'remarks'):
                    if values.get(fld):
                        re_vals[fld] = values[fld]

                owner_name = existing.lead_owner.name if existing.lead_owner else _('Unknown')
                re_ref = _('New')

                # Open a fresh cursor — completely separate DB transaction.
                # This commit survives the UserError rollback below.
                try:
                    registry = self.env.registry
                    with registry.cursor() as new_cr:
                        new_env = api.Environment(new_cr, self.env.uid, self.env.context)
                        re_enquiry = new_env['lead.re.enquiry'].sudo().create(re_vals)
                        re_ref = re_enquiry.reference_no
                        new_cr.commit()
                except Exception as e:
                    _logger.error('Re-Enquiry creation failed: %s', e)

                raise UserError(
                    _(
                        "Duplicate Mobile Detected!\n\n"
                        "The number %(phone)s already has a lead in %(year)s, "
                        "assigned to %(officer)s.\n\n"
                        "Re-Enquiry %(re_ref)s has been created and the "
                        "Team Lead has been notified.\n\n"
                        "No new lead was created."
                    ) % {
                        'phone': phone_raw,
                        'year': academic_year,
                        'officer': owner_name,
                        're_ref': re_ref,
                    }
                )

        # ── Normal creation ────────────────────────────────────────────────
        if values.get('reference_no', _('New')) == _('New'):
            values['reference_no'] = self.env['ir.sequence'].next_by_code('leads.logic') or _('New')
        if 'phone_number' in values:
            values['phone_number'] = values['phone_number'].replace(" ", "")
        if values.get('source_campaign_id') and not values.get('leads_source'):
            campaign = self.env['lead.source.campaign'].browse(values['source_campaign_id'])
            if campaign.lead_source_id:
                values['leads_source'] = campaign.lead_source_id.id
        # ── Auto student_category from Lead Source / Campaign name ─────────
        if not values.get('student_category'):
            src_name = ''
            camp_name = ''
            if values.get('leads_source'):
                src_name = self.env['leads.sources'].browse(values['leads_source']).name or ''
            if values.get('source_campaign_id'):
                camp_name = self.env['lead.source.campaign'].browse(values['source_campaign_id']).name or ''
            guess = self._guess_student_category(src_name, camp_name)
            if guess:
                values['student_category'] = guess
        lead = super(LeadsForm, self).create(values)
        if lead.lead_owner:
            self.env['lead.assignment.history'].create(
                {'lead_id': lead.id, 'owner_id': lead.lead_owner.id, 'assigned_date': fields.Datetime.now(),
                 'assigned_by': self.env.uid})
        if lead.tele_caller_id:
            notification_ids = [
                (0, 0, {'res_partner_id': lead.tele_caller_id.partner_id.id, 'notification_type': 'inbox'})]
            self.env['mail.message'].create(
                {'message_type': "notification", 'body': f"Lead '{lead.name}' has been assigned to you.",
                 'subject': "Lead Assigned", 'model': 'leads.logic', 'res_id': lead.id,
                 'partner_ids': [(4, lead.tele_caller_id.partner_id.id)], 'author_id': self.env.user.partner_id.id,
                 'notification_ids': notification_ids})
        return lead

    updated_remarks = fields.Text(string="Updated Remarks")
    truncated_call_response = fields.Char(string="Truncated Response", compute="_compute_truncated_response")

    def act_print_invoice(self):
        return self.env.ref('custom_leads.action_report_lead_payment_history_receipt').report_action(self)

    def _compute_truncated_response(self):
        for record in self:
            record.truncated_call_response = ((record.call_response[:20] + "...") if record.call_response else "")

    is_team_leader = fields.Boolean(compute="_compute_team_leader")

    @api.depends()
    def _compute_team_leader(self):
        for record in self:
            record.is_team_leader = self.env.user.has_group('custom_leads.group_lead_team_lead')

    #

    def action_bulk_lead_allocation_tele_callers(self):
        active_ids = self.env.context.get('active_ids', [])
        return {'type': 'ir.actions.act_window', 'name': 'Allocation', 'res_model': 'allocation.tele_callers.wizard',
                'view_mode': 'form', 'view_type': 'form', 'target': 'new', 'context': {'parent_obj': active_ids}}

    #     Lead Export History

    def export_data(self, fields_to_export):
        # 1. Get the IP address
        ip_addr = 'Unknown'
        if request:
            ip_addr = request.httprequest.remote_addr

        # 2. Log the export activity
        self.env['lead.export.history'].sudo().create({
            'user_id': self.env.user.id,
            'export_date': fields.Datetime.now(),
            'record_count': len(self),
            'exported_fields': ", ".join(fields_to_export),
            'ip_address': ip_addr,
            'purpose': 'other',
            'lead_ids': [(6, 0, self.ids)],
        })

        # 3. Post a note to the chatter of each exported lead (Optional)
        for record in self:
            record.message_post(body=f"⚠️ This lead was exported by {self.env.user.name} on {fields.Datetime.now()}")

        # 4. Carry out the actual export
        return super(LeadsForm, self).export_data(fields_to_export)

    is_forwarded = fields.Boolean(string="Forwarded", default=False, tracking=True)

    def action_forward_lead(self):
        for rec in self:
            rec.is_forwarded = True

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, access_rights_uid=None):
        if self.env.context.get('skip_leads_logic_search_override'):
            return super()._search(
                domain,
                offset=offset,
                limit=limit,
                order=order,
                access_rights_uid=access_rights_uid,
            )

        # referral_search context: fully bypass ir.rule by switching to a superuser
        # env and calling the BASE _search directly — not our override — to avoid
        # infinite recursion.
        if self.env.context.get('referral_search'):
            sudo_model = self.sudo().with_context(skip_leads_logic_search_override=True)
            return sudo_model._search(
                domain,
                offset=offset,
                limit=limit,
                order=order,
                access_rights_uid=access_rights_uid,
            )

        # Restrict Admission Officers to only their own leads in all other views.
        # Team Leads are excluded — they see their team's leads via ir.rule instead.
        if self.env.user.has_group('custom_leads.group_lead_users') and not (
                self.env.user.has_group('custom_leads.group_super_admin') or
                self.env.user.has_group('custom_leads.group_lead_manager') or
                self.env.user.has_group('custom_leads.group_lead_branch_head') or
                self.env.user.has_group('custom_leads.group_lead_digital_head') or
                self.env.user.has_group('custom_leads.group_lead_team_lead')
        ):
            from odoo.osv import expression
            domain = expression.AND([
                [
                    '|', '|', '|',
                    ('lead_owner', '=', self.env.user.employee_id.id),
                    ('tele_caller_id', '=', self.env.user.id),
                    ('create_uid', '=', self.env.user.id),
                    ('followup_ids.user_id', '=', self.env.user.id),
                ],
                domain
            ])
        return super()._search(domain, offset=offset, limit=limit, order=order, access_rights_uid=access_rights_uid)


# --------------------------------------------------------------------------
# Model: call.responses
# Description: Stores unique call response texts.
# --------------------------------------------------------------------------
class CallResponses(models.Model):
    _name = "call.responses"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Text(string="Call Responses")


# --------------------------------------------------------------------------
# Model: lead.response
# Description: Tracks specific comments and responses from users on a lead.
# --------------------------------------------------------------------------
class LeadResponse(models.Model):
    _name = 'lead.response'
    _description = 'Lead Comments / Responses'
    _rec_name = 'comment'
    _order = 'response_time desc'

    lead_id = fields.Many2one('leads.logic', string="Lead", ondelete='cascade')
    user_id = fields.Many2one('res.users', string="Responded By", default=lambda self: self.env.user)
    comment = fields.Text(string="Response / Comment", required=True)
    response_time = fields.Datetime(string="Response Time", default=fields.Datetime.now)
    is_editable = fields.Boolean(string="Editable", default=False)

    @api.model_create_multi
    def create(self, vals_list):
        records = super(LeadResponse, self).create(vals_list)
        for record in records:
            if record.lead_id and record.comment:
                safe_comment = html_escape(record.comment)

                # Using Markup() ensures Odoo renders the bold and line breaks
                message = Markup(
                    "<div>"
                    "<strong>💬 New Response Added</strong><br/>"
                    "<strong>By:</strong> %s<br/>"
                    "<strong>Comment:</strong> %s"
                    "</div>"
                ) % (record.user_id.name, safe_comment)

                record.lead_id.message_post(
                    body=message,
                    subtype_xmlid="mail.mt_note"
                )
        return records

    def write(self, vals):
        old_comments = {r.id: r.comment for r in self} if 'comment' in vals else {}
        res = super(LeadResponse, self).write(vals)
        if 'comment' in vals:
            for record in self:
                old_comment = old_comments.get(record.id)
                if old_comment != record.comment and record.lead_id:
                    safe_old = html_escape(old_comment or '')
                    safe_new = html_escape(record.comment or '')
                    message = Markup(
                        "<div>"
                        "<strong>✏️ Response Updated</strong><br/>"
                        "<strong>By:</strong> %s<br/>"
                        "<strong>Before:</strong> %s<br/>"
                        "<strong>After:</strong> %s"
                        "</div>"
                    ) % (self.env.user.name, safe_old, safe_new)
                    record.lead_id.message_post(
                        body=message,
                        subtype_xmlid="mail.mt_note"
                    )
        if 'is_editable' not in vals:
            self.is_editable = False
        return res

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


# --------------------------------------------------------------------------
# Model: course.interested
# Description: Simple model to list courses a lead is interested in.
# --------------------------------------------------------------------------
class CourseInterested(models.Model):
    _name = "course.interested"

    name = fields.Char(string="Course Name")


# --------------------------------------------------------------------------
# Model: lead.call.log
# Description: Detailed log of calls initiated via third-party APIs.
# --------------------------------------------------------------------------
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

    @api.model
    def get_call_performance_counts(self, date_from=False, date_to=False):
        """
        Per-agent call activity for the Call Records OWL dashboard: total
        calls, incoming/outgoing split, and answered/no-answer split.

        date_from / date_to: 'YYYY-MM-DD' strings filtered on `call_time`.
        Both optional — leaving both blank shows all-time totals.
        """
        cr = self.env.cr
        where = ["user_id IS NOT NULL"]
        args = []
        if date_from:
            where.append("call_time >= %s")
            args.append(date_from)
        if date_to:
            where.append("call_time <= %s")
            args.append(date_to + " 23:59:59")
        where_sql = " AND ".join(where)

        cr.execute(
            f"""
            SELECT user_id,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE call_type = 'incoming') AS incoming,
                   COUNT(*) FILTER (WHERE call_type = 'outgoing') AS outgoing,
                   COUNT(*) FILTER (WHERE call_status ILIKE 'answer%%') AS answered,
                   COUNT(*) FILTER (WHERE call_status NOT ILIKE 'answer%%' OR call_status IS NULL) AS not_answered
            FROM   lead_call_log
            WHERE  {where_sql}
            GROUP  BY user_id
            ORDER  BY total DESC
            """,
            args,
        )
        rows = cr.fetchall()
        users = self.env['res.users'].sudo().browse([r[0] for r in rows])
        names = {u.id: u.name for u in users}

        agents = []
        totals = {'total': 0, 'incoming': 0, 'outgoing': 0, 'answered': 0, 'not_answered': 0}
        for user_id, total, incoming, outgoing, answered, not_answered in rows:
            totals['total'] += total
            totals['incoming'] += incoming
            totals['outgoing'] += outgoing
            totals['answered'] += answered
            totals['not_answered'] += not_answered
            agents.append({
                'user_id': user_id,
                'name': names.get(user_id, 'Unknown'),
                'total': total,
                'incoming': incoming,
                'outgoing': outgoing,
                'answered': answered,
                'not_answered': not_answered,
            })

        return {'agents': agents, 'totals': totals}


# --------------------------------------------------------------------------
# Model: lead.followup
# Description: Scheduled and logged follow-up tasks for leads.
# --------------------------------------------------------------------------
class LeadFollowUp(models.Model):
    _name = "lead.followup"
    _description = "Lead Follow-Up"
    _order = 'status desc, next_followup_date asc'

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

    @api.model
    def _cron_remind_upcoming_followups(self):
        now = fields.Datetime.now()
        upcoming = now + timedelta(hours=1)
        followups = self.search(
            [('next_followup_date', '>=', now), ('next_followup_date', '<=', upcoming), ('status', '=', 'scheduled')])
        for followup in followups:
            if followup.lead_id:
                followup_time = _format_user_datetime(followup, followup.next_followup_date)
                followup.lead_id.message_post(
                    body=f"Reminder: Follow-up due on {followup_time} for {followup.user_id.name}.")
                self.env['mail.activity'].create({
                    'res_model': 'leads.logic', 'res_id': followup.lead_id.id, 'user_id': followup.user_id.id,
                    'summary': 'Follow-Up Reminder',
                    'note': f"Upcoming follow-up scheduled at {followup_time}",
                    'date_deadline': fields.Datetime.context_timestamp(followup, followup.next_followup_date).date(),
                })

    def action_mark_done(self):
        """Mark follow-up as done"""
        for record in self:
            record.status = 'done'
            if record.lead_id:
                followup_time = _format_user_datetime(record, record.next_followup_date)
                record.lead_id.message_post(
                    body=f"✅ Follow-up marked as Done by {self.env.user.name} "
                         f"(Scheduled: {followup_time})"
                )


# --------------------------------------------------------------------------
# Model: lead.followup.wizard
# Description: Wizard to capture follow-up details and schedule activities.
# --------------------------------------------------------------------------
class LeadFollowUpWizard(models.TransientModel):
    _name = "lead.followup.wizard"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Add Follow-Up Wizard"

    next_followup_date = fields.Datetime(string="Next Follow-Up Date", required=True)
    remarks = fields.Text(string="Remarks")

    def action_save_followup(self):
        active_id = self.env.context.get('active_id')
        if not active_id:
            return
        lead = self.env['leads.logic'].browse(active_id)
        self.env['lead.followup'].create(
            {'lead_id': lead.id, 'user_id': self.env.user.id, 'next_followup_date': self.next_followup_date,
             'remarks': self.remarks, 'status': 'scheduled'})
        followup_time = _format_user_datetime(self, self.next_followup_date)
        lead.message_post(
            body=f"New follow-up added on {followup_time} by {self.env.user.name}:<br/>{self.remarks}")
        self.env['mail.activity'].create({
            'res_model_id': self.env['ir.model']._get_id('leads.logic'), 'res_id': lead.id, 'user_id': self.env.user.id,
            'summary': 'Follow-Up Reminder',
            'note': f'Remind yourself to follow up on: {followup_time}',
            'date_deadline': fields.Datetime.context_timestamp(self, self.next_followup_date).date(),
        })
        return {'type': 'ir.actions.act_window_close'}


# --------------------------------------------------------------------------
# Model: course.fee.structure
# Description: Information about course levels, duration, and associated fees.
# --------------------------------------------------------------------------
class CourseFeeStructure(models.Model):
    _name = 'course.fee.structure'
    _description = 'Course Fee Structure'

    course_name = fields.Char(string="Course Name")
    level = fields.Char(string="Level")
    duration = fields.Char(string="Duration")
    amount = fields.Float(string="Fees (INR)")
    image = fields.Binary(string="Course Image", attachment=True)


# --------------------------------------------------------------------------
# Model: lead.unlock.wizard
# Description: Wizard used to toggle the is_editable state on a lead record.
# --------------------------------------------------------------------------
class LeadUnlockWizard(models.TransientModel):
    _name = "lead.unlock.wizard"
    _description = "Unlock Lead Editing Wizard"

    lead_id = fields.Many2one("leads.logic", required=True)

    def action_unlock(self):
        self.lead_id.is_editable = True
        return {'type': 'ir.actions.act_window_close'}


# --------------------------------------------------------------------------
# Model: webinar.invite.wizard
# Description: Wizard to send webinar invitations via WhatsApp with Zoom links.
# --------------------------------------------------------------------------
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
        self.lead_id.write({'webinar_invite_sent': True, 'webinar_invite_sent_on': fields.Datetime.now(),
                            'webinar_invite_sent_by': self.env.user.id, 'webinar_zoom_link': self.zoom_link})
        whatsapp_url = 'https://wa.me/%s?text=%s' % (phone.replace('+', '').replace(' ', ''), quote(message))
        return {'type': 'ir.actions.act_url', 'url': whatsapp_url, 'target': 'new'}


# --------------------------------------------------------------------------
# Model: lead.open.history
# Description: Records instances of when a lead form was opened for auditing.
# --------------------------------------------------------------------------
class LeadOpenHistory(models.Model):
    _name = 'lead.open.history'
    _description = 'Lead Open History'
    _order = 'opened_on desc'

    lead_id = fields.Many2one('leads.logic', string='Lead', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', string='Opened By', required=True)
    opened_on = fields.Datetime(string='Opened On', default=fields.Datetime.now)
    ip_address = fields.Char(string='IP Address')
    remarks = fields.Char(string='Remarks')


class LeadExportHistory(models.Model):
    _name = 'lead.export.history'
    _description = 'Lead Export Audit'
    _order = 'export_date desc'

    user_id = fields.Many2one('res.users', string='Exported By', default=lambda self: self.env.user)
    export_date = fields.Datetime(string='Export Date', default=fields.Datetime.now)
    record_count = fields.Integer(string='Number of Records')
    exported_fields = fields.Text(string='Fields Exported')
    ip_address = fields.Char(string='IP Address')
    purpose = fields.Selection(
        [('whatsapp', 'Bulk WhatsApp'), ('sms', 'Bulk SMS'),
         ('call', 'Bulk Call List'), ('other', 'Other / Standard Export')],
        string='Purpose', default='other',
        help="Why this export was taken — feeds the Nurturing Dashboard's "
             "activity counters."
    )
    lead_ids = fields.Many2many('leads.logic', string='Leads Exported',
                                help="Exact leads included in this export — "
                                     "what data was actually sent out.")


class LeadNurtureExportWizard(models.TransientModel):
    _name = 'lead.nurture.export.wizard'
    _description = 'Export Leads for Nurturing (WhatsApp / SMS / Call)'

    purpose = fields.Selection(
        [('whatsapp', 'Bulk WhatsApp'), ('sms', 'Bulk SMS'), ('call', 'Bulk Call List')],
        string='Purpose', required=True, default='whatsapp',
        help="What are you exporting this list for? This is tracked and shown "
             "on the Nurturing Dashboard."
    )

    def action_export(self):
        self.ensure_one()
        active_ids = self.env.context.get('active_ids', [])
        leads = self.env['leads.logic'].browse(active_ids)
        if not leads:
            raise UserError(_("Select at least one lead to export."))

        # ── Build the CSV — the columns telecallers actually need for nurturing ──
        fields_map = [
            ('name', 'Lead Name'),
            ('phone_number', 'Phone'),
            ('phone_number_second', 'Alternate Phone'),
            ('email_address', 'Email'),
            ('student_category', 'Student Category'),
            ('lead_quality', 'Lead Quality'),
            ('academic_year', 'Academic Year'),
        ]
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([label for _key, label in fields_map])
        for lead in leads:
            row = []
            for key, _label in fields_map:
                value = getattr(lead, key, '')
                if hasattr(value, 'display_name'):
                    value = value.display_name
                if key == 'student_category':
                    value = dict(lead._fields['student_category'].selection).get(value, value or '')
                row.append(value or '')
            writer.writerow(row)
        csv_data = base64.b64encode(buffer.getvalue().encode('utf-8'))

        ip_addr = 'Unknown'
        if request:
            ip_addr = request.httprequest.remote_addr

        # ── Log it for the dashboard ─────────────────────────────────────
        self.env['lead.export.history'].sudo().create({
            'user_id': self.env.user.id,
            'export_date': fields.Datetime.now(),
            'record_count': len(leads),
            'exported_fields': ", ".join(label for _key, label in fields_map),
            'ip_address': ip_addr,
            'purpose': self.purpose,
            'lead_ids': [(6, 0, leads.ids)],
        })

        # ── Bump per-lead counters (WhatsApp / SMS only — calls are already
        #    tracked individually via the "Log Call" button / lead.call.log) ──
        if self.purpose == 'whatsapp':
            for lead in leads:
                lead.sudo().whatsapp_sent_count += 1
        elif self.purpose == 'sms':
            for lead in leads:
                lead.sudo().sms_sent_count += 1

        for lead in leads:
            lead.message_post(
                body=f"📤 Exported for <b>{dict(self._fields['purpose'].selection).get(self.purpose)}</b> "
                     f"by {self.env.user.name} on {fields.Datetime.now()}"
            )

        # ── Serve the file as a downloadable attachment ──────────────────
        attachment = self.env['ir.attachment'].sudo().create({
            'name': f"nurture_export_{self.purpose}_{fields.Date.today()}.csv",
            'type': 'binary',
            'datas': csv_data,
            'mimetype': 'text/csv',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }