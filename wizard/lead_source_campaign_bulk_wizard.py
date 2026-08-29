from odoo import fields, models, api, _
from odoo.exceptions import UserError


class LeadSourceCampaignBulkWizard(models.TransientModel):
    _name = 'lead.source.campaign.bulk.wizard'
    _description = 'Bulk Change Source Campaign (Super Admin Override)'

    source_campaign_id = fields.Many2one(
        'lead.source.campaign', string='New Source Campaign', required=True,
        options="{'no_create': True}",
    )
    lead_count = fields.Integer(string='Leads Selected', compute='_compute_lead_count')
    note = fields.Char(
        string='Note', readonly=True,
        default=_('This also updates each lead\'s Leads Source to the Campaign\'s '
                   'parent Source automatically.'),
    )

    def _compute_lead_count(self):
        for rec in self:
            rec.lead_count = len(self.env.context.get('active_ids', []))

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('custom_leads.group_super_admin'):
            raise UserError(_('Only Super Admins can bulk-change Source Campaign.'))

        active_ids = self.env.context.get('active_ids', [])
        if not active_ids:
            raise UserError(_('No leads selected. Please select leads from the list view first.'))

        leads = self.env['leads.logic'].browse(active_ids)
        # leads.logic.write() already auto-fills leads_source from the
        # campaign's parent lead_source_id when source_campaign_id is set
        # without an explicit leads_source in vals — see LeadsForm.write().
        leads.sudo().write({'source_campaign_id': self.source_campaign_id.id})

        for lead in leads:
            lead.message_post(
                body=_('Source Campaign bulk-changed to "%s" by Super Admin %s.') % (
                    self.source_campaign_id.name, self.env.user.name,
                )
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Source Campaign Updated'),
                'message': _('%d lead(s) set to "%s".') % (len(leads), self.source_campaign_id.name),
                'type': 'success',
                'sticky': False,
            },
        }
