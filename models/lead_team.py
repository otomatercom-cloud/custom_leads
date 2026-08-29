from odoo import fields, models, api, _


class LeadTeam(models.Model):
    _name = 'lead.team'
    _description = 'Admission Lead Team'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(string='Team Name', required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    color = fields.Integer(string='Color')

    # A team can have one or more Team Leads
    team_lead_ids = fields.Many2many(
        'res.users', 'lead_team_team_lead_rel', 'team_id', 'user_id',
        string='Team Leads', tracking=True,
        domain=lambda self: [
            ('groups_id', 'in', [self.env.ref('custom_leads.group_lead_team_lead').id])
        ],
        help='Users in this list can view leads belonging to every member of this team.',
    )

    # Admission Officers placed in this team (reverse of res.users.admission_team_id)
    member_ids = fields.One2many(
        'res.users', 'admission_team_id', string='Team Members (Admission Officers)',
    )

    member_count = fields.Integer(string='Members', compute='_compute_member_count')
    lead_count = fields.Integer(string='Leads', compute='_compute_lead_count')

    @api.depends('member_ids')
    def _compute_member_count(self):
        for rec in self:
            rec.member_count = len(rec.member_ids)

    def _compute_lead_count(self):
        for rec in self:
            rec.lead_count = self.env['leads.logic'].sudo().search_count(
                [('lead_owner.admission_team_id', '=', rec.id)]
            )

    def action_view_members(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Team Members'),
            'res_model': 'res.users',
            'view_mode': 'tree,form',
            'domain': [('admission_team_id', '=', self.id)],
            'context': {'default_admission_team_id': self.id},
        }

    def action_view_leads(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Team Leads'),
            'res_model': 'leads.logic',
            'view_mode': 'tree,form',
            'domain': [('lead_owner.admission_team_id', '=', self.id)],
        }

    def action_bulk_assign_members(self):
        """Open the bulk assignment wizard pre-filled with this team."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bulk Assign Admission Officers'),
            'res_model': 'team.bulk.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_team_id': self.id},
        }


class ResUsersAdmissionTeam(models.Model):
    _inherit = 'res.users'

    admission_team_id = fields.Many2one(
        'lead.team', string='Admission Team',
        help='Team this Admission Officer / Team Lead belongs to.',
    )
    is_admission_officer = fields.Boolean(
        string='Is Admission Officer', compute='_compute_is_admission_officer'
    )

    def _compute_is_admission_officer(self):
        group = self.env.ref('custom_leads.group_lead_users', raise_if_not_found=False)
        for user in self:
            user.is_admission_officer = bool(group) and group in user.groups_id


class HrEmployeeAdmissionTeam(models.Model):
    _inherit = 'hr.employee'

    admission_team_id = fields.Many2one(
        'lead.team', string='Admission Team',
        related='user_id.admission_team_id', store=True, readonly=True,
    )
