from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class LeadAutoAssignPool(models.Model):
    """Round-robin auto-assignment pool.

    Configured by Team Leads / Managers / Admins. When a new lead arrives with no
    owner chosen, it is given to the next Admission Officer of the pool, in turn.
    """
    _name = 'lead.auto.assign.pool'
    _description = 'Lead Auto Assign Pool (Round Robin)'
    _inherit = ['mail.thread']
    _order = 'id'

    name = fields.Char(string='Pool Name', required=True, default='Auto Assign Pool', tracking=True)
    active = fields.Boolean(default=True)
    is_enabled = fields.Boolean(string='Auto Assign Enabled', default=True, tracking=True,
                                help='Switch off to stop automatic assignment without deleting the pool.')
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company)
    member_ids = fields.Many2many(
        'res.users', 'lead_auto_assign_pool_user_rel', 'pool_id', 'user_id',
        string='Admission Officers in Pool', tracking=True,
        domain=lambda self: [('groups_id', 'in', [self.env.ref('custom_leads.group_lead_users').id])],
        help='New leads are given to these officers one after another, in turn.',
    )
    member_count = fields.Integer(compute='_compute_member_count', string='Officers')
    last_user_id = fields.Many2one('res.users', string='Last Assigned To', readonly=True, copy=False)
    last_assigned_on = fields.Datetime(string='Last Assigned On', readonly=True, copy=False)
    assigned_total = fields.Integer(string='Leads Auto-Assigned', readonly=True, copy=False)

    @api.depends('member_ids')
    def _compute_member_count(self):
        for rec in self:
            rec.member_count = len(rec.member_ids)

    @api.constrains('is_enabled', 'company_id', 'active')
    def _check_one_enabled_pool(self):
        for rec in self:
            if rec.is_enabled and rec.active:
                other = self.search_count([
                    ('id', '!=', rec.id), ('is_enabled', '=', True),
                    ('active', '=', True), ('company_id', '=', rec.company_id.id),
                ])
                if other:
                    raise ValidationError(_('Only one enabled Auto Assign Pool is allowed per company.'))

    @api.model
    def _next_employee(self):
        """Return the hr.employee of the next officer in rotation (or empty recordset)."""
        pool = self.sudo().search([
            ('is_enabled', '=', True), ('active', '=', True),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not pool:
            return self.env['hr.employee']
        # lock the pool row so two leads arriving together never get the same officer
        self.env.cr.execute('SELECT id FROM lead_auto_assign_pool WHERE id = %s FOR UPDATE', (pool.id,))
        pool.invalidate_recordset(['last_user_id'])

        candidates = []
        for user in pool.member_ids.filtered('active').sorted('id'):
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
            if emp:
                candidates.append((user, emp))
        if not candidates:
            return self.env['hr.employee']

        pick = candidates[0]
        if pool.last_user_id:
            for idx, (user, _emp) in enumerate(candidates):
                if user.id == pool.last_user_id.id:
                    pick = candidates[(idx + 1) % len(candidates)]
                    break
            else:
                # last officer was removed from pool: continue with the next higher id
                higher = [c for c in candidates if c[0].id > pool.last_user_id.id]
                pick = higher[0] if higher else candidates[0]
        pool.write({
            'last_user_id': pick[0].id,
            'last_assigned_on': fields.Datetime.now(),
            'assigned_total': pool.assigned_total + 1,
        })
        return pick[1]
