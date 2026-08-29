from odoo import http
from odoo.http import request, Response
import json
import requests
import logging

_logger = logging.getLogger(__name__)
class CallbackAPI(http.Controller):

    @http.route('/api/wp/callback', type='http', auth='public', csrf=False, methods=['POST', 'OPTIONS'])
    def wp_callback(self, **kw):
        # --- Handle CORS Preflight ---
        if request.httprequest.method == 'OPTIONS':
            headers = [
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'POST, OPTIONS'),
                ('Access-Control-Allow-Headers', 'Content-Type'),
            ]
            return Response(status=200, headers=headers)

        try:
            data = json.loads(request.httprequest.data.decode())

            # ✅ Get or create "Digital Leads" record in leads.sources
            digital_source = request.env['leads.sources'].sudo().search([('name', '=', 'Digital Leads')], limit=1)
            if not digital_source:
                digital_source = request.env['leads.sources'].sudo().create({'name': 'Digital Leads'})

            # ✅ Prepare lead data
            values = {
                'name': data.get('name'),
                'phone_number': data.get('phone'),
                'email_address': data.get('email'),
                'preferred_course': data.get('course'),
                'leads_source': digital_source.id,   # 👈 set default lead source
            }

            # ✅ Create the lead
            lead = request.env['leads.logic'].sudo().create(values)

            response = {'status': 'success', 'lead_id': lead.id}

        except Exception as e:
            response = {'status': 'error', 'message': str(e)}

        headers = [
            ('Content-Type', 'application/json'),
            ('Access-Control-Allow-Origin', '*'),
        ]
        return Response(json.dumps(response), headers=headers)

# class VoxbayWebhook(http.Controller):
#
#     @http.route(['/api/voxbay/callcenterbridging', '/callcenterbridging'], type='http', auth='public', csrf=False, methods=['POST', 'GET'])
#     def voxbay_webhook(self, **kw):
#         """ Webhook to receive Call Events from Voxbay. """
#         import logging
#         _logger = logging.getLogger(__name__)
#
#         try:
#             if request.httprequest.data:
#                 try:
#                     data = json.loads(request.httprequest.data.decode())
#                     kw.update(data)
#                 except Exception:
#                     pass
#
#             _logger.info("Voxbay Webhook payload: %s", kw)
#
#             call_uuid = kw.get('CallUUID') or kw.get('callUUlD') or kw.get('call_id') or kw.get('callID')
#             called_number = kw.get('calledNumber')
#             caller_number = kw.get('callerNumber')
#             destination = kw.get('destination')
#             extension = kw.get('extension')
#
#             call_type = 'incoming' if caller_number else ('outgoing' if destination else False)
#
#             if not call_type:
#                 return Response("error: Unknown call type", content_type='text/plain')
#
#             # Identify the customer number
#             customer_number = caller_number if call_type == 'incoming' else destination
#             if customer_number and len(customer_number) > 10:
#                 customer_number = customer_number[-10:]
#
#             lead_model = request.env['leads.logic'].sudo()
#             lead = False
#             if customer_number:
#                 lead = lead_model.search([('phone_number', 'like', '%' + customer_number)], limit=1)
#
#                 if not lead:
#                     # Create a new lead
#                     digital_source = request.env['leads.sources'].sudo().search([('name', '=', 'Incoming Call Leads')], limit=1)
#                     if not digital_source:
#                         digital_source = request.env['leads.sources'].sudo().create({'name': 'Incoming Call Leads'})
#                     lead = lead_model.create({
#                         'name': 'Incoming Call [' + (caller_number or destination or "Unknown") + ']',
#                         'phone_number': caller_number or destination,
#                         'leads_source': digital_source.id
#                     })
#
#             if lead:
#                 call_log_model = request.env['lead.call.log'].sudo()
#                 log_domain = [('lead_id', '=', lead.id)]
#                 if call_uuid:
#                     log_domain.append(('call_uuid', '=', call_uuid))
#
#                 call_log = call_log_model.search(log_domain, limit=1) if call_uuid else False
#
#                 # 1. Capture Raw Data from Voxbay
#                 raw_duration = kw.get('totalCallDuration') or kw.get('conversationDuration') or kw.get('duration')
#                 status = kw.get('callStatus') or kw.get('status')
#                 recording_url = kw.get('recording_URL')
#                 agent_ext = kw.get('AgentNumber') or extension
#
#                 # 2. Convert Seconds to HH:MM:SS
#                 formatted_duration = "00:00:00"
#                 if raw_duration:
#                     try:
#                         total_seconds = int(raw_duration)  # Voxbay sends varchar seconds
#                         hours, remainder = divmod(total_seconds, 3600)
#                         minutes, seconds = divmod(remainder, 60)
#                         formatted_duration = "{:02}:{:02}:{:02}".format(int(hours), int(minutes), int(seconds))
#                     except (ValueError, TypeError):
#                         formatted_duration = str(raw_duration)
#
#                 # 3. Fetch Agent User
#                 user = False
#                 if agent_ext:
#                     user = request.env['res.users'].sudo().search([('voxbay_user_no', '=', agent_ext)], limit=1)
#
#                 full_recording_url = ''
#                 if recording_url:
#                     full_recording_url = f"{recording_url}"
#
#
#                 # 4. Prepare Values for Odoo
#                 vals = {
#                     'lead_id': lead.id,
#                     'call_type': call_type,
#                     'caller_number': caller_number or destination,
#                     'call_status': status or '',
#                     'recording_url': full_recording_url or '',
#                     'duration': formatted_duration,  # Use the formatted HH:MM:SS here
#                 }
#
#                 if call_uuid:
#                     vals['call_uuid'] = call_uuid
#                 if user:
#                     vals['user_id'] = user.id
#
#                 # 5. Set Remarks
#                 if raw_duration or status:
#                     vals[
#                         'remarks'] = f"Voxbay {call_type} call ended. Status: {status}. Duration: {formatted_duration}."
#                 else:
#                     vals['remarks'] = f"Voxbay {call_type} call event received. Agent: {agent_ext or 'Unknown'}."
#
#                 # 6. Save to Database
#                 if call_log:
#                     call_log.write(vals)
#                 else:
#                     call_log_model.create(vals)
#
#             return Response("success", content_type='text/plain')
#
#         except Exception as e:
#             _logger.error("Voxbay Webhook Error: %s", str(e))
#             return Response("error", content_type='text/plain')

# working 2
# class VoxbayWebhook(http.Controller):
#
#     @http.route(['/api/voxbay/callcenterbridging', '/callcenterbridging'], type='http', auth='public', csrf=False,
#                 methods=['POST', 'GET'])
#     def voxbay_webhook(self, **kw):
#         """ Webhook to receive Call Events from Voxbay and Bonvoice. """
#         import logging
#         _logger = logging.getLogger(__name__)
#
#         try:
#             # Parse JSON body if available
#             if request.httprequest.data:
#                 try:
#                     data = json.loads(request.httprequest.data.decode())
#                     kw.update(data)
#                 except Exception:
#                     pass
#
#             _logger.info("Call Webhook payload received: %s", kw)
#
#             # 1. Unified Parameter Extraction (Voxbay or Bonvoice fallback)
#             # IDs: CallUUID (Voxbay) | callID/call_id (Bonvoice)
#             call_uuid = kw.get('CallUUID') or kw.get('callUUlD') or kw.get('callID') or kw.get('call_id')
#
#             # Numbers: callerNumber/destination (Voxbay) | SourceNumber/DestinationNumber (Bonvoice)
#             caller_number = kw.get('callerNumber') or kw.get('SourceNumber')
#             destination = kw.get('destination') or kw.get('DestinationNumber')
#
#             # Status: callStatus (Voxbay) | Status (Bonvoice)
#             status = kw.get('callStatus') or kw.get('status') or kw.get('Status') or kw.get('disposition')
#
#             # Duration: totalCallDuration/duration (Voxbay) | CallDuration (Bonvoice)
#             raw_duration = kw.get('totalCallDuration') or kw.get('conversationDuration') or kw.get(
#                 'duration') or kw.get('CallDuration')
#
#             # Recording: recording_URL (Voxbay) | ResourceURL (Bonvoice)
#             recording_url = kw.get('recording_URL') or kw.get('ResourceURL') or kw.get('recording_url')
#
#             # Agent/Extension Mapping
#             extension = kw.get('extension')
#             agent_ext = kw.get('AgentNumber') or kw.get('agent_id') or extension
#
#             # Determine Call Type
#             call_type = 'incoming' if (caller_number or kw.get('Direction') == 'Inbound') else (
#                 'outgoing' if destination else False)
#
#             if not call_type:
#                 return Response("error: Unknown call type", content_type='text/plain')
#
#             # Identify the customer number (clean to last 10 digits for searching)
#             customer_number = caller_number if call_type == 'incoming' else destination
#             if customer_number and len(str(customer_number)) > 10:
#                 customer_number = str(customer_number)[-10:]
#
#             lead_model = request.env['leads.logic'].sudo()
#             lead = False
#             if customer_number:
#                 # Search for existing lead using the last 10 digits
#                 lead = lead_model.search([('phone_number', 'like', '%' + str(customer_number))], limit=1)
#
#                 if not lead:
#                     # Create a new lead if not found
#                     digital_source = request.env['leads.sources'].sudo().search([('name', '=', 'Incoming Call Leads')],
#                                                                                 limit=1)
#                     if not digital_source:
#                         digital_source = request.env['leads.sources'].sudo().create({'name': 'Incoming Call Leads'})
#                     lead = lead_model.create({
#                         'name': 'Call Lead [' + str(caller_number or destination or "Unknown") + ']',
#                         'phone_number': caller_number or destination,
#                         'leads_source': digital_source.id
#                     })
#
#             if lead:
#                 call_log_model = request.env['lead.call.log'].sudo()
#                 log_domain = [('lead_id', '=', lead.id)]
#                 if call_uuid:
#                     log_domain.append(('call_uuid', '=', call_uuid))
#
#                 call_log = call_log_model.search(log_domain, limit=1) if call_uuid else False
#
#                 # 2. Convert Seconds to HH:MM:SS format
#                 formatted_duration = "00:00:00"
#                 if raw_duration:
#                     try:
#                         total_seconds = int(float(raw_duration))
#                         hours, remainder = divmod(total_seconds, 3600)
#                         minutes, seconds = divmod(remainder, 60)
#                         formatted_duration = "{:02}:{:02}:{:02}".format(int(hours), int(minutes), int(seconds))
#                     except (ValueError, TypeError):
#                         formatted_duration = str(raw_duration)
#
#                 # 3. Handle Recording URL
#                 full_recording_url = ''
#                 if recording_url:
#                     # If it's already a full Bonvoice URL, use it. If not, treat as Voxbay.
#                     if str(recording_url).startswith('http'):
#                         full_recording_url = recording_url
#                     else:
#                         # Standard Voxbay prefix logic
#                         full_recording_url = f"https://x.voxbay.com:81/callcenter/{recording_url}"
#
#                 # 4. Fetch Agent User mapping
#                 user = False
#                 if agent_ext:
#                     user = request.env['res.users'].sudo().search([('voxbay_user_no', '=', str(agent_ext))], limit=1)
#
#                 # 5. Prepare Values for Odoo
#                 vals = {
#                     'lead_id': lead.id,
#                     'call_type': call_type,
#                     'caller_number': caller_number or destination,
#                     'call_status': status or '',
#                     'recording_url': full_recording_url or '',
#                     'duration': formatted_duration,
#                 }
#
#                 if call_uuid:
#                     vals['call_uuid'] = call_uuid
#                 if user:
#                     vals['user_id'] = user.id
#
#                 # 6. Set Remarks
#                 if raw_duration or status:
#                     vals['remarks'] = f"Call ended. Status: {status}. Duration: {formatted_duration}."
#                 else:
#                     vals['remarks'] = f"Call event received. Agent: {agent_ext or 'Unknown'}."
#
#                 # 7. Create or Update Log
#                 if call_log:
#                     call_log.write(vals)
#                 else:
#                     call_log_model.create(vals)
#
#             return Response("success", content_type='text/plain')
#
#         except Exception as e:
#             _logger.error("Webhook Logic Error: %s", str(e))
#             return Response("error", content_type='text/plain')
# class VoxbayWebhook(http.Controller):
#
#     @http.route(['/api/voxbay/callcenterbridging', '/callcenterbridging'], type='http', auth='public', csrf=False,
#                 methods=['POST', 'GET'])
#     def voxbay_webhook(self, **kw):
#         """ Webhook to receive Call Events from Voxbay and Bonvoice. """
#         try:
#             # Parse JSON payload if the request contains raw data
#             if request.httprequest.data:
#                 try:
#                     data = json.loads(request.httprequest.data.decode())
#                     kw.update(data)
#                 except Exception:
#                     pass
#
#             _logger.info("Call Webhook payload received: %s", kw)
#
#             # --- 1. UNIFIED PARAMETER EXTRACTION ---
#             # Unique ID: CallUUID (Voxbay) | callID/call_id (Bonvoice)
#             call_uuid = kw.get('CallUUID') or kw.get('callUUlD') or kw.get('callID') or kw.get('call_id')
#
#             # Numbers: Supports both providers
#             src_no = kw.get('callerNumber') or kw.get('SourceNumber')
#             dest_no = kw.get('destination') or kw.get('DestinationNumber')
#
#             # Determine Direction & Customer Number
#             direction = kw.get('Direction') or ''
#
#             # Logic to handle Outbound vs Inbound for both providers
#             if direction == 'Outbound' or (dest_no and not src_no):
#                 call_type = 'outgoing'
#                 customer_number = dest_no
#                 temp_agent_ext = src_no  # In outbound, the source is the internal extension
#             else:
#                 call_type = 'incoming'
#                 customer_number = src_no
#                 temp_agent_ext = dest_no  # In inbound, the destination is the internal extension
#
#             if not customer_number:
#                 return Response("error: No phone number found", content_type='text/plain')
#
#
#
#             # --- 2. LEAD SEARCH (Last 10 Digits) ---
#             search_number = str(customer_number)
#             if len(search_number) > 10:
#                 search_number = search_number[-10:]
#
#             lead_model = request.env['leads.logic'].sudo()
#             lead = lead_model.search([('phone_number', 'like', '%' + search_number)], limit=1)
#             # lead_model_context = lead_model.with_user(user.id) if user else lead_model
#             if not lead:
#                 # Create a new lead automatically if no match is found
#                 source_name = 'Incoming Call Leads' if call_type == 'incoming' else 'Outgoing Call Leads'
#                 digital_source = request.env['leads.sources'].sudo().search([('name', '=', source_name)], limit=1)
#                 if not digital_source:
#                     digital_source = request.env['leads.sources'].sudo().create({'name': source_name})
#
#                 lead = lead_model.create({
#                     'name': f'Auto-Created [{customer_number}]',
#                     'phone_number': customer_number,
#                     'leads_source': digital_source.id
#                 })
#
#                 # lead = lead_model_context.create({
#                 #     'name': f'Auto-Created [{user.name if user else customer_number}]',
#                 #     'phone_number': customer_number,
#                 #     'leads_source': digital_source.id,
#                 #     'user_id': user.id if user else False,  # Explicitly set the Salesperson/Owner
#                 # })
#
#             #     Agent Maping
#
#
#
#             # --- 3. PROCESS CALL LOG ---
#             if lead:
#                 call_log_model = request.env['lead.call.log'].sudo()
#                 log_domain = [('lead_id', '=', lead.id)]
#                 if call_uuid:
#                     log_domain.append(('call_uuid', '=', call_uuid))
#
#                 # Update existing log or prepare to create a new one
#                 call_log = call_log_model.search(log_domain, limit=1) if call_uuid else False
#
#                 # Format Duration (Handles "7.0" or "7" safely)
#                 raw_duration = kw.get('totalCallDuration') or kw.get('CallDuration') or kw.get('duration')
#                 formatted_duration = "00:00:00"
#                 if raw_duration:
#                     try:
#                         total_seconds = int(float(raw_duration))
#                         hours, remainder = divmod(total_seconds, 3600)
#                         minutes, seconds = divmod(remainder, 60)
#                         formatted_duration = "{:02}:{:02}:{:02}".format(int(hours), int(minutes), int(seconds))
#                     except:
#                         formatted_duration = str(raw_duration)
#
#                 # Format Recording URL (Checks for existing full links)
#                 recording_url = kw.get('recording_URL') or kw.get('ResourceURL') or kw.get('recording_url')
#                 full_recording_url = ''
#                 if recording_url:
#                     rec_str = str(recording_url)
#                     if rec_str.startswith('http'):
#                         full_recording_url = rec_str
#                     else:
#                         # Fallback to Voxbay base URL
#                         full_recording_url = f"https://x.voxbay.com:81/callcenter/{rec_str}"
#
#                 # --- 4. AGENT MAPPING (THE BONVOICE FIX) ---
#                 agent_ext = kw.get('AgentNumber') or kw.get('extension') or temp_agent_ext
#                 user = False
#                 if agent_ext:
#                     clean_ext = str(agent_ext).strip()
#                     # First check Bonvoice technical field
#                     user = request.env['res.users'].sudo().search([
#                         ('bonvoice_agent_number', '=', clean_ext)
#                     ], limit=1)
#
#                     # If not found, check Voxbay technical field
#                     if not user:
#                         user = request.env['res.users'].sudo().search([
#                             ('voxbay_user_no', '=', clean_ext)
#                         ], limit=1)
#
#                 # --- 5. PREPARE DATA FOR ODOO ---
#                 status = kw.get('callStatus') or kw.get('Status') or kw.get('disposition') or 'ANSWERED'
#                 provider = "Bonvoice" if kw.get('DataSource') == 'Bonvoice' or kw.get('ResourceURL') else "Voxbay"
#
#                 vals = {
#                     'lead_id': lead.id,
#                     'call_type': call_type,
#                     'caller_number': customer_number,
#                     'call_status': status,
#                     'recording_url': full_recording_url,
#                     'duration': formatted_duration,
#                     'call_uuid': call_uuid,
#                     'user_id': user.id if user else False,
#                     'remarks': f"{provider} {call_type} call. Status: {status}. Duration: {formatted_duration}."
#                 }
#
#                 if call_log:
#                     call_log.write(vals)
#                 else:
#                     call_log_model.create(vals)
#
#             return Response("success", content_type='text/plain')
#
#         except Exception as e:
#             _logger.error("Call Webhook Critical Error: %s", str(e))
#             return Response("error", content_type='text/plain')

class VoxbayWebhook(http.Controller):

    @http.route(['/api/voxbay/callcenterbridging', '/callcenterbridging'], type='http', auth='public', csrf=False,
                methods=['POST', 'GET'])
    def voxbay_webhook(self, **kw):
        """ Webhook to receive Call Events from Voxbay and Bonvoice. """
        try:
            # Parse JSON payload
            if request.httprequest.data:
                try:
                    data = json.loads(request.httprequest.data.decode())
                    kw.update(data)
                except Exception:
                    pass

            _logger.info("Call Webhook payload received: %s", kw)

            # --- 1. PARAMETER EXTRACTION ---
            call_uuid = kw.get('CallUUID') or kw.get('callUUlD') or kw.get('callID') or kw.get('call_id')
            src_no = kw.get('callerNumber') or kw.get('SourceNumber')
            dest_no = kw.get('destination') or kw.get('DestinationNumber')
            direction = kw.get('Direction') or ''

            if direction == 'Outbound' or (dest_no and not src_no):
                call_type, customer_number, temp_agent_ext = 'outgoing', dest_no, src_no
            else:
                call_type, customer_number, temp_agent_ext = 'incoming', src_no, dest_no

            if not customer_number:
                return Response("error: No phone number found", content_type='text/plain')

            # --- 2. AGENT MAPPING (Moved up so we have the name for the Lead) ---
            agent_ext = kw.get('AgentNumber') or kw.get('extension') or temp_agent_ext
            user = False
            if agent_ext:
                clean_ext = str(agent_ext).strip()
                user = request.env['res.users'].sudo().search([('bonvoice_agent_number', '=', clean_ext)], limit=1)
                if not user:
                    user = request.env['res.users'].sudo().search([('voxbay_user_no', '=', clean_ext)], limit=1)

            # --- 3. LEAD SEARCH & CREATION ---
            search_number = str(customer_number)[-10:] if len(str(customer_number)) > 10 else str(customer_number)
            lead_model = request.env['leads.logic'].sudo()
            lead = lead_model.search([('phone_number', 'like', '%' + search_number)], limit=1)

            if not lead:
                source_name = 'Incoming Call Leads' if call_type == 'incoming' else 'Outgoing Call Leads'
                digital_source = request.env['leads.sources'].sudo().search([('name', '=', source_name)], limit=1)
                if not digital_source:
                    digital_source = request.env['leads.sources'].sudo().create({'name': source_name})

                # Use Agent Name if found, otherwise use Number
                lead_display_name = user.name if user else customer_number

                lead = lead_model.create({
                    'name': f'Auto-Created [{lead_display_name}]',
                    'phone_number': customer_number,
                    'leads_source': digital_source.id,
                    'user_id': user.id if user else False  # Assign to agent
                })

            # --- 4. PROCESS CALL LOG ---
            if lead:
                # Format Duration
                raw_duration = kw.get('totalCallDuration') or kw.get('CallDuration') or kw.get('duration')
                formatted_duration = "00:00:00"
                if raw_duration:
                    try:
                        total_seconds = int(float(raw_duration))
                        hours, remainder = divmod(total_seconds, 3600)
                        minutes, seconds = divmod(remainder, 60)
                        formatted_duration = "{:02}:{:02}:{:02}".format(int(hours), int(minutes), int(seconds))
                    except:
                        formatted_duration = str(raw_duration)

                # Format Recording URL
                recording_url = kw.get('recording_URL') or kw.get('ResourceURL') or kw.get('recording_url')
                full_url = ''
                if recording_url:
                    full_url = str(recording_url) if str(recording_url).startswith(
                        'http') else f"https://x.voxbay.com:81/callcenter/{recording_url}"

                # Prepare Log Data
                status = kw.get('callStatus') or kw.get('Status') or kw.get('disposition') or 'ANSWERED'
                provider = "Bonvoice" if kw.get('DataSource') == 'Bonvoice' or kw.get('ResourceURL') else "Voxbay"

                vals = {
                    'lead_id': lead.id,
                    'call_type': call_type,
                    'caller_number': customer_number,
                    'call_status': status,
                    'recording_url': full_url,
                    'duration': formatted_duration,
                    'call_uuid': call_uuid,
                    'user_id': user.id if user else False,
                    'remarks': f"{provider} {call_type} call. Status: {status}."
                }

                call_log_model = request.env['lead.call.log'].sudo()
                call_log = call_log_model.search([('call_uuid', '=', call_uuid)], limit=1) if call_uuid else False

                if call_log:
                    call_log.write(vals)
                else:
                    call_log_model.create(vals)

            return Response("success", content_type='text/plain')

        except Exception as e:
            _logger.error("Call Webhook Critical Error: %s", str(e))
            return Response("error", content_type='text/plain')


# class VoxbayWebhook(http.Controller):
#
#     @http.route(['/api/voxbay/callcenterbridging', '/callcenterbridging'], type='http', auth='public', csrf=False,
#                 methods=['POST', 'GET'])
#     def voxbay_webhook(self, **kw):
#         """ Webhook to receive Call Events from Voxbay and Bonvoice. """
#         try:
#             # Parse JSON payload if the request contains raw data
#             if request.httprequest.data:
#                 try:
#                     data = json.loads(request.httprequest.data.decode())
#                     kw.update(data)
#                 except Exception:
#                     pass
#
#             _logger.info("Call Webhook payload received: %s", kw)
#
#             # --- 1. UNIFIED PARAMETER EXTRACTION ---
#             call_uuid = kw.get('CallUUID') or kw.get('callUUlD') or kw.get('callID') or kw.get('call_id')
#             src_no = kw.get('callerNumber') or kw.get('SourceNumber')
#             dest_no = kw.get('destination') or kw.get('DestinationNumber')
#             direction = kw.get('Direction') or ''
#
#             # Logic to handle Outbound vs Inbound
#             if direction == 'Outbound' or (dest_no and not src_no):
#                 call_type = 'outgoing'
#                 customer_number = dest_no
#                 temp_agent_ext = src_no
#             else:
#                 call_type = 'incoming'
#                 customer_number = src_no
#                 temp_agent_ext = dest_no
#
#             if not customer_number:
#                 return Response("error: No phone number found", content_type='text/plain')
#
#             # --- 2. AGENT MAPPING (Unified and Moved Up) ---
#             agent_ext = kw.get('AgentNumber') or kw.get('extension') or temp_agent_ext
#             user = False
#             if agent_ext:
#                 clean_ext = str(agent_ext).strip()
#                 # Search Bonvoice then Voxbay
#                 user = request.env['res.users'].sudo().search([
#                     ('bonvoice_agent_number', '=', clean_ext)
#                 ], limit=1)
#                 if not user:
#                     user = request.env['res.users'].sudo().search([
#                         ('voxbay_user_no', '=', clean_ext)
#                     ], limit=1)
#
#             # --- 3. LEAD SEARCH & CREATION ---
#             search_number = str(customer_number)
#             if len(search_number) > 10:
#                 search_number = search_number[-10:]
#
#             lead_model = request.env['leads.logic'].sudo()
#             lead = lead_model.search([('phone_number', 'like', '%' + search_number)], limit=1)
#
#             # Switch context to agent for "Created By" tracking
#             lead_model_context = lead_model.with_user(user.id) if user else lead_model
#
#             if not lead:
#                 source_name = 'Incoming Call Leads' if call_type == 'incoming' else 'Outgoing Call Leads'
#                 digital_source = request.env['leads.sources'].sudo().search([('name', '=', source_name)], limit=1)
#                 if not digital_source:
#                     digital_source = request.env['leads.sources'].sudo().create({'name': source_name})
#
#                 lead = lead_model_context.create({
#                     'name': f'Auto-Created [{user.name if user else customer_number}]',
#                     'phone_number': customer_number,
#                     'leads_source': digital_source.id,
#                     'user_id': user.id if user else False,
#                 })
#
#             # --- 4. PROCESS CALL LOG ---
#             if lead:
#                 call_log_model = request.env['lead.call.log'].sudo()
#                 log_domain = [('lead_id', '=', lead.id)]
#                 if call_uuid:
#                     log_domain.append(('call_uuid', '=', call_uuid))
#
#                 call_log = call_log_model.search(log_domain, limit=1) if call_uuid else False
#
#                 # Format Duration
#                 raw_duration = kw.get('totalCallDuration') or kw.get('CallDuration') or kw.get('duration')
#                 formatted_duration = "00:00:00"
#                 if raw_duration:
#                     try:
#                         total_seconds = int(float(raw_duration))
#                         hours, remainder = divmod(total_seconds, 3600)
#                         minutes, seconds = divmod(remainder, 60)
#                         formatted_duration = "{:02}:{:02}:{:02}".format(int(hours), int(minutes), int(seconds))
#                     except:
#                         formatted_duration = str(raw_duration)
#
#                 # Format Recording URL
#                 recording_url = kw.get('recording_URL') or kw.get('ResourceURL') or kw.get('recording_url')
#                 full_recording_url = ''
#                 if recording_url:
#                     rec_str = str(recording_url)
#                     full_recording_url = rec_str if rec_str.startswith(
#                         'http') else f"https://x.voxbay.com:81/callcenter/{rec_str}"
#
#                 # --- 5. PREPARE DATA FOR LOG ---
#                 status = kw.get('callStatus') or kw.get('Status') or kw.get('disposition') or 'ANSWERED'
#                 provider = "Bonvoice" if kw.get('DataSource') == 'Bonvoice' or kw.get('ResourceURL') else "Voxbay"
#
#                 vals = {
#                     'lead_id': lead.id,
#                     'call_type': call_type,
#                     'caller_number': customer_number,
#                     'call_status': status,
#                     'recording_url': full_recording_url,
#                     'duration': formatted_duration,
#                     'call_uuid': call_uuid,
#                     'user_id': user.id if user else False,
#                     'remarks': f"{provider} {call_type} call. Status: {status}. Duration: {formatted_duration}."
#                 }
#
#                 if call_log:
#                     call_log.write(vals)
#                 else:
#                     call_log_model.create(vals)
#
#             return Response("success", content_type='text/plain')
#
#         except Exception as e:
#             _logger.error("Call Webhook Critical Error: %s", str(e))
#             return Response("error", content_type='text/plain')
class MetaWebhookController(http.Controller):

    @http.route('/api/meta/webhook', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def meta_webhook(self, **kw):
        company = request.env['res.company'].sudo().search([], limit=1)
        verify_token = company.meta_verify_token

        # Handle GET requests for Webhook Verification
        if request.httprequest.method == 'GET':
            mode = kw.get('hub.mode')
            token = kw.get('hub.verify_token')
            challenge = kw.get('hub.challenge')

            if mode and token:
                if mode == 'subscribe' and token == verify_token:
                    _logger.info('Meta Webhook Verified Successfully.')
                    return Response(challenge, status=200)
            return Response('Forbidden', status=403)

        # Handle POST requests for Lead Data
        elif request.httprequest.method == 'POST':
            try:
                data = json.loads(request.httprequest.data.decode())
                
                # Meta Payload can have multiple entries
                if data.get('object') == 'page':
                    for entry in data.get('entry', []):
                        for change in entry.get('changes', []):
                            if change.get('value') and change.get('field') == 'leadgen':
                                leadgen_id = change['value'].get('leadgen_id')
                                ad_id = change['value'].get('ad_id')
                                form_id = change['value'].get('form_id')
                                
                                if leadgen_id:
                                    self._process_meta_lead(leadgen_id, ad_id)
                
                return Response('Success', status=200)
            except Exception as e:
                _logger.error("Meta Webhook Processing Error: %s", str(e))
                return Response('Error', status=500)
                
    def _process_meta_lead(self, leadgen_id, ad_id):
        company = request.env['res.company'].sudo().search([], limit=1)
        access_token = company.meta_page_access_token
        
        if not access_token:
            _logger.error("Meta Page Access Token not configured.")
            return

        # 1. Fetch Lead Details
        lead_url = f"https://graph.facebook.com/v19.0/{leadgen_id}"
        lead_response = requests.get(lead_url, params={'access_token': access_token})
        
        if lead_response.status_code != 200:
            _logger.error("Failed to fetch lead from Meta. Response: %s", lead_response.text)
            return
            
        lead_data = lead_response.json()
        
        name = 'Unknown Meta Lead'
        email = False
        phone = False
        
        # Parse Field Data from Meta Form
        field_data = lead_data.get('field_data', [])
        for field in field_data:
            field_name = field.get('name')
            field_values = field.get('values', [])
            val = field_values[0] if field_values else ''
            
            if field_name in ['full_name', 'name', 'first_name']:
                # Note: Meta often separates first and last name, but usually provides full_name.
                if name == 'Unknown Meta Lead': 
                    name = val
                else: 
                    name += f" {val}"
            elif field_name in ['email', 'email_address']:
                email = val
            elif field_name in ['phone_number', 'phone']:
                phone = val
        
        # 2. Extract Campaign/Ad Name dynamically to set Lead Source
        source_name = "Meta Ad Lead" # Default fallback
        if ad_id:
            ad_url = f"https://graph.facebook.com/v19.0/{ad_id}"
            # Ask for ad name, which often relates to the campaign
            ad_response = requests.get(ad_url, params={'fields': 'campaign{name},name', 'access_token': access_token})
            if ad_response.status_code == 200:
                ad_data = ad_response.json()
                campaign_data = ad_data.get('campaign', {})
                source_name = campaign_data.get('name') or ad_data.get('name') or source_name

        # 3. Find or Create lead source in Odoo
        source_model = request.env['leads.sources'].sudo()
        source = source_model.search([('name', '=', source_name)], limit=1)
        if not source:
            source = source_model.create({'name': source_name})

        # 4. Create the Lead in Leads Logic
        lead_vals = {
            'name': name,
            'email_address': email,
            'phone_number': phone,
            'leads_source': source.id,
        }
        
        request.env['leads.logic'].sudo().create(lead_vals)
        _logger.info("Successfully created Meta Lead from leadgen_id: %s with source: %s", leadgen_id, source_name)

