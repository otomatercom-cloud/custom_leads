from odoo import fields, models, api, _
from odoo.exceptions import UserError


class TeamBulkAssignWizard(models.TransientModel):
    _name = 'team.bulk.assign.wizard'
    _description = 'Bulk Assign Admission Officers to a Team'

    team_id = fields.Many2one('lead.team', string='Team', required=True)
    team_lead_ids = fields.Many2many(
        related='team_id.team_lead_ids', string='Team Lead(s)', readonly=True
    )
    user_ids = fields.Many2many(
        'res.users', 'team_bulk_assign_user_rel', 'wizard_id', 'user_id',
        string='Admission Officers',
        domain=lambda self: [
            ('groups_id', 'in', [self.env.ref('custom_leads.group_lead_users').id])
        ],
        help='Select the Admission Officers to place into this team.',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # When launched from a multi-select action on the Admission Officers list
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids')
        if active_model == 'res.users' and active_ids:
            res['user_ids'] = [(6, 0, active_ids)]
        return res

    def action_assign(self):
        self.ensure_one()
        if not self.user_ids:
            raise UserError(_('Please select at least one Admission Officer to assign.'))
        self.user_ids.sudo().write({'admission_team_id': self.team_id.id})
        self.team_id.message_post(
            body=_('%s officer(s) bulk-assigned to this team: %s') % (
                len(self.user_ids), ', '.join(self.user_ids.mapped('name'))
            )
        )
        return {'type': 'ir.actions.act_window_close'}
