from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Model: lead.re.enquiry
# Description: Stores repeated enquiries linked to an existing lead.
#
# When a new enquiry arrives with a mobile number that already exists in
# the same academic year, instead of creating a duplicate lead a
# Re-Enquiry record is created and linked to the original.
# The original Admission Officer keeps full ownership; all Team Leads
# receive an inbox notification for review.
# --------------------------------------------------------------------------
class LeadReEnquiry(models.Model):
    _name = 'lead.re.enquiry'
    _description = 'Lead Re-Enquiry'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'enquiry_date desc'
    _rec_name = 'reference_no'

    # ── Identification ─────────────────────────────────────────────────────
    reference_no = fields.Char(
        string='Reference',
        default=lambda self: _('New'),
        copy=False,
        readonly=True,
        tracking=True,
    )

    # ── Link to original lead ──────────────────────────────────────────────
    lead_id = fields.Many2one(
        'leads.logic',
        string='Original Lead',
        required=True,
        ondelete='cascade',
        tracking=True,
        index=True,
    )

    # Read-only mirrors — keeps the re-enquiry form self-contained for review
    lead_name = fields.Char(
        string='Student Name',
        related='lead_id.name',
        readonly=True,
        store=True,
    )
    lead_phone = fields.Char(
        string='Mobile',
        related='lead_id.phone_number',
        readonly=True,
        store=True,
    )
    lead_owner_id = fields.Many2one(
        'hr.employee',
        string='Assigned Officer',
        related='lead_id.lead_owner',
        readonly=True,
        store=True,
    )
    lead_quality = fields.Selection(
        related='lead_id.lead_quality',
        readonly=True,
        string='Current Stage',
        store=True,
    )
    lead_academic_year = fields.Selection(
        related='lead_id.academic_year_of_course_attend',
        readonly=True,
        string='Academic Year',
        store=True,
    )

    # ── Old Source (original lead's source — snapshot at re-enquiry time) ──
    old_source_id = fields.Many2one(
        'leads.sources',
        string='Old Source',
        readonly=True,
        store=True,
        tracking=True,
        help='Source of the original lead at the time this re-enquiry was created.',
    )

    # ── New-enquiry metadata ───────────────────────────────────────────────
    enquiry_date = fields.Date(
        string='Enquiry Date',
        default=fields.Date.today,
        required=True,
        tracking=True,
    )
    leads_source = fields.Many2one(
        'leads.sources',
        string='New Source',
        tracking=True,
    )
    campaign = fields.Selection(
        [
            ('CA Weekend Thrissur', 'CA Weekend Thrissur'),
            ('CA Weekend Ernakulam', 'CA Weekend Ernakulam'),
            ('CA Weekend Trivandrum', 'CA Weekend Trivandrum'),
            ('CA Weekend Calicut', 'CA Weekend Calicut'),
            ('CA Weekend Perintalmanna', 'CA Weekend Perintalmanna'),
        ],
        string='Campaign',
        tracking=True,
    )
    digital_lead_source = fields.Selection(
        [
            ('just_dial', 'Just Dial'),
            ('youtube_google', 'Youtube - Google'),
            ('whatsapp_campaign', 'Whatsapp Campaign'),
            ('messenger', 'Messenger'),
            ('facebook', 'Facebook'),
            ('linkedin', 'Linkedin'),
            ('instagram', 'Instagram'),
            ('whatsapp_meta', 'Whatsapp Meta'),
            ('website', 'Website'),
            ('google', 'Google'),
        ],
        string='Digital Source',
        tracking=True,
    )
    course_interested = fields.Char(string='Course Interested', tracking=True)
    remarks = fields.Text(string='Remarks / Notes', tracking=True)

    # ── Review workflow ────────────────────────────────────────────────────
    review_required = fields.Boolean(
        string='Team Lead Review Required',
        default=True,
        tracking=True,
    )
    review_state = fields.Selection(
        [
            ('pending', 'Pending Review'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('merged', 'Merged to Lead'),
        ],
        string='Review Status',
        default='pending',
        tracking=True,
    )
    reviewed_by = fields.Many2one(
        'res.users',
        string='Reviewed By',
        readonly=True,
        tracking=True,
    )
    reviewed_on = fields.Datetime(string='Reviewed On', readonly=True)
    review_notes = fields.Text(string='Review Notes')
    created_by = fields.Many2one(
        'res.users',
        string='Created By',
        default=lambda self: self.env.user,
        readonly=True,
    )

    # ── ORM overrides ──────────────────────────────────────────────────────

    @api.model
    def create(self, vals):
        if vals.get('reference_no', _('New')) == _('New'):
            vals['reference_no'] = (
                self.env['ir.sequence'].next_by_code('lead.re.enquiry') or _('New')
            )
        # Snapshot old source from the original lead
        if vals.get('lead_id') and not vals.get('old_source_id'):
            lead = self.env['leads.logic'].browse(vals['lead_id'])
            if lead.leads_source:
                vals['old_source_id'] = lead.leads_source.id
        record = super(LeadReEnquiry, self).create(vals)
        record._notify_team_leads()
        record._post_chatter_on_lead()
        return record

    # ── Actions ────────────────────────────────────────────────────────────

    def action_approve(self):
        """Approve the re-enquiry: update lead's source to new source."""
        for rec in self:
            if rec.review_state not in ('pending',):
                continue
            vals = {
                'review_state': 'approved',
                'reviewed_by': self.env.user.id,
                'reviewed_on': fields.Datetime.now(),
            }
            rec.write(vals)
            # Update lead source to new source if provided
            if rec.leads_source:
                rec.lead_id.sudo().write({'leads_source': rec.leads_source.id})
                rec.lead_id.message_post(
                    body=_(
                        "🔁 Re-Enquiry <b>%s</b> approved by <b>%s</b>.<br/>"
                        "Source updated: <b>%s</b> → <b>%s</b>"
                    ) % (
                        rec.reference_no,
                        self.env.user.name,
                        rec.old_source_id.name if rec.old_source_id else '—',
                        rec.leads_source.name,
                    )
                )
            else:
                rec.lead_id.message_post(
                    body=_(
                        "🔁 Re-Enquiry <b>%s</b> approved by <b>%s</b>. "
                        "No new source provided — lead source unchanged."
                    ) % (rec.reference_no, self.env.user.name)
                )

    def action_reject(self):
        """Reject the re-enquiry without changing lead source."""
        for rec in self:
            if rec.review_state not in ('pending',):
                continue
            rec.write({
                'review_state': 'rejected',
                'reviewed_by': self.env.user.id,
                'reviewed_on': fields.Datetime.now(),
            })
            rec.lead_id.message_post(
                body=_(
                    "🔁 Re-Enquiry <b>%s</b> rejected by <b>%s</b>."
                ) % (rec.reference_no, self.env.user.name)
            )

    def action_mark_reviewed(self):
        """Team Lead marks the re-enquiry as reviewed (legacy / kept for compat)."""
        self.ensure_one()
        self.write({
            'review_state': 'approved',
            'reviewed_by': self.env.user.id,
            'reviewed_on': fields.Datetime.now(),
        })
        if self.leads_source:
            self.lead_id.sudo().write({'leads_source': self.leads_source.id})
        self.lead_id.message_post(
            body=_("Re-Enquiry <b>%s</b> reviewed by <b>%s</b>.") % (
                self.reference_no, self.env.user.name
            )
        )

    def action_open_original_lead(self):
        """Open the parent lead form."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'leads.logic',
            'res_id': self.lead_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Scheduled cleanup ───────────────────────────────────────────────────

    @api.model
    def _cron_cleanup_old_re_enquiries(self, days_to_keep=2, batch_size=500):
        """Scheduled daily at 8:00 PM (IST) — keeps only the most recent
        `days_to_keep` days of Re-Enquiry data (by Enquiry Date) and
        permanently deletes everything older.

        days_to_keep=2 (default): keeps today's and yesterday's records,
        deletes anything with enquiry_date 2 or more days in the past.

        Deletes in batches of `batch_size` records, committing after each
        batch, instead of one giant unlink(). This matters a lot the
        FIRST time this runs against a table that's already grown huge:
        a single unlink() across tens of thousands of records (each one
        also cascading through its mail.message / mail.followers /
        activity records via mail.thread) can hold a long-running
        transaction and lock, or simply time out. Batching keeps each
        transaction small so the backlog drains steadily instead of
        risking a failed all-or-nothing run. Once the backlog is
        cleared, nightly runs only ever touch a small number of records
        (whatever crossed 2 days old since yesterday), so batching costs
        nothing going forward.

        Run by ir_cron_cleanup_old_re_enquiries
        (data/re_enquiry_cleanup_cron.xml). sudo() is used so the cron
        (running as a system user) can see and delete every record
        regardless of the usual record-rule ownership restrictions.
        """
        cutoff = fields.Date.today() - timedelta(days=days_to_keep - 1)
        stale_ids = self.sudo().search([('enquiry_date', '<', cutoff)]).ids
        total = len(stale_ids)
        deleted = 0
        for i in range(0, total, batch_size):
            batch = self.sudo().browse(stale_ids[i:i + batch_size])
            batch.unlink()
            deleted += len(batch)
            self.env.cr.commit()
            _logger.info(
                "Re-Enquiry cleanup: %s / %s deleted so far (Enquiry Date before %s).",
                deleted, total, cutoff,
            )
        _logger.info(
            "Re-Enquiry cleanup: finished — deleted %s record(s) with Enquiry Date "
            "before %s (keeping the last %s day(s) of data).",
            deleted, cutoff, days_to_keep,
        )
        return deleted

    def action_purge_old_re_enquiries(self):
        """Manual trigger for the same cleanup the 8 PM cron runs — a
        'Purge Old Data Now' button on the Re-Enquiry list, for whenever
        someone doesn't want to wait for tonight's scheduled run.
        Restricted to the same roles as the bulk Approve/Reject buttons.
        """
        if not (self.env.user.has_group('custom_leads.group_lead_team_lead')
                or self.env.user.has_group('custom_leads.group_lead_manager')
                or self.env.user.has_group('custom_leads.group_super_admin')):
            raise UserError(_("You don't have permission to purge Re-Enquiry data."))
        count = self._cron_cleanup_old_re_enquiries(days_to_keep=2)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Re-Enquiry Cleanup"),
                'message': _("Deleted %s record(s) older than 2 days.") % count,
                'type': 'success',
                'sticky': False,
            },
        }

    # ── Private helpers ────────────────────────────────────────────────────

    def _notify_team_leads(self):
        """Send an Odoo inbox notification to every Team Lead."""
        if not self.review_required:
            return
        group = self.env.ref('custom_leads.group_lead_team_lead', raise_if_not_found=False)
        if not group:
            return
        partners = group.users.mapped('partner_id')
        if not partners:
            return
        notification_ids = [
            (0, 0, {'res_partner_id': p.id, 'notification_type': 'inbox'})
            for p in partners
        ]
        self.env['mail.message'].create({
            'message_type': 'notification',
            'body': _(
                "🔁 Re-Enquiry <b>%s</b> received for lead <b>%s</b> (%s). "
                "Please review."
            ) % (self.reference_no, self.lead_id.name, self.lead_id.phone_number),
            'subject': _("Re-Enquiry Requires Review"),
            'model': 'lead.re.enquiry',
            'res_id': self.id,
            'partner_ids': [(4, p.id) for p in partners],
            'author_id': self.env.user.partner_id.id,
            'notification_ids': notification_ids,
        })

    def _post_chatter_on_lead(self):
        """Log the re-enquiry event on the original lead's chatter."""
        self.lead_id.message_post(
            body=_(
                "🔁 <b>New Re-Enquiry</b> recorded: <b>%s</b><br/>"
                "Old Source: %s &nbsp;|&nbsp; New Source: %s &nbsp;|&nbsp; Campaign: %s &nbsp;|&nbsp; Date: %s"
            ) % (
                self.reference_no,
                self.old_source_id.name if self.old_source_id else '—',
                self.leads_source.name if self.leads_source else '—',
                self.campaign or '—',
                self.enquiry_date,
            )
        )
