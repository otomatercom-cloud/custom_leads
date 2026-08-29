from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    voxbay_uid = fields.Char(related='company_id.voxbay_uid', string='Voxbay UID', readonly=False)
    voxbay_upin = fields.Char(related='company_id.voxbay_upin', string='Voxbay UPIN', readonly=False)
    voxbay_callerid = fields.Char(related='company_id.voxbay_callerid', string='Voxbay Caller ID (DID)', readonly=False)

    bonvoice_username = fields.Char(related='company_id.bonvoice_username', string='Bonvoice Username', readonly=False)
    bonvoice_password = fields.Char(related='company_id.bonvoice_password', string='Bonvoice Password', readonly=False)
    bonvoice_leg_a_caller_id = fields.Char(related='company_id.bonvoice_leg_a_caller_id', string='Bonvoice Leg A Caller ID', readonly=False)
    bonvoice_leg_b_caller_id = fields.Char(related='company_id.bonvoice_leg_b_caller_id', string='Bonvoice Leg B Caller ID', readonly=False)
    bonvoice_url = fields.Char(related='company_id.bonvoice_url', string='Bonvoice Auto Call API URL', readonly=False)

    meta_verify_token = fields.Char(related='company_id.meta_verify_token', string='Meta Verify Token', readonly=False)
    meta_page_access_token = fields.Char(related='company_id.meta_page_access_token', string='Meta Page Access Token', readonly=False)

    auto_create_lead_incoming = fields.Boolean(related='company_id.auto_create_lead_incoming', string='Auto-Create Lead on Incoming Calls', readonly=False)
    auto_create_lead_outgoing = fields.Boolean(related='company_id.auto_create_lead_outgoing', string='Auto-Create Lead on Outgoing Calls', readonly=False)
