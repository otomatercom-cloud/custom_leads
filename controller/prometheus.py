from odoo import http
from odoo.http import request, Response

class PrometheusMetricsController(http.Controller):

    @http.route('/metrics', type='http', auth='public', csrf=False, methods=['GET'])
    def metrics(self, **kw):
        leads = request.env['leads.logic'].sudo()
        
        # Group leads by lead owner, quality, and state
        domain = []
        # In Odoo, we group by these fields to get the counts
        grouped_leads = leads.read_group(
            domain,
            ['id'],
            ['lead_owner', 'lead_quality', 'state'],
            lazy=False
        )

        metrics_output = []
        metrics_output.append("# HELP odoo_leads_total Total number of leads grouped by owner, quality, and state")
        metrics_output.append("# TYPE odoo_leads_total gauge")

        for group in grouped_leads:
            # lead_owner can be False or a tuple (id, name)
            owner_data = group.get('lead_owner')
            owner_name = owner_data[1] if isinstance(owner_data, tuple) else (owner_data or 'Unassigned')
            
            quality = group.get('lead_quality') or 'none'
            state = group.get('state') or 'none'
            count = group.get('__count', 0)

            # Sanitize labels to remove double quotes and newlines
            owner_name = str(owner_name).replace('"', '\\"').replace('\n', ' ')
            quality = str(quality).replace('"', '\\"')
            state = str(state).replace('"', '\\"')

            metrics_output.append(
                f'odoo_leads_total{{owner="{owner_name}",quality="{quality}",state="{state}"}} {count}'
            )

        # Add metric for total admission staff
        metrics_output.append("# HELP odoo_admission_officers_total Total number of admission officers (employees)")
        metrics_output.append("# TYPE odoo_admission_officers_total gauge")
        
        # Count all employees (admission officers)
        officers_count = request.env['hr.employee'].sudo().search_count([])
        metrics_output.append(f'odoo_admission_officers_total {officers_count}')

        response_body = "\n".join(metrics_output) + "\n"

        headers = [
            ('Content-Type', 'text/plain; version=0.0.4'),
            ('Cache-Control', 'no-cache, no-store, must-revalidate'),
        ]
        return Response(response_body, headers=headers)
