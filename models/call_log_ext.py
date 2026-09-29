# --------------------------------------------------------------------------
# Call Log Dashboard — extends lead.call.log with reporting fields and adds
# the server-side aggregation used by the "☎ Call Dashboard" client action.
#
# Design notes (Odoo 17):
#   - duration/is_connected/call_date are stored compute fields so they can
#     be summed / filtered directly in SQL (fast GROUP BY across thousands
#     of rows) instead of looping in Python.
#   - The dashboard query uses raw SQL (like the existing
#     get_dashboard_stage_counts / get_nurturing_activity_counts methods in
#     leads.py) for a single round-trip regardless of dataset size, then
#     uses the ORM only for the small, human-scale lookups (teams,
#     campaigns, employees).
#   - call.campaign gets an `employee_id` field so today's Assigned/Called/
#     Pending numbers can be joined reliably instead of matching on the
#     "Daily Campaign - <name> - <date>" string. Older campaigns created
#     before this field existed are still picked up via a name fallback.
# --------------------------------------------------------------------------
from odoo import models, fields, api


def _parse_duration_to_seconds(duration_str):
    """Best-effort parse of the Char `duration` field into whole seconds.

    Accepts 'HH:MM:SS', 'MM:SS', a plain number of seconds, or a float
    string such as '7.0'. Anything unparsable safely returns 0.
    """
    if not duration_str:
        return 0
    text = str(duration_str).strip()
    if not text:
        return 0
    try:
        if ':' in text:
            parts = [int(float(p)) for p in text.split(':')]
            while len(parts) < 3:
                parts.insert(0, 0)
            hours, minutes, seconds = parts[-3], parts[-2], parts[-1]
            return hours * 3600 + minutes * 60 + seconds
        return int(float(text))
    except (ValueError, TypeError):
        return 0


def _seconds_to_hms(total_seconds):
    total_seconds = int(total_seconds or 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return "%02d:%02d:%02d" % (hours, minutes, seconds)


class LeadCallLogDashboard(models.Model):
    _inherit = 'lead.call.log'

    # Re-declared only to add DB indexes — attributes not repeated here
    # (default=, ondelete=, string=, etc.) are preserved from the base
    # definition in models/leads.py.
    user_id = fields.Many2one(index=True)
    lead_id = fields.Many2one(index=True)
    call_time = fields.Datetime(index=True)

    duration_seconds = fields.Integer(
        string='Duration (sec)', compute='_compute_call_metrics', store=True,
    )
    is_connected = fields.Boolean(
        string='Connected', compute='_compute_call_metrics', store=True,
        help="True when the call status looks like 'Answered' or the call "
             "had a duration greater than zero.",
    )
    call_date = fields.Date(
        string='Call Date', compute='_compute_call_metrics', store=True, index=True,
    )
    has_recording = fields.Boolean(
        string='Has Recording', compute='_compute_call_metrics', store=True,
    )

    @api.depends('duration', 'call_status', 'call_time', 'recording_url')
    def _compute_call_metrics(self):
        for rec in self:
            seconds = _parse_duration_to_seconds(rec.duration)
            status = (rec.call_status or '').strip().lower()
            rec.duration_seconds = seconds
            rec.is_connected = bool(('answer' in status) or seconds > 0)
            rec.call_date = rec.call_time.date() if rec.call_time else False
            rec.has_recording = bool(rec.recording_url)

    def action_play_recording(self):
        """Open the recording URL in a new browser tab."""
        self.ensure_one()
        if not self.recording_url:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': self.recording_url,
            'target': 'new',
        }

    # ── Dashboard aggregation ───────────────────────────────────────────
    @api.model
    def get_call_log_dashboard_data(self, date_filter='today'):
        """
        Returns everything the Call Dashboard widget needs in one call:
        role-scoped KPI totals + a per-team, per-agent breakdown combining
        telephony stats (this method, from lead.call.log) with today's
        dialing-list stats (call.campaign: Assigned / Called / Pending).

        date_filter: 'today' | 'yesterday' | 'week' | 'month' | 'all'

        Agent identity is res.users (that's what lead.call.log.user_id
        actually points to) — NOT hr.employee. A telephony agent doesn't
        need an hr.employee record or a Lead Team assignment to show up
        here; team/role/reporting-TL are enrichment, added when available,
        never a requirement for being listed.
        """
        from datetime import date, timedelta

        cr = self.env.cr
        user = self.env.user
        today = date.today()

        def _date_range(df):
            if df == 'yesterday':
                y = today - timedelta(days=1)
                return y, y
            if df == 'week':
                return today - timedelta(days=today.weekday()), today
            if df == 'month':
                return today.replace(day=1), today
            if df == 'all':
                return date(2000, 1, 1), today
            return today, today  # 'today' (default)

        date_from, date_to = _date_range(date_filter)

        Users = self.env['res.users'].sudo()

        is_manager = user.has_group('custom_leads.group_lead_manager')
        is_super = user.has_group('custom_leads.group_super_admin')
        is_odoo_admin = user.has_group('base.group_system')
        is_tl = user.has_group('custom_leads.group_lead_team_lead')

        # ── Roster: WHO counts as an agent, independent of the date filter
        # so switching Today/Week/Month/All Time never changes which rows
        # show up — only their stats.
        if is_manager or is_super or is_odoo_admin:
            role = 'manager'
            # Anyone who has ever logged a call, OR is on a Lead Team, OR
            # has ever had a daily dialing campaign generated for them.
            cr.execute("SELECT DISTINCT user_id FROM lead_call_log WHERE user_id IS NOT NULL")
            calling_user_ids = {row[0] for row in cr.fetchall()}
            team_user_ids = set(Users.search([('admission_team_id', '!=', False)]).ids)
            campaign_user_ids = set(
                self.env['call.campaign'].sudo().search([('employee_id.user_id', '!=', False)])
                .mapped('employee_id.user_id').ids
            )
            roster_ids = calling_user_ids | team_user_ids | campaign_user_ids
        elif is_tl:
            role = 'tl'
            teams = self.env['lead.team'].sudo().search([('team_lead_ids', 'in', [user.id])])
            roster_ids = set(Users.search([('admission_team_id', 'in', teams.ids)]).ids) if teams else set()
        else:
            role = 'officer'
            roster_ids = {user.id}

        empty_kpi = dict(assigned=0, total_calls=0, connected=0, outgoing=0, incoming=0,
                          called_leads=0, pending=0, recordings=0, talk_seconds=0, talk_time='00:00:00')
        if not roster_ids:
            return {'role': role, 'date_filter': date_filter, 'date_from': str(date_from),
                    'date_to': str(date_to), 'kpi': empty_kpi, 'teams': []}

        # Note: intentionally NOT filtering by active=True here. The raw SQL
        # above bypasses Odoo's implicit "hide archived records" behaviour on
        # purpose — an agent whose login was later archived (left the
        # company, telephony-only account, etc.) should still show up with
        # their historical call stats. Re-adding an active filter here would
        # silently drop them again, which is exactly what caused agents with
        # real call logs to disappear from every date filter.
        agents = Users.browse(list(roster_ids)).exists()
        if not agents:
            return {'role': role, 'date_filter': date_filter, 'date_from': str(date_from),
                    'date_to': str(date_to), 'kpi': empty_kpi, 'teams': []}

        agent_ids = agents.ids

        # ── 1. Telephony stats per agent (res.users), ONE query ──────────
        cr.execute(
            """
            SELECT u.id,
                   COUNT(cl.id)                                                       AS total_calls,
                   COUNT(cl.id) FILTER (WHERE cl.call_type = 'outgoing')              AS outgoing,
                   COUNT(cl.id) FILTER (WHERE cl.call_type = 'incoming')              AS incoming,
                   COUNT(cl.id) FILTER (WHERE cl.is_connected)                        AS connected,
                   COUNT(cl.id) FILTER (WHERE cl.has_recording)                       AS recordings,
                   COALESCE(SUM(cl.duration_seconds), 0)                              AS talk_seconds
            FROM   res_users u
            LEFT JOIN lead_call_log cl
                   ON cl.user_id = u.id
                  AND cl.call_date >= %s AND cl.call_date <= %s
            WHERE  u.id = ANY(%s)
            GROUP  BY u.id
            """,
            (date_from, date_to, agent_ids),
        )
        call_map = {row[0]: row[1:] for row in cr.fetchall()}

        # ── 2. Today's dialing-list stats per agent (call.campaign) ──────
        # call.campaign links to hr.employee (lead ownership lives there),
        # so agents with no hr.employee record simply get 0s here — that's
        # correct, not a bug: they can still have full call stats above.
        Campaign = self.env['call.campaign'].sudo()
        emp_to_user = {a.employee_id.id: a.id for a in agents if a.employee_id}
        emp_ids = list(emp_to_user.keys())
        camp_map = {}  # user_id -> campaign
        if emp_ids:
            campaigns = Campaign.search([('employee_id', 'in', emp_ids)])
            for c in campaigns:
                if c.employee_id and c.employee_id.id in emp_to_user:
                    camp_map[emp_to_user[c.employee_id.id]] = c

            missing_emp_ids = [eid for eid in emp_ids if emp_to_user[eid] not in camp_map]
            if missing_emp_ids:
                today_str = today.strftime('%Y-%m-%d')
                name_to_user = {}
                for emp in self.env['hr.employee'].sudo().browse(missing_emp_ids):
                    name_to_user['Daily Campaign - %s - %s' % (emp.name, today_str)] = emp_to_user[emp.id]
                if name_to_user:
                    for camp in Campaign.search([('name', 'in', list(name_to_user.keys()))]):
                        uid = name_to_user.get(camp.name)
                        if uid:
                            camp_map[uid] = camp

        # ── 3. Role lookups (small, human-scale — plain ORM) ──────────────
        tl_group = self.env.ref('custom_leads.group_lead_team_lead', raise_if_not_found=False)
        tl_user_ids = set(tl_group.users.ids) if tl_group else set()

        def build_agent_row(agent):
            stats = call_map.get(agent.id, (0, 0, 0, 0, 0, 0))
            total_calls, outgoing, incoming, connected, recordings, talk_seconds = stats
            not_connected = total_calls - connected
            connect_pct = round((connected / total_calls) * 100) if total_calls else 0
            avg_seconds = round(talk_seconds / connected) if connected else 0

            camp = camp_map.get(agent.id)
            assigned = camp.lead_count if camp else 0
            called_leads = camp.called_count if camp else 0
            pending = camp.pending_count if camp else 0

            team = agent.admission_team_id
            reporting_tl = ', '.join(team.team_lead_ids.mapped('name')) if team else ''
            role_label = 'Team Lead' if agent.id in tl_user_ids else 'Officer'

            return {
                'employee_id': agent.employee_id.id if agent.employee_id else 0,
                'user_id': agent.id,
                'name': agent.employee_id.name if agent.employee_id else agent.name,
                'role': role_label,
                'reporting_tl': reporting_tl,
                'assigned': assigned,
                'total_calls': total_calls,
                'outgoing': outgoing,
                'incoming': incoming,
                'connected': connected,
                'not_connected': not_connected,
                'recordings': recordings,
                'called_leads': called_leads,
                'pending': pending,
                'talk_seconds': talk_seconds,
                'talk_time': _seconds_to_hms(talk_seconds),
                'avg_seconds': avg_seconds,
                'avg_time': _seconds_to_hms(avg_seconds),
                'connect_pct': connect_pct,
            }

        # ── 4. Group agents by team, keep "Unassigned" bucket ────────────
        teams_out = {}
        order = []
        for agent in agents.sorted(key=lambda a: a.name or ''):
            team = agent.admission_team_id
            key = team.id if team else 0
            if key not in teams_out:
                teams_out[key] = {'id': key, 'name': team.name if team else 'Unassigned', 'agents': []}
                order.append(key)
            teams_out[key]['agents'].append(build_agent_row(agent))

        kpi = dict(assigned=0, total_calls=0, connected=0, outgoing=0, incoming=0,
                   called_leads=0, pending=0, recordings=0, talk_seconds=0)
        teams_list = []
        for key in order:
            t = teams_out[key]
            summary = dict(assigned=0, total_calls=0, connected=0, pending=0)
            for a in t['agents']:
                summary['assigned'] += a['assigned']
                summary['total_calls'] += a['total_calls']
                summary['connected'] += a['connected']
                summary['pending'] += a['pending']
                for k in kpi:
                    kpi[k] += a.get(k, 0)
            t['summary'] = summary
            teams_list.append(t)

        teams_list.sort(key=lambda t: (t['id'] == 0, t['name'] or ''))
        kpi['talk_time'] = _seconds_to_hms(kpi['talk_seconds'])

        return {
            'role': role,
            'date_filter': date_filter,
            'date_from': str(date_from),
            'date_to': str(date_to),
            'kpi': kpi,
            'teams': teams_list,
        }


class CallCampaignEmployeeLink(models.Model):
    """Adds a hard link from a daily call campaign to the officer it was
    generated for, so reporting doesn't have to parse the campaign name."""
    _inherit = 'call.campaign'

    employee_id = fields.Many2one(
        'hr.employee', string='Officer', index=True,
        help='Officer this daily campaign was auto-generated for.',
    )
