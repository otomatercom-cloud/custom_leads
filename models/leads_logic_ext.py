from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class LeadsLogicReEnquiryMixin(models.Model):
    """
    Extends leads.logic with:
      1.  re_enquiry_count  — smart-button counter on the lead form
      2.  action_open_re_enquiries — opens the re-enquiry list for this lead
      3.  create() override — intercepts duplicate mobile numbers and
          creates a Re-Enquiry record instead of raising a hard error
    """

    _inherit = 'leads.logic'

    # ── Smart button ──────────────────────────────────────────────────
    re_enquiry_count = fields.Integer(
        string='Re-Enquiries',
        compute='_compute_re_enquiry_count',
    )

    @api.depends('phone_number')
    def _compute_re_enquiry_count(self):
        for rec in self:
            rec.re_enquiry_count = self.env['lead.re.enquiry'].search_count(
                [('lead_id', '=', rec.id)]
            )

    def action_open_re_enquiries(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Re-Enquiries'),
            'res_model': 'lead.re.enquiry',
            'view_mode': 'list,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {'default_lead_id': self.id},
        }

    # ── Duplicate-aware create ────────────────────────────────────────

    @api.model
    def create(self, values):
        """
        If the incoming mobile number already exists in the same
        academic year, create a Re-Enquiry record linked to the
        original lead and raise a friendly ValidationError so the
        user knows what happened.

        The original lead (and its officer) are left untouched.
        """
        phone_raw = values.get('phone_number', '').replace(' ', '')
        academic_year = values.get(
            'academic_year_of_course_attend', '2025-2026'
        )

        if phone_raw and academic_year:
            last_10 = phone_raw[-10:]
            existing = self.sudo().search([
                ('phone_number', 'like', '%' + last_10),
                ('academic_year_of_course_attend', '=', academic_year),
            ], limit=1)

            if existing:
                # Build a Re-Enquiry record from whatever the caller provided
                re_enquiry_vals = {
                    'lead_id': existing.id,
                    'leads_source': values.get('leads_source'),
                    'campaign': values.get('campaign'),
                    'digital_lead_source': values.get('digital_lead_source'),
                    'course_interested': values.get('course_interested'),
                    'remarks': values.get('remarks'),
                    'review_required': True,
                    'review_state': 'pending',
                }
                # Drop None values so model defaults kick in
                re_enquiry_vals = {
                    k: v for k, v in re_enquiry_vals.items() if v is not None
                }
                re_enquiry = self.env['lead.re.enquiry'].sudo().create(
                    re_enquiry_vals
                )

                owner_name = existing.lead_owner.name if existing.lead_owner else _('Unknown')
                raise ValidationError(
                    _(
                        "📋 Duplicate Mobile Detected!\n\n"
                        "The number %(phone)s already has a lead in %(year)s "
                        "(Ref: %(ref)s), assigned to %(officer)s.\n\n"
                        "A Re-Enquiry record %(re_ref)s has been created and "
                        "linked to the original lead. The Team Lead has been "
                        "notified for review.\n\n"
                        "No new lead was created."
                    ) % {
                        'phone': phone_raw,
                        'year': academic_year,
                        'ref': existing.reference_no,
                        'officer': owner_name,
                        're_ref': re_enquiry.reference_no,
                    }
                )

        return super().create(values)
