from odoo import fields,models,api, _

class LeadsSources(models.Model):
    _name = 'leads.sources'
    _inherit = 'mail.thread'
    _description = 'Leads Sources'

    name = fields.Char('Name', required=True, tracking=1)
    digital_lead = fields.Boolean('Digital Lead', default=False)
    source = fields.Selection([('inbound_source', 'Inbound Source'), ('outbound_source', 'Outbound Source')],
                              string="Source")
    # Lead Source is the PARENT (e.g. "Digital"). Many Source Campaigns can
    # be added under one Lead Source (e.g. "Urban Chat Leads Meta",
    # "Facebook Meta", "Justdial" all under "Digital"). This one2many lets
    # an admin add/manage all of a source's campaigns directly from the
    # Lead Source form instead of going to Source Campaigns separately.
    campaign_ids = fields.One2many('lead.source.campaign', 'lead_source_id', string='Campaigns')
    campaign_count = fields.Integer(string='Campaigns', compute='_compute_campaign_count')

    def _compute_campaign_count(self):
        for rec in self:
            rec.campaign_count = len(rec.campaign_ids)


# --------------------------------------------------------------------------
# Model: lead.source.campaign
# Description: Editable list of marketing/source campaigns that can be
# tagged on a lead, independent of the existing 'leads_source' and
# 'campaign' fields. Managed under Leads > Configuration > Source Campaigns.
# Each campaign belongs to one parent Lead Source (e.g. "Urban Chat Leads
# Meta" -> parent "Digital"), so picking a Campaign on a lead can auto-fill
# the parent Lead Source.
# --------------------------------------------------------------------------
class LeadSourceCampaign(models.Model):
    _name = 'lead.source.campaign'
    _description = 'Lead Source Campaign'
    _order = 'sequence, name'

    name = fields.Char('Name', required=True)
    sequence = fields.Integer('Sequence', default=10)
    active = fields.Boolean('Active', default=True)
    lead_source_id = fields.Many2one('leads.sources', string='Parent Lead Source', tracking=1)