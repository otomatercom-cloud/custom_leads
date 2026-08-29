from odoo import fields, models, api, _
from odoo.exceptions import UserError


class LeadRoundRobinWizard(models.TransientModel):
    _name = 'lead.round.robin.wizard'
    _description = 'Bulk Assign Leads to Team (Round-Robin)'

    team_id = fields.Many2one(
        'lead.team', string='Team', required=True,
        help='Leads will be distributed round-robin across this team\'s members.',
    )
    member_ids = fields.Many2many(
        'res.users',
        compute='_compute_member_ids',
        string='Team Members',
    )
    member_preview = fields.Text(
        string='Members (in rotation order)',
        compute='_compute_member_ids',
    )
    lead_count = fields.Integer(
        string='Leads Selected', compute='_compute_lead_count',
    )

    @api.depends('team_id')
    def _compute_member_ids(self):
        for rec in self:
            if rec.team_id:
                members = rec.team_id.member_ids
                rec.member_ids = members
                if members:
                    names = [u.name for u in members]
                    rec.member_preview = ' → '.join(names) + '  (repeats)'
                else:
                    rec.member_preview = _('No members in this team yet.')
            else:
                rec.member_ids = False
                rec.member_preview = ''

    def _compute_lead_count(self):
        for rec in self:
            active_ids = self.env.context.get('active_ids', [])
            rec.lead_count = len(active_ids)

    def action_assign(self):
        self.ensure_one()
        active_ids = self.env.context.get('active_ids', [])
        if not active_ids:
            raise UserError(_('No leads selected. Please select leads from the list view first.'))

        members = self.team_id.member_ids
        if not members:
            raise UserError(_(
                'Team "%s" has no members. Please add Admission Officers to the team first.'
            ) % self.team_id.name)

        leads = self.env['leads.logic'].browse(active_ids)

        # Build a list of employees for round-robin (via user → employee)
        employees = []
        for user in members:
            emp = self.env['hr.employee'].sudo().search(
                [('user_id', '=', user.id)], limit=1
            )
            if emp:
                employees.append(emp)

        if not employees:
            raise UserError(_(
                'No team members have linked Employee records. '
                'Please ensure each Admission Officer has an Employee profile.'
            ))

        # Distribute leads round-robin
        total_members = len(employees)
        assigned_counts = {emp.id: 0 for emp in employees}

        for idx, lead in enumerate(leads):
            emp = employees[idx % total_members]
            lead.lead_owner = emp.id
            assigned_counts[emp.id] += 1

        # Post a summary message on each assigned lead (chatter)
        for lead in leads:
            lead.message_post(
                body=_('Lead assigned via Team Round-Robin to %s (Team: %s)') % (
                    lead.lead_owner.name, self.team_id.name
                )
            )

        # Summary notification
        summary_lines = [
            _('%s → %d lead(s)') % (emp.name, assigned_counts[emp.id])
            for emp in employees
        ]
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Round-Robin Assignment Complete'),
                'message': _('%d lead(s) distributed across %d member(s):\n%s') % (
                    len(leads), len(employees), '\n'.join(summary_lines)
                ),
                'type': 'success',
                'sticky': False,
            },
        }
