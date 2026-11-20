import logging
import time
import uuid

import requests

from odoo import _, release
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TIMEOUT = 30


class SourevoTradeError(UserError):
    """Sourevo answered with an error; the message is translated. ``code`` and ``reason`` come from the API."""

    def __init__(self, message, status=None, code=None, reason=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.reason = reason


def error_message(status, error, context=None):
    """A readable message for an API error ({code, message, details}), in the language of ``context``."""
    error = error if isinstance(error, dict) else {}
    code = error.get('code')
    details = error.get('details') if isinstance(error.get('details'), dict) else {}
    reason = details.get('reason')
    if code in ('missing_api_key', 'invalid_api_key'):
        return _('The Sourevo API key is not valid. Check it in Settings > Sourevo EUDR Lite.')
    if code == 'key_owner_forbidden':
        return _('The owner of this API key is no longer an owner or administrator in Sourevo. Create a new key.')
    if code == 'rate_limited':
        return _('Too many requests to Sourevo (30 per minute on the trader plan). Try again in a minute.')
    if reason == 'trade_not_enabled':
        return _('Trade records are not turned on in Sourevo: turn them on in Sourevo, Trade > Settings.')
    if reason == 'trader_plan':
        return _('The free trader plan only covers the trade records.')
    if reason == 'invalid_partner':
        return _('Sourevo needs the name, postal address, a valid email and the country of this contact (EUDR Art. 5.3).')
    if reason in ('invalid_purchase', 'invalid_sale'):
        return _('Sourevo needs the date, description, CN code (4, 6 or 8 digits), quantity and unit of this line.')
    if reason == 'invalid_reference':
        return _('The reference number has up to 50 characters and the verification number 5 to 35.')
    if reason == 'partner_not_supplier':
        return _('This contact is recorded in Sourevo as a customer only.')
    if reason == 'partner_not_customer':
        return _('This contact is recorded in Sourevo as a supplier only.')
    if reason == 'purchase_unlink_not_allowed':
        return _('A receipt already linked to a sale in Sourevo cannot be unlinked (records are kept five years).')
    if reason == 'reference_request_cap':
        return _('The number of this receipt was already asked for three times.')
    if reason == 'reference_request_too_soon':
        return _('The supplier was asked less than three days ago.')
    if reason == 'reference_request_daily_cap':
        return _("Today's limit of requests to suppliers is reached. Try again tomorrow.")
    if reason == 'already_decided':
        return _('This number was already accepted or rejected in Sourevo.')
    if reason in ('trade_limit_purchases', 'trade_limit_sales', 'trade_limit_partners'):
        return _('The yearly limit of the free trader plan is reached. Write to Sourevo.')
    if code == 'not_found':
        return _('Sourevo does not know this record any more.')
    if code == 'service_unavailable':
        return _('Sourevo is not available right now. Try again in a few minutes.')
    return _('Sourevo: %(message)s (%(status)s)', message=error.get('message') or code or _('unknown error'), status=status)


class SourevoTradeClient:
    """Client of the /trade endpoints of the Sourevo API v1 (https://sourevo.com/en/developers).

    Every POST and PATCH carries an Idempotency-Key, and one that times out is
    sent again once with the same key: Sourevo answers the stored result.
    """

    def __init__(self, company):
        env = company.env
        self.context = {'lang': env.lang or env.user.lang or 'en_US'}
        company = company.sudo()
        self.base_url = (company.sourevo_trade_url or '').rstrip('/')
        self.api_key = company.sourevo_trade_api_key
        if not self.base_url or not self.api_key:
            raise UserError(_('Sourevo is not connected yet: Settings > Sourevo EUDR Lite > API key.'))

    def _request(self, method, path, payload=None, params=None):
        context = self.context  # noqa: F841 - read by _() for the language of the messages below
        url = f'{self.base_url}{path}'
        headers = {'Authorization': f'Bearer {self.api_key}', 'Accept': 'application/json',
                   'X-Sourevo-Client': f'Odoo {release.major_version} Lite'}
        if method in ('POST', 'PATCH'):
            headers['Idempotency-Key'] = str(uuid.uuid4())
        attempts = 2 if method in ('POST', 'PATCH') else 1
        for attempt in range(attempts):
            try:
                resp = requests.request(method, url, json=payload, params=params, headers=headers, timeout=TIMEOUT)
                break
            except requests.Timeout as e:
                _logger.warning('Sourevo %s %s timed out (attempt %s)', method, path, attempt + 1)
                if attempt + 1 == attempts:
                    raise SourevoTradeError(_('Sourevo did not answer in time. Try again in a moment.'), code='timeout') from e
                time.sleep(1)
            except requests.RequestException as e:
                _logger.warning('Sourevo %s %s: %s', method, path, e)
                raise SourevoTradeError(_('Could not connect to Sourevo (%s).', e), code='network') from e
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if 200 <= resp.status_code < 300:
            return data
        error = data.get('error') if isinstance(data, dict) else None
        error = error if isinstance(error, dict) else {}
        details = error.get('details') if isinstance(error.get('details'), dict) else {}
        _logger.info('Sourevo %s %s -> %s %s', method, path, resp.status_code, error)
        raise SourevoTradeError(error_message(resp.status_code, error, self.context), status=resp.status_code,
                                code=error.get('code'), reason=details.get('reason'))

    def me(self):
        return self._request('GET', '/me')

    def find(self, kind, external_ref):
        """The partner, purchase or sale with this externalRef, or None."""
        data = self._request('GET', f'/trade/{kind}', params={'externalRef': external_ref, 'limit': 1})
        rows = data.get('data') or []
        return rows[0] if rows else None

    def create_partner(self, payload):
        return self._request('POST', '/trade/partners', payload)

    def correct_partner(self, partner_id, payload):
        return self._request('PATCH', f'/trade/partners/{partner_id}', payload)

    def create_purchase(self, payload):
        return self._request('POST', '/trade/purchases', payload)

    def purchase(self, purchase_id):
        return self._request('GET', f'/trade/purchases/{purchase_id}')

    def add_reference(self, purchase_id, payload):
        return self._request('POST', f'/trade/purchases/{purchase_id}/references', payload)

    def request_reference(self, purchase_id, payload):
        return self._request('POST', f'/trade/purchases/{purchase_id}/reference-request', payload)

    def decide(self, reference_id, accept, reason=None):
        body = {'accept': True} if accept else {'accept': False, 'reason': reason}
        return self._request('POST', f'/trade/references/{reference_id}/decision', body)

    def create_sale(self, payload):
        return self._request('POST', '/trade/sales', payload)

    def create_webhook(self, url, events):
        return self._request('POST', '/webhooks', {'url': url, 'events': events, 'description': 'Odoo Lite'})

    def delete_webhook(self, webhook_id):
        return self._request('DELETE', f'/webhooks/{webhook_id}')

    def test_webhook(self, webhook_id):
        return self._request('POST', f'/webhooks/{webhook_id}/test', {})
