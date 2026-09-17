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

        is_manager = user.has_group('custom_leads.group_lead_manager')
        is_super = user.has_group('custom_leads.group_super_admin')
        is_odoo_admin = user.has_group('base.group_system')
        is_tl = user.has_group('custom_leads.group_lead_team_lead')
        employee = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        if is_manager or is_super or is_odoo_admin:
            role = 'manager'
            emp_domain = [('admission_team_id', '!=', False)]
        elif is_tl:
            role = 'tl'
            teams = self.env['lead.team'].sudo().search([('team_lead_ids', 'in', [user.id])])
            emp_domain = [('admission_team_id', 'in', teams.ids)] if teams else [('id', '=', 0)]
        else:
            role = 'officer'
            emp_domain = [('id', '=', employee.id)] if employee else [('id', '=', 0)]

        employees = self.env['hr.employee'].sudo().search(emp_domain + [('active', '=', True)])

        empty_kpi = dict(assigned=0, total_calls=0, connected=0, outgoing=0, incoming=0,
                          called_leads=0, pending=0, recordings=0, talk_seconds=0, talk_time='00:00:00')
        if not employees:
            return {'role': role, 'date_filter': date_filter, 'date_from': str(date_from),
                    'date_to': str(date_to), 'kpi': empty_kpi, 'teams': []}

        emp_ids = employees.ids

        # ── 1. Telephony stats per employee, ONE query ───────────────────
        cr.execute(
            """
            SELECT e.id,
                   COUNT(cl.id)                                                       AS total_calls,
                   COUNT(cl.id) FILTER (WHERE cl.call_type = 'outgoing')              AS outgoing,
                   COUNT(cl.id) FILTER (WHERE cl.call_type = 'incoming')              AS incoming,
                   COUNT(cl.id) FILTER (WHERE cl.is_connected)                        AS connected,
                   COUNT(cl.id) FILTER (WHERE cl.has_recording)                       AS recordings,
                   COALESCE(SUM(cl.duration_seconds), 0)                              AS talk_seconds
            FROM   hr_employee e
            LEFT JOIN res_users u ON u.id = e.user_id
            LEFT JOIN lead_call_log cl
                   ON cl.user_id = u.id
                  AND cl.call_date >= %s AND cl.call_date <= %s
            WHERE  e.id = ANY(%s)
            GROUP  BY e.id
            """,
            (date_from, date_to, emp_ids),
        )
        call_map = {row[0]: row[1:] for row in cr.fetchall()}

        # ── 2. Today's dialing-list stats per employee (call.campaign) ───
        Campaign = self.env['call.campaign'].sudo()
        campaigns = Campaign.search([('employee_id', 'in', emp_ids)])
        camp_map = {c.employee_id.id: c for c in campaigns if c.employee_id}

        missing_ids = [eid for eid in emp_ids if eid not in camp_map]
        if missing_ids:
            today_str = today.strftime('%Y-%m-%d')
            name_to_emp = {}
            for emp in self.env['hr.employee'].sudo().browse(missing_ids):
                name_to_emp['Daily Campaign - %s - %s' % (emp.name, today_str)] = emp.id
            if name_to_emp:
                for camp in Campaign.search([('name', 'in', list(name_to_emp.keys()))]):
                    emp_id = name_to_emp.get(camp.name)
                    if emp_id:
                        camp_map[emp_id] = camp

        # ── 3. Team / role lookups (small, human-scale — plain ORM) ──────
        teams = self.env['lead.team'].sudo().search([])
        team_by_id = {t.id: t for t in teams}
        tl_group = self.env.ref('custom_leads.group_lead_team_lead', raise_if_not_found=False)
        tl_user_ids = set(tl_group.users.ids) if tl_group else set()

        def build_agent_row(emp):
            stats = call_map.get(emp.id, (0, 0, 0, 0, 0, 0))
            total_calls, outgoing, incoming, connected, recordings, talk_seconds = stats
            not_connected = total_calls - connected
            connect_pct = round((connected / total_calls) * 100) if total_calls else 0
            avg_seconds = round(talk_seconds / connected) if connected else 0

            camp = camp_map.get(emp.id)
            assigned = camp.lead_count if camp else 0
            called_leads = camp.called_count if camp else 0
            pending = camp.pending_count if camp else 0

            team = emp.admission_team_id
            reporting_tl = ', '.join(team.team_lead_ids.mapped('name')) if team else ''
            role_label = 'Team Lead' if (emp.user_id and emp.user_id.id in tl_user_ids) else 'Officer'

            return {
                'employee_id': emp.id,
                'user_id': emp.user_id.id if emp.user_id else False,
                'name': emp.name,
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
        for emp in employees.sorted(key=lambda e: e.name or ''):
            team = emp.admission_team_id
            key = team.id if team else 0
            if key not in teams_out:
                teams_out[key] = {'id': key, 'name': team.name if team else 'Unassigned', 'agents': []}
                order.append(key)
            teams_out[key]['agents'].append(build_agent_row(emp))

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
