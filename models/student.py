from odoo import fields, models, _, api

class StudentFormInherit(models.Model):
    _inherit = 'op.student'

    admission_officer_id = fields.Many2one('res.users', string="Admission Officer")
    branch_id = fields.Many2one('op.branch', string="Branch", required=1)
    admission_date = fields.Date(string="Admission Date")
    lead_id = fields.Many2one('leads.logic', string="Lead ID")
    is_referral = fields.Selection([('yes', 'Yes'), ('no', 'No')], string="Is Referral", default='no')
    referral_type = fields.Selection([('student', 'Student/Staff'), ('agent', 'Agent')], string='Referral Type')
    referral_lead_id = fields.Many2one('leads.logic', string="Referred By")

    # Fix for OwlError: "op.student"."attendance_line_ids" field is undefined.
    # attendance_line_ids = fields.Many2many('st.attendance.line', string="Attendance Lines")


class MailFormInherit(models.Model):
    _inherit = 'mail.activity'

    lead_id = fields.Many2one('leads.logic', string="Lead")

class LogicBaseBranches(models.Model):
    _inherit = "op.batch"

    branch = fields.Many2one('op.branch', string="Branch", required=1)