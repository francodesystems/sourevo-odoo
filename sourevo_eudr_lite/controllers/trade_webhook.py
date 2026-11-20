import hashlib
import hmac
import json
import logging
import time

from odoo import SUPERUSER_ID, http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Sourevo signs with a timestamp: an older signature is a replay.
TOLERANCE_SECONDS = 300


def verify_signature(secret, body, header, now=None):
    """X-Sourevo-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<raw body>")>."""
    if not secret or not header:
        return False
    parts = dict(p.strip().split('=', 1) for p in header.split(',') if '=' in p)
    try:
        timestamp = int(parts.get('t', ''))
    except ValueError:
        return False
    if abs((now or time.time()) - timestamp) > TOLERANCE_SECONDS or not parts.get('v1'):
        return False
    expected = hmac.new(secret.encode(), f'{timestamp}.'.encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts['v1'])


class SourevoTradeWebhook(http.Controller):
    """Sourevo notifications for the trade records: signature first, on the raw body."""

    @http.route('/sourevo/trade-webhook/<int:company_id>', type='http', auth='public', methods=['POST'], csrf=False,
                save_session=False)
    def notification(self, company_id, **_kw):
        body = request.httprequest.get_data()
        company = request.env['res.company'].sudo().browse(company_id).exists()
        secret = company.sourevo_trade_webhook_secret if company else None
        if not verify_signature(secret, body, request.httprequest.headers.get('X-Sourevo-Signature', '')):
            return request.make_json_response({'error': 'signature'}, status=401)
        try:
            event = json.loads(body)
        except ValueError:
            return request.make_json_response({'error': 'json'}, status=400)
        if not isinstance(event, dict):
            return request.make_json_response({'error': 'json'}, status=400)
        if event.get('type') == 'trade.reference_proposed':
            # As OdooBot, not as the public user: it writes in the chatter.
            env = request.env(user=SUPERUSER_ID, context=dict(request.env.context, allowed_company_ids=[company.id]))
            purchase = (event.get('data') or {}).get('purchase') or {}
            line = env['sourevo.trade.line'].search([('company_id', '=', company.id), ('direction', '=', 'in'),
                                                     ('sourevo_id', '=', purchase.get('id'))], limit=1)
            if line:
                line.picking_id._sourevo_trade_take_proposals(purchase)
            else:
                _logger.info('Sourevo Lite: proposal for an unknown purchase %s', purchase.get('id'))
        return request.make_json_response({'ok': True})
