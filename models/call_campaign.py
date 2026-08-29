import logging
from datetime import date

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

QUALITY_SELECTION = [
    ('new', '🆕 New'),
    ('first_attempt', '🎯 First Attempt'),
    ('waiting_for_admission', '⏳ Waiting for Admission'),
    ('admission', '🎓 Admission'),
    ('hot', '🔥 Hot'),
    ('warm', '🌞 Warm'),
    ('cold', '❄️ Cold'),
    ('bad_lead', '⚠️ Language Barrier'),
    ('crash_lead', '💥 Crash Lead'),
    ('not_responding', '🔕 Ringing Not Responding'),
    ('call_later', '📞 Call Later'),
    ('may_be_later', '🔔 May Be Later'),
    ('follow_up', '⏰ Follow Up'),
    ('not_reachable', '🚫 Not Reachable'),
    ('already_joined', '✅ Already Joined'),
    ('joined_other_institute', '🏫 Joined Other Institute'),
    ('wrong_number', '📵 Wrong Number'),
    ('not_enquiry', '🛑 Not Enquiry'),
]


class CallCampaign(models.Model):
    _name = 'call.campaign'
    _description = 'Call Campaign'
    _order = 'create_date desc'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Campaign Name', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('running', 'Running'),
        ('done', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    created_by = fields.Many2one(
        'res.users', string='Created By',
        default=lambda self: self.env.user, readonly=True,
    )
    description = fields.Text(string='Notes')

    # ── Filters ───────────────────────────────────────────────────────────
    filter_lead_quality = fields.Many2many(
        'call.campaign.quality', 'campaign_quality_rel', 'campaign_id', 'quality_id',
        string='Filter by Quality',
    )
    filter_lead_owner = fields.Many2many(
        'hr.employee', 'campaign_owner_rel', 'campaign_id', 'employee_id',
        string='Filter by Lead Owner',
    )
    filter_leads_source = fields.Many2many(
        'leads.sources', 'campaign_source_rel', 'campaign_id', 'source_id',
        string='Filter by Source',
    )
    filter_team = fields.Many2many(
        'lead.team', 'campaign_team_rel', 'campaign_id', 'team_id',
        string='Filter by Team',
    )

    # ── Leads ─────────────────────────────────────────────────────────────
    lead_ids = fields.Many2many(
        'leads.logic', 'call_campaign_lead_rel', 'campaign_id', 'lead_id',
        string='Leads',
    )
    lead_count = fields.Integer(
        string='Total Leads', compute='_compute_counts', store=True,
    )
    called_count = fields.Integer(
        string='Called', compute='_compute_counts', store=True,
    )
    pending_count = fields.Integer(
        string='Pending', compute='_compute_counts', store=True,
    )

    @api.depends('lead_ids', 'lead_ids.campaign_call_done')
    def _compute_counts(self):
        for rec in self:
            rec.lead_count = len(rec.lead_ids)
            rec.called_count = len(rec.lead_ids.filtered('campaign_call_done'))
            rec.pending_count = rec.lead_count - rec.called_count

    # ── Actions ───────────────────────────────────────────────────────────
    def action_load_leads(self):
        domain = []
        if self.filter_lead_quality:
            domain.append(('lead_quality', 'in', self.filter_lead_quality.mapped('value')))
        if self.filter_lead_owner:
            domain.append(('lead_owner', 'in', self.filter_lead_owner.ids))
        if self.filter_leads_source:
            domain.append(('leads_source', 'in', self.filter_leads_source.ids))
        if self.filter_team:
            # leads whose owner belongs to a filtered team
            member_employees = self.env['hr.employee'].search([
                ('admission_team_id', 'in', self.filter_team.ids)
            ])
            domain.append(('lead_owner', 'in', member_employees.ids))
        leads = self.env['leads.logic'].search(domain, limit=500)
        self.lead_ids = [(6, 0, leads.ids)]
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Leads Loaded',
                'message': '%d leads added to campaign.' % len(leads),
                'type': 'success',
            },
        }

    def action_start(self):
        if not self.lead_ids:
            raise UserError('Add leads to the campaign before starting.')
        self.state = 'running'
        return self.action_open_runner()

    def action_open_runner(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'call_campaign_runner',
            'name': '📞 %s' % self.name,
            'params': {'campaign_id': self.id},
        }

    def action_mark_done(self):
        self.state = 'done'

    def action_cancel(self):
        self.state = 'cancelled'

    def action_reset(self):
        self.state = 'draft'
        self.lead_ids.write({'campaign_call_done': False})

    # ── Helpers ───────────────────────────────────────────────────────────
    def _get_employee_for_user(self, user):
        """Return the hr.employee linked to a res.users record, or False."""
        return self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)

    def _get_officers_for_tl(self, tl_employee):
        """
        Return hr.employee records that are officers under this TL.
        In Odoo 17, team membership is via hr.employee.admission_team_id.
        We find teams where this employee is a team_lead, then get all members.
        """
        teams = self.env['lead.team'].search([
            ('team_lead_ids', 'in', tl_employee.user_id.ids)
        ])
        if not teams:
            return self.env['hr.employee']
        return self.env['hr.employee'].search([
            ('admission_team_id', 'in', teams.ids)
        ])

    def _get_all_officers(self):
        """Return all hr.employee records that have an admission team."""
        return self.env['hr.employee'].search([
            ('admission_team_id', '!=', False)
        ])

    # ── RPC helpers for JS ────────────────────────────────────────────────
    @api.model
    def get_campaign_leads(self, campaign_id):
        campaign = self.browse(campaign_id)
        quality_map = dict(QUALITY_SELECTION)
        leads = []
        for lead in campaign.lead_ids:
            leads.append({
                'id': lead.id,
                'name': lead.name,
                'phone': lead.phone_number or '',
                'quality': lead.lead_quality or 'new',
                'quality_label': quality_map.get(lead.lead_quality, lead.lead_quality or ''),
                'call_response': lead.third_response or '',
                'called': lead.campaign_call_done,
                'reference': lead.reference_no or '',
                'course': ', '.join(lead.course_inter.mapped('name')) if lead.course_inter else '',
                'lead_owner': lead.lead_owner.name if lead.lead_owner else '',
            })
        called = len([l for l in leads if l['called']])
        return {
            'campaign_name': campaign.name,
            'total': len(leads),
            'called': called,
            'pending': len(leads) - called,
            'leads': leads,
            'quality_options': QUALITY_SELECTION,
        }

    @api.model
    def submit_call_response(self, campaign_id, lead_id, quality, response):
        """Save quality + response and mark lead as called in campaign."""
        lead = self.env['leads.logic'].browse(lead_id)
        vals = {'campaign_call_done': True}
        if quality:
            vals['lead_quality'] = quality
        if response:
            vals['third_response'] = response
            self.env['lead.response'].create({
                'lead_id': lead_id,
                'comment': response,
                'user_id': self.env.uid,
            })
        lead.write(vals)
        return True

    @api.model
    def get_or_create_daily_campaign(self):
        """
        Auto-creates/finds today's daily call campaign for the current user.
        """
        user = self.env.user
        today_str = date.today().strftime('%Y-%m-%d')

        employee = self._get_employee_for_user(user)
        user_label = employee.name if employee else user.name
        campaign_name = 'Daily Campaign - %s - %s' % (user_label, today_str)

        existing = self.search([
            ('name', '=', campaign_name),
            ('created_by', '=', user.id),
        ], limit=1)

        if existing:
            campaign = existing
        else:
            quality_priority = [
                'hot', 'warm', 'follow_up', 'call_later', 'may_be_later',
                'first_attempt', 'new', 'not_responding', 'cold',
                'waiting_for_admission', 'crash_lead', 'bad_lead',
            ]

            if employee:
                domain = [
                    ('lead_owner', '=', employee.id),
                    ('state', 'not in', ['lost', 'qualified']),
                    ('lead_quality', 'in', quality_priority),
                ]
            else:
                domain = [
                    ('create_uid', '=', user.id),
                    ('state', 'not in', ['lost', 'qualified']),
                    ('lead_quality', 'in', quality_priority),
                ]

            all_leads = self.env['leads.logic'].search(domain, order='id asc')

            def quality_rank(lead):
                try:
                    return quality_priority.index(lead.lead_quality)
                except ValueError:
                    return 99

            sorted_leads = sorted(all_leads, key=quality_rank)[:50]

            campaign = self.create({
                'name': campaign_name,
                'state': 'running',
                'lead_ids': [(6, 0, [l.id for l in sorted_leads])],
            })

        return {
            'campaign_id': campaign.id,
            'campaign_name': campaign.name,
            'state': campaign.state,
            'total': campaign.lead_count,
            'called': campaign.called_count,
            'pending': campaign.pending_count,
        }

    def _create_campaign_for_employee(self, employee, today_str, quality_priority):
        """Internal helper: create or return today's campaign for one employee."""
        campaign_name = 'Daily Campaign - %s - %s' % (employee.name, today_str)
        existing = self.search([('name', '=', campaign_name)], limit=1)
        if existing:
            return existing

        all_leads = self.env['leads.logic'].search([
            ('lead_owner', '=', employee.id),
            ('state', 'not in', ['lost', 'qualified']),
            ('lead_quality', 'in', quality_priority),
        ], order='id asc')

        def quality_rank(lead):
            try:
                return quality_priority.index(lead.lead_quality)
            except ValueError:
                return 99

        sorted_leads = sorted(all_leads, key=quality_rank)[:50]
        return self.create({
            'name': campaign_name,
            'state': 'running',
            'lead_ids': [(6, 0, [l.id for l in sorted_leads])],
        })

    @api.model
    def generate_team_campaigns(self, team_lead_employee_id=None):
        """
        Called by Team Lead button on dashboard.
        Creates daily campaigns for all officers under the TL's teams.
        """
        today_str = date.today().strftime('%Y-%m-%d')
        quality_priority = [
            'hot', 'warm', 'follow_up', 'call_later', 'may_be_later',
            'first_attempt', 'new', 'not_responding', 'cold',
            'waiting_for_admission', 'crash_lead', 'bad_lead',
        ]

        if team_lead_employee_id:
            tl_employee = self.env['hr.employee'].browse(team_lead_employee_id)
            officers = self._get_officers_for_tl(tl_employee)
        else:
            officers = self._get_all_officers()

        created = 0
        existing = 0
        for officer in officers:
            campaign_name = 'Daily Campaign - %s - %s' % (officer.name, today_str)
            if self.search([('name', '=', campaign_name)], limit=1):
                existing += 1
            else:
                self._create_campaign_for_employee(officer, today_str, quality_priority)
                created += 1

        return {
            'created': created,
            'existing': existing,
            'total': len(officers),
        }

    @api.model
    def get_dashboard_campaign_info(self):
        """
        Returns info for the dashboard:
        - For officers: their own daily campaign
        - For TL/manager: list of their team officers + campaign status
        """
        user = self.env.user
        today_str = date.today().strftime('%Y-%m-%d')
        is_tl      = user.has_group('custom_leads.group_lead_team_lead')
        is_manager = user.has_group('custom_leads.group_lead_manager')
        is_super   = user.has_group('custom_leads.group_super_admin')
        is_odoo_admin = user.has_group('base.group_system')

        employee = self._get_employee_for_user(user)

        result = {
            'role': 'manager' if (is_manager or is_super or is_odoo_admin) else ('tl' if is_tl else 'officer'),
            'employee_id': employee.id if employee else False,
            'own_campaign': None,
            'team_summary': None,
        }

        own = self.get_or_create_daily_campaign()
        if 'error' not in own:
            result['own_campaign'] = own

        if is_tl or is_manager or is_super or is_odoo_admin:
            if is_tl and employee:
                officers = self._get_officers_for_tl(employee)
            else:
                officers = self._get_all_officers()

            team_campaigns = []
            for officer in officers:
                campaign_name = 'Daily Campaign - %s - %s' % (officer.name, today_str)
                campaign = self.search([('name', '=', campaign_name)], limit=1)
                team_campaigns.append({
                    'employee_name': officer.name,
                    'employee_id': officer.id,
                    'has_campaign': bool(campaign),
                    'campaign_id': campaign.id if campaign else False,
                    'total': campaign.lead_count if campaign else 0,
                    'called': campaign.called_count if campaign else 0,
                    'pending': campaign.pending_count if campaign else 0,
                })

            result['team_summary'] = {
                'officers': team_campaigns,
                'total_officers': len(officers),
                'campaigns_created': len([c for c in team_campaigns if c['has_campaign']]),
                'tl_employee_id': employee.id if employee else False,
            }

        return result

    @api.model
    def get_campaign_dashboard_data(self):
        """Returns all campaigns visible to current user with stats."""
        user = self.env.user
        is_manager = user.has_group('custom_leads.group_lead_manager')
        is_super   = user.has_group('custom_leads.group_super_admin')
        is_tl      = user.has_group('custom_leads.group_lead_team_lead')
        is_odoo_admin = user.has_group('base.group_system')
        employee   = self._get_employee_for_user(user)

        role = 'manager' if (is_manager or is_super or is_odoo_admin) else ('tl' if is_tl else 'officer')

        if is_manager or is_super or is_odoo_admin:
            campaigns = self.search([], order='create_date desc')
        elif is_tl:
            if employee:
                officers = self._get_officers_for_tl(employee)
                officer_user_ids = officers.mapped('user_id').ids
                officer_names = officers.mapped('name') + [employee.name]
                # Match created_by OR name contains officer name (cron-created)
                name_domain = ['|'] * (len(officer_names) - 1) if len(officer_names) > 1 else []
                for ename in officer_names:
                    name_domain += [('name', 'ilike', ename)]
                campaigns = self.search(
                    ['|', '|',
                     ('created_by', '=', user.id),
                     ('created_by', 'in', officer_user_ids),
                    ] + (['|'] + name_domain if name_domain else name_domain),
                    order='create_date desc'
                )
            else:
                campaigns = self.search([('created_by', '=', user.id)], order='create_date desc')
        else:
            # Officer: own campaigns + cron-created daily campaign for this employee
            if employee:
                campaigns = self.search([
                    '|',
                    ('created_by', '=', user.id),
                    ('name', 'ilike', employee.name),
                ], order='create_date desc')
            else:
                campaigns = self.search([('created_by', '=', user.id)], order='create_date desc')

        result = []
        for c in campaigns:
            # A campaign is "mine" if I created it, or if it's a daily campaign named after me
            is_mine = (c.created_by.id == user.id) or (
                employee and employee.name and employee.name in c.name
            )
            result.append({
                'id': c.id,
                'name': c.name,
                'state': c.state,
                'created_by': c.created_by.name if c.created_by else '',
                'date': str(c.create_date.date()) if c.create_date else '',
                'total': c.lead_count,
                'called': c.called_count,
                'pending': c.pending_count,
                'is_mine': is_mine,
            })

        running = [c for c in result if c['state'] == 'running']
        draft   = [c for c in result if c['state'] == 'draft']
        done    = [c for c in result if c['state'] == 'done']

        return {
            'role': role,
            'campaigns': result,
            'stats': {
                'total': len(result),
                'running': len(running),
                'draft': len(draft),
                'done': len(done),
                'total_leads': sum(c['total'] for c in result),
                'total_called': sum(c['called'] for c in result),
            },
        }

    @api.model
    def auto_create_all_officer_campaigns(self):
        """
        Called by scheduled cron job every day.
        Creates a daily campaign for every active admission officer
        who has leads assigned to them.
        """
        today_str = date.today().strftime('%Y-%m-%d')
        quality_priority = [
            'hot', 'warm', 'follow_up', 'call_later', 'may_be_later',
            'first_attempt', 'new', 'not_responding', 'cold',
            'waiting_for_admission', 'crash_lead', 'bad_lead',
        ]

        employees_with_leads = self.env['leads.logic'].search([
            ('state', 'not in', ['lost', 'qualified']),
            ('lead_quality', 'in', quality_priority),
            ('lead_owner', '!=', False),
        ]).mapped('lead_owner')

        created = 0
        skipped = 0
        for employee in employees_with_leads:
            campaign_name = 'Daily Campaign - %s - %s' % (employee.name, today_str)
            if self.search([('name', '=', campaign_name)], limit=1):
                skipped += 1
                continue
            self._create_campaign_for_employee(employee, today_str, quality_priority)
            created += 1

        _logger.info(
            'Daily campaign cron: %d created, %d already existed for %d officers.',
            created, skipped, len(employees_with_leads),
        )
        return True


class CallCampaignQuality(models.Model):
    """Helper model so quality filter can be a Many2many selector."""
    _name = 'call.campaign.quality'
    _description = 'Campaign Quality Filter Option'

    name = fields.Char(string='Label', required=True)
    value = fields.Char(string='Value', required=True)

    @api.model
    def _ensure_defaults(self):
        for val, label in QUALITY_SELECTION:
            if not self.search([('value', '=', val)], limit=1):
                self.create({'name': label, 'value': val})


class LeadsLogicCampaign(models.Model):
    _inherit = 'leads.logic'

    campaign_call_done = fields.Boolean(
        string='Campaign Called', default=False,
    )
    campaign_ids = fields.Many2many(
        'call.campaign', 'call_campaign_lead_rel', 'lead_id', 'campaign_id',
        string='Campaigns',
    )
