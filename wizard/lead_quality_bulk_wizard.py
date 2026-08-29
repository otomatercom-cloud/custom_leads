from odoo import fields, models, api, _
from odoo.exceptions import UserError


class LeadQualityBulkWizard(models.TransientModel):
    _name = 'lead.quality.bulk.wizard'
    _description = 'Bulk Change Lead Quality (Super Admin Override)'

    # Kept in sync with leads.logic.lead_quality — intentionally duplicated
    # here rather than referenced, since a TransientModel selection field
    # can't read another model's field definition at build time.
    lead_quality = fields.Selection(
        [
            ('new', '🆕  New'), ('first_attempt', '🎯 First Attempt'),
            ('waiting_for_admission', '⏳  Waiting for Admission'), ('admission', '🎓  Admission'),
            ('hot', '🔥  Hot'), ('warm', '🌞  Warm'), ('cold', '❄️  Cold'),
            ('bad_lead', '⚠️  Language Barrier'), ('crash_lead', '💥  Crash Lead'),
            ('not_responding', '🔕  Ringing Not Responding'),
            ('call_later', '📞  Call Later'), ('may_be_later', '🔔 May Be Later'),
            ('follow_up', '⏰  Follow Up'), ('not_reachable', '🚫  Not Reachable'),
            ('logic_students', 'Logic Students'),
            ('already_joined', '✅ Already Joined'), ('joined_other_institute', '🏫 Joined Other Institute'),
            ('wrong_number', '📵 Wrong number'), ('not_enquiry', '🛑 Not Enquiry')
        ],
        string='New Lead Quality', required=True
    )
    lead_count = fields.Integer(string='Leads Selected', compute='_compute_lead_count')
    note = fields.Char(
        string='Note', readonly=True,
        default=_('This bypasses the usual Course Interested / Follow-Up / '
                   'Admission-stage validations. Only Super Admins can do this.'),
    )

    def _compute_lead_count(self):
        for rec in self:
            rec.lead_count = len(self.env.context.get('active_ids', []))

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('custom_leads.group_super_admin'):
            raise UserError(_('Only Super Admins can bulk-change Lead Quality.'))

        active_ids = self.env.context.get('active_ids', [])
        if not active_ids:
            raise UserError(_('No leads selected. Please select leads from the list view first.'))

        leads = self.env['leads.logic'].browse(active_ids)

        # skip_lead_quality_validation bypasses the Course Interested /
        # Follow-Up-required constraint (_check_course_and_followup_required)
        # for this write only — a deliberate Super Admin override, not a
        # general-purpose bypass.
        leads.sudo().with_context(skip_lead_quality_validation=True).write({
            'lead_quality': self.lead_quality,
        })

        for lead in leads:
            lead.message_post(
                body=_('Lead Quality bulk-changed to "%s" by Super Admin %s (validation overridden).') % (
                    dict(self._fields['lead_quality'].selection).get(self.lead_quality),
                    self.env.user.name,
                )
            )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Lead Quality Updated'),
                'message': _('%d lead(s) set to "%s".') % (
                    len(leads), dict(self._fields['lead_quality'].selection).get(self.lead_quality)
                ),
                'type': 'success',
                'sticky': False,
            },
        }
