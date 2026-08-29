from odoo import models, fields

class ResUsers(models.Model):
    _inherit = 'res.users'

    voxbay_user_no = fields.Char(string='Voxbay Extension Number', help='Agent extension number used for Voxbay click-to-call')
    bonvoice_agent_number = fields.Char(string='Bourn Voice Agent Number', help='Agent extension or phone number used for Bourn Voice click-to-call (Leg A)')
