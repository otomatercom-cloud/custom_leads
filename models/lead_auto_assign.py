import logging
from datetime import timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class LeadAutoAssignPool(models.Model):
    """Round-robin auto-assignment pool.

    Configured by Team Leads / Managers / Admins.
    * Works only inside the working window (default 10:45 - 19:00, IST).
    * Only Admission Officers who are PRESENT (checked in today, not checked out) get leads.
    * A lead that arrives outside the window, or when nobody is present, is queued
      (flag `pending_auto_assign`) and handed out by a cron as soon as the window is open
      and an officer is present - e.g. the next morning at 10:45.
    """
    _name = 'lead.auto.assign.pool'
    _description = 'Lead Auto Assign Pool (Round Robin)'
    _inherit = ['mail.thread']
    _order = 'id'

    name = fields.Char(string='Pool Name', required=True, default='Auto Assign Pool', tracking=True)
    active = fields.Boolean(default=True)
    is_enabled = fields.Boolean(string='Auto Assign Enabled', default=True, tracking=True,
                                help='Switch off to stop automatic assignment without deleting the pool.')
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company)
    member_ids = fields.Many2many(
        'res.users', 'lead_auto_assign_pool_user_rel', 'pool_id', 'user_id',
        string='Admission Officers in Pool', tracking=True,
        domain=lambda self: [('groups_id', 'in', [self.env.ref('custom_leads.group_lead_users').id])],
        help='New leads are given to these officers one after another, in turn.',
    )
    member_count = fields.Integer(compute='_compute_member_count', string='Officers')

    # ── working window ──
    start_time = fields.Float(string='Start Time', default=10.75, tracking=True,
                              help='Round robin starts at this time (10.75 = 10:45 AM).')
    end_time = fields.Float(string='End Time', default=19.0, tracking=True,
                            help='No new lead is assigned after this time (19.0 = 7:00 PM). '
                                 'Leads arriving later wait and are assigned when the window opens again.')
    tz = fields.Selection(lambda self: [(t, t) for t in pytz.all_timezones], string='Timezone',
                          default='Asia/Kolkata', required=True)
    skip_sunday = fields.Boolean(string='Skip Sundays', default=False,
                                 help='If ticked, nothing is assigned on Sunday; leads wait until Monday start time.')

    # ── presence ──
    require_presence = fields.Boolean(
        string='Only Present Officers', default=True, tracking=True,
        help='Only officers who have checked in today (attendance) and not checked out receive leads.')

    pending_count = fields.Integer(string='Waiting Leads', compute='_compute_pending_count')
    last_user_id = fields.Many2one('res.users', string='Last Assigned To', readonly=True, copy=False)
    last_assigned_on = fields.Datetime(string='Last Assigned On', readonly=True, copy=False)
    assigned_total = fields.Integer(string='Leads Auto-Assigned', readonly=True, copy=False)

    @api.depends('member_ids')
    def _compute_member_count(self):
        for rec in self:
            rec.member_count = len(rec.member_ids)

    def _compute_pending_count(self):
        count = self.env['leads.logic'].sudo().search_count([('pending_auto_assign', '=', True)])
        for rec in self:
            rec.pending_count = count

    @api.constrains('is_enabled', 'company_id', 'active')
    def _check_one_enabled_pool(self):
        for rec in self:
            if rec.is_enabled and rec.active:
                other = self.search_count([
                    ('id', '!=', rec.id), ('is_enabled', '=', True),
                    ('active', '=', True), ('company_id', '=', rec.company_id.id),
                ])
                if other:
                    raise ValidationError(_('Only one enabled Auto Assign Pool is allowed per company.'))

    @api.constrains('start_time', 'end_time')
    def _check_times(self):
        for rec in self:
            if not (0 <= rec.start_time < 24 and 0 < rec.end_time <= 24) or rec.start_time >= rec.end_time:
                raise ValidationError(_('Start Time must be earlier than End Time (same day).'))

    # ------------------------------------------------------------------ helpers
    def _local_now(self):
        self.ensure_one()
        return pytz.utc.localize(fields.Datetime.now()).astimezone(pytz.timezone(self.tz or 'Asia/Kolkata'))

    def _is_open_now(self):
        """True if the current local time is inside the working window."""
        self.ensure_one()
        now = self._local_now()
        if self.skip_sunday and now.weekday() == 6:
            return False
        hour = now.hour + now.minute / 60.0
        return self.start_time <= hour < self.end_time

    def _present_user_ids(self, users):
        """Users that are present now: checked in today and not checked out."""
        self.ensure_one()
        if not self.require_presence:
            return set(users.ids)
        if 'hr.attendance' not in self.env:
            _logger.warning('hr.attendance not installed: presence check skipped for auto assign.')
            return set(users.ids)
        now = self._local_now()
        start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
        employees = self.env['hr.employee'].sudo().search([('user_id', 'in', users.ids)])
        att = self.env['hr.attendance'].sudo().search([
            ('employee_id', 'in', employees.ids),
            ('check_in', '>=', start_utc),
            ('check_out', '=', False),
        ])
        present_emps = att.mapped('employee_id')
        return set(present_emps.mapped('user_id').ids)

    # ------------------------------------------------------------------ main API
    @api.model
    def _next_employee(self):
        """Return the hr.employee of the next PRESENT officer in rotation, inside the
        working window. Empty recordset = nobody can take the lead right now (queue it)."""
        empty = self.env['hr.employee']
        pool = self.sudo().search([
            ('is_enabled', '=', True), ('active', '=', True),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not pool or not pool._is_open_now():
            return empty
        # lock the pool row so two leads arriving together never get the same officer
        self.env.cr.execute('SELECT id FROM lead_auto_assign_pool WHERE id = %s FOR UPDATE', (pool.id,))
        pool.invalidate_recordset(['last_user_id'])

        users = pool.member_ids.filtered('active').sorted('id')
        emp_by_user = {}
        for user in users:
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
            if emp:
                emp_by_user[user.id] = emp
        users = users.filtered(lambda u: u.id in emp_by_user)
        if not users:
            return empty
        present = pool._present_user_ids(users)
        if not present:
            return empty

        ordered = list(users)
        start = 0
        if pool.last_user_id:
            ids = [u.id for u in ordered]
            if pool.last_user_id.id in ids:
                start = ids.index(pool.last_user_id.id) + 1
            else:
                higher = [i for i, u in enumerate(ordered) if u.id > pool.last_user_id.id]
                start = higher[0] if higher else 0
        pick = None
        for step in range(len(ordered)):
            cand = ordered[(start + step) % len(ordered)]
            if cand.id in present:
                pick = cand
                break
        if not pick:
            return empty
        pool.write({
            'last_user_id': pick.id,
            'last_assigned_on': fields.Datetime.now(),
            'assigned_total': pool.assigned_total + 1,
        })
        return emp_by_user[pick.id]

    @api.model
    def _cron_assign_pending(self):
        """Hand out queued leads (arrived outside hours / nobody present) in arrival order."""
        Lead = self.env['leads.logic'].sudo()
        pending = Lead.search([('pending_auto_assign', '=', True)], order='create_date asc, id asc')
        for lead in pending:
            emp = self._next_employee()
            if not emp:
                break  # window closed or nobody present: try again next run
            lead.with_context(skip_auto_assign=True).write({
                'lead_owner': emp.id,
                'pending_auto_assign': False,
            })
        return True

    def action_assign_pending_now(self):
        self._cron_assign_pending()
        return True
