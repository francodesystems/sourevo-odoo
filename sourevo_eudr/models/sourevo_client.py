import logging
import time
import uuid

import requests

from odoo import _, release
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TIMEOUT = 30
# TRACES answers slowly: submitting, refreshing, amending and retracting get more time.
TIMEOUT_TRACES = 90
PAGE_LIMIT = 100


class SourevoError(UserError):
    """Sourevo answered with an error. The message is translated and can be shown as is.

    ``code`` and ``reason`` are the API's ``error.code`` and ``error.details.reason``;
    ``details`` the whole ``error.details`` (the check report of a blocked submission).
    """

    def __init__(self, message, status=None, code=None, reason=None, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.reason = reason
        self.details = details or {}


def error_message(status, error, context=None):
    """A readable message for an API error ({code, message, details}), in the language of ``context``."""
    error = error if isinstance(error, dict) else {}
    code = error.get('code')
    details = error.get('details') if isinstance(error.get('details'), dict) else {}
    reason = details.get('reason')
    if code == 'plan_not_allowed' or reason == 'pack_plan':
        return _('The Sourevo API is available from the Pro plan. Upgrade your plan in Sourevo to use it from Odoo.')
    if code in ('missing_api_key', 'invalid_api_key'):
        return _('The Sourevo API key is not valid. Check it in Settings > Sourevo.')
    if code == 'key_owner_forbidden':
        return _('The owner of this API key can no longer use the API in Sourevo. Create a new key.')
    if code == 'rate_limited':
        return _('Too many requests to Sourevo (120 per minute). Try again in a minute.')
    if reason == 'trial_expired' or reason == 'plan_expired':
        return _('Your Sourevo plan has expired.')
    if reason == 'plan_limit_reached':
        return _('You have reached the statements included in your Sourevo plan.')
    if reason == 'scientific_name_required':
        return _('Sourevo needs the scientific name for this product (wood, paper and pulp).')
    if reason == 'invalid_cn_code':
        return _('Sourevo does not accept this CN code.')
    if reason == 'invalid_country':
        return _('The country is missing or not valid.')
    if reason == 'invalid_tax_id':
        return _('The tax ID does not match the format of its country.')
    if reason == 'operator_without_credentials':
        return _('This company has no TRACES credentials in Sourevo yet.')
    if reason == 'operator_without_test_credentials':
        return _('This company has no TRACES test credentials in Sourevo, and the Sourevo test account is not available.')
    if reason == 'shared_test_account_daily_limit':
        return _('The daily limit of the Sourevo TRACES test account was reached. Try again tomorrow or add your own TRACES test credentials in Sourevo.')
    if reason in ('invalid_quantity', 'quantity_required'):
        return _('Enter the net weight in kg: more than 0, with at most 3 decimals.')
    if reason in ('batch_frozen', 'batch_has_live_dds'):
        return _('This receipt line already has a statement in TRACES: amend or retract it in Sourevo.')
    if reason == 'not_yet_available':
        return _('TRACES is still analysing the statement. Try again once it is available.')
    if reason == 'pre_submission_blocked':
        return _('The statement has blocking issues: check it again and fix them in Sourevo.')
    if reason == 'acknowledgement_required':
        return _('There are new warnings to acknowledge: check the statement again.')
    if reason == 'internal_reference_taken':
        return _('This internal reference is already used by another statement of this company.')
    if reason == 'submission_in_progress':
        return _('The statement is being submitted to TRACES. Refresh it in a moment.')
    if reason == 'polygon_required_over_4_ha':
        return _('A plot over 4 ha must be a polygon, not a point.')
    if reason and reason.startswith('geojson_'):
        return _('The GeoJSON file is not valid (%(reason)s): %(message)s', reason=reason, message=error.get('message') or '')
    if reason in ('traces_rejected', 'traces_fault', 'traces_permission_denied') or code == 'upstream_error':
        return _('TRACES did not accept the request: %s', error.get('message') or reason or code)
    if code == 'service_unavailable':
        return _('Sourevo is not available right now. Try again in a few minutes.')
    return _('Sourevo: %(message)s (%(status)s)', message=error.get('message') or code or _('unknown error'), status=status)


class SourevoClient:
    """Client of the Sourevo API v1 (https://sourevo.com/es/desarrolladores).

    Every POST carries an Idempotency-Key, and a POST that times out is sent
    again once with the same key: Sourevo answers the stored result. Errors come
    as {"error": {"code", "message", "details": {"reason"}}}.
    """

    def __init__(self, company):
        # Read by _() in error_message: the language of the messages.
        env = company.env
        self.context = {'lang': env.lang or env.user.lang or 'en_US'}
        company = company.sudo()
        self.base_url = (company.sourevo_url or '').rstrip('/')
        self.api_key = company.sourevo_api_key
        if not self.base_url or not self.api_key:
            raise UserError(_('Sourevo is not connected yet: Settings > Sourevo > API key.'))

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.api_key}',
            'Accept': 'application/json',
            'X-Sourevo-Client': f'Odoo {release.major_version}',
        }

    def _request(self, method, path, payload=None, params=None, timeout=TIMEOUT):
        url = f'{self.base_url}{path}'
        headers = self._headers()
        if method == 'POST':
            headers['Idempotency-Key'] = str(uuid.uuid4())
        attempts = 2 if method == 'POST' else 1
        for attempt in range(attempts):
            try:
                resp = requests.request(method, url, json=payload, params=params, headers=headers, timeout=timeout)
                break
            except requests.Timeout as e:
                _logger.warning('Sourevo %s %s timed out (attempt %s)', method, path, attempt + 1)
                if attempt + 1 == attempts:
                    raise UserError(_('Sourevo did not answer in time. Try again in a moment.')) from e
                time.sleep(1)
            except requests.RequestException as e:
                _logger.warning('Sourevo %s %s: %s', method, path, e)
                raise UserError(_('Could not connect to Sourevo (%s).', e)) from e
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
        raise SourevoError(error_message(resp.status_code, error, self.context), status=resp.status_code,
                           code=error.get('code'), reason=details.get('reason'), details=details)

    def _all(self, path, params=None):
        """Every item of a paginated list (limit + cursor -> nextCursor)."""
        params = dict(params or {}, limit=PAGE_LIMIT)
        items = []
        while True:
            data = self._request('GET', path, params=params)
            items += data.get('data') or []
            cursor = data.get('nextCursor')
            if not cursor:
                return items
            params['cursor'] = cursor

    # Account
    def me(self):
        return self._request('GET', '/me')

    def operators(self):
        return self._all('/operators')

    # Suppliers and plots
    def create_supplier(self, payload):
        return self._request('POST', '/suppliers', payload)

    def update_supplier(self, supplier_id, payload):
        return self._request('PATCH', f'/suppliers/{supplier_id}', payload)

    def supplier_status(self, supplier_id):
        return self._request('GET', f'/suppliers/{supplier_id}/status')

    def invite_supplier(self, supplier_id):
        return self._request('POST', f'/suppliers/{supplier_id}/invitations', {})

    def supplier_plots(self, supplier_id):
        return self._all(f'/suppliers/{supplier_id}/plots')

    def upload_plots(self, supplier_id, payload):
        return self._request('POST', f'/suppliers/{supplier_id}/plots', payload, timeout=TIMEOUT_TRACES)

    def plot(self, plot_id):
        return self._request('GET', f'/plots/{plot_id}')

    def verify_plot(self, plot_id):
        return self._request('POST', f'/plots/{plot_id}/verify', {})

    # Products
    def create_product(self, payload):
        return self._request('POST', '/products', payload)

    # Batches and statements
    def create_batch(self, payload):
        return self._request('POST', '/batches', payload)

    def create_dds(self, payload):
        return self._request('POST', '/dds', payload)

    def dds(self, dds_id):
        return self._request('GET', f'/dds/{dds_id}')

    def delete_dds(self, dds_id):
        return self._request('DELETE', f'/dds/{dds_id}')

    def check_dds(self, dds_id):
        return self._request('GET', f'/dds/{dds_id}/check')

    def submit_dds(self, dds_id, acknowledged_warnings):
        return self._request('POST', f'/dds/{dds_id}/submit', {'acknowledgedWarnings': list(acknowledged_warnings)},
                             timeout=TIMEOUT_TRACES)

    def refresh_dds(self, dds_id):
        return self._request('POST', f'/dds/{dds_id}/refresh', {}, timeout=TIMEOUT_TRACES)

    # Webhooks
    def create_webhook(self, url, events):
        return self._request('POST', '/webhooks', {'url': url, 'events': events, 'description': 'Odoo'})

    def delete_webhook(self, webhook_id):
        return self._request('DELETE', f'/webhooks/{webhook_id}')

    def test_webhook(self, webhook_id):
        return self._request('POST', f'/webhooks/{webhook_id}/test', {})
