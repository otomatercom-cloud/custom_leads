from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    voxbay_uid = fields.Char(string='Voxbay UID')
    voxbay_upin = fields.Char(string='Voxbay UPIN')
    voxbay_callerid = fields.Char(string='Voxbay Caller ID (DID)')

    bonvoice_username = fields.Char(string='Bonvoice Username')
    bonvoice_password = fields.Char(string='Bonvoice Password')
    bonvoice_leg_a_caller_id = fields.Char(string='Bonvoice Leg A Caller ID')
    bonvoice_leg_b_caller_id = fields.Char(string='Bonvoice Leg B Caller ID')
    bonvoice_url = fields.Char(string='Bonvoice Auto Call API URL', default='https://backend.pbx.bonvoice.com/autoDialManagement/autoCallBridging/')

    meta_verify_token = fields.Char(string='Meta Verify Token', help='Custom string used for webhook verification')
    meta_page_access_token = fields.Char(string='Meta Page Access Token', help='Long-lived token for Graph API')

    # Call -> Lead automation toggles. When a Voxbay/Bonvoice call webhook
    # arrives and the phone number doesn't match any existing lead, these
    # control whether a new lead gets auto-created for it.
    auto_create_lead_incoming = fields.Boolean(
        string='Auto-Create Lead on Incoming Calls', default=True,
        help='When enabled, an unmatched incoming call automatically creates a new lead. '
             'Disable this if you don\'t want unknown incoming calls to create leads.'
    )
    auto_create_lead_outgoing = fields.Boolean(
        string='Auto-Create Lead on Outgoing Calls', default=False,
        help='When enabled, an unmatched outgoing call automatically creates a new lead. '
             'Leave this off if outgoing calls should only ever be made against leads that already exist.'
    )
