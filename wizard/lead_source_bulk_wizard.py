from odoo import fields, models, api, _
from odoo.exceptions import UserError


class LeadSourceBulkWizard(models.TransientModel):
    _name = 'lead.source.bulk.wizard'
    _description = 'Bulk Change Lead Source (Super Admin Override)'

    leads_source = fields.Many2one(
        'leads.sources', string='New Leads Source', required=True,
        options="{'no_create': True}",
    )
    lead_count = fields.Integer(string='Leads Selected', compute='_compute_lead_count')
    note = fields.Char(
        string='Note', readonly=True,
        default=_('If the selected leads have a Source Campaign that belongs to a '
                   'different Leads Source, it is left as-is — use "Bulk Change '
                   'Source Campaign" afterward if it also needs updating.'),
    )

    def _compute_lead_count(self):
        for rec in self:
            rec.lead_count = len(self.env.context.get('active_ids', []))

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('custom_leads.group_super_admin'):
            raise UserError(_('Only Super Admins can bulk-change Leads Source.'))

        active_ids = self.env.context.get('active_ids', [])
        if not active_ids:
            raise UserError(_('No leads selected. Please select leads from the list view first.'))

        leads = self.env['leads.logic'].browse(active_ids)
        leads.sudo().write({'leads_source': self.leads_source.id})

        for lead in leads:
            lead.message_post(
                body=_('Leads Source bulk-changed to "%s" by Super Admin %s.') % (
                    self.leads_source.name, self.env.user.name,
                )
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Leads Source Updated'),
                'message': _('%d lead(s) set to "%s".') % (len(leads), self.leads_source.name),
                'type': 'success',
                'sticky': False,
            },
        }
