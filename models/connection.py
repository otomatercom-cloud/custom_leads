from odoo import fields, models, api, _, tools
from odoo.http import request
from odoo.exceptions import ValidationError, UserError
from datetime import datetime


class ConnectionForm(models.TransientModel):
    _name = 'connect.form'
    _description = 'Connection Form'

    lead_quality = fields.Selection(
        [('hot', 'Hot'),
         ('warm', 'Warm'), ('cold', 'Cold'),
         ('bad_lead', 'Bad Lead'), ('crash_lead', 'Crash Lead'), ('not_responding', 'Not Responding'),
         ],
        string='Lead Quality')
    expected_joining_date = fields.Date(string="Expected Joining Date")
    lead_id = fields.Many2one('leads.logic', string="Lead")
    crash_user_id = fields.Many2one('res.users', string="Crash User")
    subject = fields.Many2one('mail.activity.type', string="Subject")
    task_owner_id = fields.Many2one('res.users', string="Task Owner")
    due_date = fields.Date(string="Due Date")
    status = fields.Selection(
        [('not_started', 'Not Started'),
         ('deferred', 'Deffered'), ('in_progress', 'In Progress'),
         ('completed', 'Completed'), ('waiting_for_input', 'Waiting for Input')],
        string='Status')
    priority = fields.Selection(
        [('high', 'High'),
         ('highest', 'Highest'), ('low', 'Low'),
         ('lowest', 'Lowest'), ('normal', 'Normal')],
        string='Priority')
    description = fields.Text(string="Description")
    date = fields.Datetime(string="Date Time")

    @api.onchange('lead_quality')
    def _onchange_lead_quality(self):
        if self.lead_quality:
            if self.lead_quality != 'warm' or self.lead_quality != 'hot':
                self.expected_joining_date = False

    def act_connect(self):
        print('hi')
        self.lead_id.write({
            'lead_quality': self.lead_quality,
            'expected_joining_date': self.expected_joining_date,
            'crash_user_id': self.crash_user_id.id,
            'current_status': 'need_follow_up',
            'state': 'in_progress',
            'call_response': self.description,
            'next_follow_up_date': self.due_date
        })

        self.lead_id.activity_schedule(
            'custom_leads.mail_activity_lead_tasks', user_id=self.task_owner_id.id, summary=self.description,
            activity_type_id=self.subject.id, date_deadline=self.due_date,
            note=f'Task Created.'),


class NotConnectionForm(models.TransientModel):
    _name = 'not.connect.form'

    notes = fields.Text(string="Notes")
    lead_id = fields.Many2one('leads.logic', string="Lead")

    def act_done(self):
        self.lead_id.write({
            'not_response_note': self.notes,
            'lead_quality': 'not_responding',
            'current_status': 'not_responding',
            'state': 'not_connected',
        })


class ConvertLead(models.TransientModel):
    _name = 'convert.lead'

    amount = fields.Float(string="Booking Amount", compute="_compute_admission_amount", store=1)
    lead_id = fields.Many2one('leads.logic', string="Deal Name")
    closing_date = fields.Date(string="Closing Date")
    lead_owner_id = fields.Many2one('res.users', string="Lead Owner")
    add_on = fields.Boolean(string="Add On")
    add_amount = fields.Selection([('7000', '7000'), ('10000', '10000')], string="Add Amount")

    @api.depends('lead_id', 'add_amount', 'add_on')
    def _compute_admission_amount(self):
        if self.add_on == True:
            if self.add_amount == '7000':
                self.amount = self.lead_id.batch_id.adm_exc_fee + self.lead_id.batch_id.lump_fee_excluding_tax + 7000
            elif self.add_amount == '10000':
                self.amount = self.lead_id.batch_id.adm_exc_fee + self.lead_id.batch_id.lump_fee_excluding_tax + 10000
            else:
                self.amount = self.lead_id.batch_id.adm_exc_fee + self.lead_id.batch_id.lump_fee_excluding_tax
        else:
            self.amount = self.lead_id.batch_id.adm_exc_fee + self.lead_id.batch_id.lump_fee_excluding_tax

    def act_convert(self):
        self.lead_id.write({
            'closing_date': self.closing_date,
            'state': 'deal',
            'current_status': 'deal',
            'lead_quality': 'waiting_for_admission',
            'booking_amount': self.amount
        })


class LostLead(models.TransientModel):
    _name = 'lost.lead.form'

    lead_id = fields.Many2one('leads.logic', string="Lead")
    reason = fields.Text(string="Lost Reason")

    @api.constrains('reason')
    def _check_updated_remarks(self):
        for record in self:
            if not record.reason:
                raise ValidationError("Reason is required when Lead is 'Bad Lead'.")
            if len(record.reason) < 140:
                raise ValidationError("Reason must be at least 140 characters long.")

    def act_lost_lead(self):
        self.lead_id.write({
            'state': 'lost',
            'lost_reason': self.reason,
            'current_status': 'lost',
            'updated_remarks': self.reason
        })


class QualifiedLead(models.TransientModel):
    _name = 'qualified.lead.form'

    lead_id = fields.Many2one('leads.logic', string="Lead")
    first_name = fields.Char(string="First Name", required=1)
    last_name = fields.Char(string="Last Name", required=1)
    name = fields.Char(string="Name")
    batch_id = fields.Many2one('op.batch', string="Batch", domain="[('branch', '=', branch_id),('total_lump_sum_fee', '!=', 0)]")
    course_id = fields.Many2one('op.course', string="Course", related='batch_id.course_id')
    branch_id = fields.Many2one('op.branch', string="Branch", related='batch_id.branch')
    gender = fields.Selection([
        ('m', 'Male'),
        ('f', 'Female'),
        ('o', 'Other')
    ], 'Gender', required=True, default='m')
    birth_date = fields.Date('Birth Date', required=1)
    email = fields.Char(string="Email", required=1)
    mobile = fields.Char(string="Mobile")
    fee_type = fields.Selection([('lump_sum_fee', 'Lump Sum Fee'), ('installment', 'Installment'),
                                 ('3_installment', '3 Installment'),
                                 ('bajaj_finance_payment_plan', 'Bajaj Finance Payment Plan')], string="Fee Type", required=1)
    referral_source = fields.Selection([('yes', 'Yes'), ('no', 'No')], string="Referral", required=1)
    referral_type = fields.Selection([('student', 'Student/Staff'), ('agent', 'Agent')], string='Referral Type')
    referral_lead_id = fields.Many2one('leads.logic', string="Who Referred", domain="[('admission_status', '=', True)]",
                                       context={'referral_search': 1})

    @api.onchange('email')
    def _validate_email(self):
        if self.email and not tools.single_email_re.match(self.email):
            raise ValidationError(_('Invalid Email! Please enter a valid email address.'))

    @api.onchange('first_name', 'last_name')
    def _onchange_name(self):
        self.name = str(self.first_name) + " " + str(self.last_name)

    def act_admission(self):
        # Dynamic prefix based on financial year (April onwards = new year)
        today = datetime.today()
        if today.month >= 4:
            year = today.year
        else:
            year = today.year - 1
        prefix = f"L{year}/"

        # Get last student and continue the number from their gr_no
        admission_id = self.env['op.student'].sudo().search([], order="id DESC", limit=1)
        last_gr = admission_id.gr_no or f"{prefix}0"
        last_number = int(last_gr.split('/')[-1])
        new_number = last_number + 1
        new_gr_no = f"{prefix}{new_number}"
        print(new_gr_no, 'stuuu')

        due_amount = 0
        if self.fee_type == 'lump_sum_fee':
            due_amount = self.batch_id.total_lump_sum_fee
        elif self.fee_type == 'installment':
            due_amount = self.batch_id.total_installment_fee
        elif self.fee_type == '3_installment':
            due_amount = self.batch_id.total_three_installment_fee

        if self.lead_id.crash_lead == 1 or self.course_id.tayyap_course == True:
            print('its crash lead')
            student = self.env['op.student'].sudo().create({
                'name': self.name,
                'first_name': self.first_name,
                'last_name': self.last_name,
                'gr_no': new_gr_no,
                'gender': self.gender,
                'birth_date': self.birth_date,
                'email': self.email,
                'integrated_student': 0,
                'batch_id': self.batch_id.id,
                'course_id': self.course_id.id,
                'branch_id': self.branch_id.id,
                'state': 'batch_allocated',
                'mobile': self.mobile,
                'admission_officer_id': self.lead_id.lead_owner.user_id.id,
                'admission_date': fields.Date.today(),
                'fee_type': self.fee_type,
                'lead_id': self.lead_id.id,
                'due_amount': due_amount,
                'is_referral': self.referral_source,
                'referral_type': self.referral_type,
                'referral_lead_id': self.referral_lead_id.id,
            })
        else:
            print('its not crash lead')
            student = self.env['op.student'].sudo().create({
                'name': self.name,
                'first_name': self.first_name,
                'last_name': self.last_name,
                'gr_no': new_gr_no,
                'gender': self.gender,
                'birth_date': self.birth_date,
                'email': self.email,
                'integrated_student': 0,
                'batch_id': self.batch_id.id,
                'course_id': self.course_id.id,
                'branch_id': self.branch_id.id,
                'state': 'batch_allocated',
                'mobile': self.mobile,
                'admission_officer_id': self.lead_id.lead_owner.user_id.id,
                'fee_type': self.fee_type,
                'lead_id': self.lead_id.id,
                'due_amount': due_amount,
                'is_referral': self.referral_source,
                'referral_type': self.referral_type,
                'referral_lead_id': self.referral_lead_id.id,
            })

        student = self.env['op.student'].sudo().search([], order="id DESC", limit=1).id
        print(self.batch_id.course_id.name, 'course tayyep course')
        if self.lead_id.crash_lead == 1 or self.course_id.tayyap_course == True:
            print('tayyep course')
            self.lead_id.write({
                'state': 'qualified',
                'admission_status': True,
                'admission_date': fields.Datetime.now(),
                'current_status': 'admission',
                'lead_quality': 'admission',
                'student_id': student,
                'student_profile_created': True,
                'batch_id': self.batch_id.id,
            })
        else:
            print('not tayyep course')
            self.lead_id.write({
                'state': 'qualified',
                'admission_status': True,
                'current_status': 'admission',
                'lead_quality': 'waiting_for_admission',
                'student_id': student,
                'student_profile_created': True,
                'batch_id': self.batch_id.id,
            })

    @api.onchange('fee_type')
    def _onchange_fee_type(self):
        print(self.fee_type, 'typeee')
        if self.fee_type == 'lump_sum_fee':
            if self.batch_id.total_lump_sum_fee == 0:
                raise UserError(_("Lump Sum Fee Not Added"))
        if self.fee_type == 'installment':
            if self.batch_id.total_installment_fee == 0:
                raise UserError(_("Installment Fee Not Added"))
        if self.fee_type == '3_installment':
            if self.batch_id.total_three_installment_fee == 0:
                raise UserError(_("3 Installment Fee Not Added"))
        if self.fee_type == 'bajaj_finance_payment_plan':
            if self.batch_id.bajaj_emi_total == 0:
                raise UserError(_("Bajaj Fee Not Added"))

    @api.constrains('birth_date')
    def _check_birthdate(self):
        for record in self:
            if record.birth_date > fields.Date.today():
                raise ValidationError(_(
                    "Birth Date can't be greater than current date!"))