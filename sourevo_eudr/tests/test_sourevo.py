import base64
import hashlib
import hmac
import json
import re
import time
from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.sourevo_eudr.controllers.webhook import verify_signature

REQUEST = 'odoo.addons.sourevo_eudr.models.sourevo_client.requests.request'


class FakeResponse:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data
        self.reason = 'reason'

    def json(self):
        return self._data


def plot_json(id_='plot1', name='Finca 1', verification='VERIFIED', proposal=None, supplier='sup1'):
    return {'id': id_, 'supplierId': supplier, 'name': name, 'country': 'BR', 'producerName': None, 'areaHa': 2.5,
            'geometry': {'type': 'Polygon', 'coordinates': []}, 'source': 'SUPPLIER',
            'proposal': proposal, 'verification': {'status': verification, 'comment': None, 'at': None},
            'satellite': None, 'batchCount': 0, 'createdAt': '2026-11-01T10:00:00Z'}


def dds_json(status='DRAFT', ref=None, ver=None, simulated=True, id_='dds1'):
    return {'id': id_, 'internalReferenceNumber': 'WH/IN/00001', 'status': status, 'simulated': simulated,
            'operatorId': 'op1', 'batchId': 'batch1', 'activityType': 'IMPORT', 'operatorRole': 'OPERATOR',
            'representedRole': None, 'countryOfActivity': 'ES', 'borderCrossCountry': None, 'comment': None,
            'geoLocationConfidential': False, 'riskAssessment': None, 'associatedStatements': [], 'tracesUuid': None,
            'referenceNumber': ref, 'verificationNumber': ver, 'submitting': False, 'lastSyncedAt': None,
            'createdAt': '2026-11-01T10:00:00Z', 'updatedAt': '2026-11-01T10:00:00Z'}


class FakeSourevo:
    """Answers like the Sourevo API (openapi.json); ``routes`` overrides an answer by (method, path)."""

    def __init__(self, routes=None):
        self.calls = []
        self.routes = routes or {}

    def __call__(self, method, url, json=None, params=None, headers=None, timeout=None):
        path = re.sub(r'^https://sourevo\.test/api/v1', '', url)
        self.calls.append({'method': method, 'path': path, 'json': json, 'params': params, 'headers': headers})
        if (method, path) in self.routes:
            answer = self.routes[(method, path)]
            return FakeResponse(*answer) if isinstance(answer, tuple) else FakeResponse(200, answer)
        defaults = {
            ('GET', '/me'): {'organization': {'id': 'org1', 'name': 'Café Import SL', 'taxId': 'ESB1'}, 'mode': 'simulated',
                             'plan': {'productCode': 'pro'}, 'role': 'OWNER',
                             'key': {'id': 'k', 'name': 'Odoo', 'prefix': 'svk_ab', 'createdAt': '2026-11-01T10:00:00Z',
                                     'createdBy': {'name': 'Juan', 'email': 'j@test'}}},
            ('GET', '/operators'): {'data': [{'id': 'op1', 'legalName': 'Café Import SL', 'country': 'ES', 'address': None,
                                              'email': None, 'phone': None, 'eoriNumber': 'ESB1', 'hasCredentials': True}],
                                    'nextCursor': None},
            ('POST', '/suppliers'): (201, {'id': 'sup1', 'trustLevel': 'LEVEL_1_EMAIL_VERIFIED', 'trustSignal': 'AMBER',
                                           'claimed': False}),
            ('GET', '/suppliers/sup1/status'): {
                'supplierId': 'sup1', 'owned': True, 'trustLevel': 'LEVEL_1_EMAIL_VERIFIED', 'trustSignal': 'AMBER',
                'claimed': False, 'claimedAt': None, 'taxId': None, 'invitation': None,
                'plots': {'total': 2, 'verified': 1, 'declared': 1, 'correctionRequested': 0, 'proposalsPending': 1,
                          'proposalsRejected': 0, 'satelliteFlagged': 0, 'satelliteUnchecked': 2}},
            ('GET', '/suppliers/sup1/plots'): {'data': [
                plot_json(),
                plot_json('plot2', 'Finca 2', 'DECLARED', {'status': 'PENDING', 'uploadedAt': '2026-11-01T10:00:00Z',
                                                         'confirmedAt': None, 'rejectedAt': None, 'rejectionReason': None}),
            ], 'nextCursor': None},
            ('POST', '/products'): (201, {'id': 'prod1'}),
            ('POST', '/batches'): (201, {'id': 'batch1'}),
            ('POST', '/dds'): (201, dds_json()),
            ('GET', '/dds/dds1/check'): {'ready': True, 'blocking': [], 'warnings': [
                {'key': 'w1', 'code': 'SUPPLIER_TRUST_BELOW_VALIDATED', 'level': 'supplier', 'entityId': 'sup1',
                 'data': {'trustLevel': 'LEVEL_1_EMAIL_VERIFIED'}}]},
            ('POST', '/dds/dds1/submit'): dds_json('SUBMITTED', 'SIM26ES00001', 'SIMVER01'),
            ('GET', '/dds/dds1'): dds_json('AVAILABLE', 'SIM26ES00001', 'SIMVER01'),
            ('POST', '/webhooks'): (201, {'id': 'wh1', 'url': 'x', 'events': [], 'description': 'Odoo',
                                          'createdAt': '2026-11-01T10:00:00Z', 'secret': 'whsec_test'}),
            ('POST', '/webhooks/wh1/test'): {'ok': True},
        }
        if (method, path) in defaults:
            answer = defaults[(method, path)]
            return FakeResponse(*answer) if isinstance(answer, tuple) else FakeResponse(200, answer)
        return FakeResponse(404, {'error': {'code': 'not_found', 'message': f'{method} {path}'}})

    def paths(self, method=None):
        return [c['path'] for c in self.calls if not method or c['method'] == method]


class SourevoCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.sudo().write({'sourevo_api_key': 'svk_test', 'sourevo_url': 'https://sourevo.test/api/v1',
                                  'country_id': cls.env.ref('base.es').id})
        Operator = cls.env['sourevo.operator'].with_context(active_test=False)
        cls.operator = Operator.search([('company_id', '=', cls.company.id), ('sourevo_id', '=', 'op1')]) or Operator.create(
            {'name': 'Café Import SL', 'sourevo_id': 'op1', 'country_code': 'ES', 'has_credentials': True})
        cls.company.sourevo_operator_id = cls.operator
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Fazenda Boa Vista', 'is_company': True, 'country_id': cls.env.ref('base.br').id,
            'email': 'fazenda@test.br', 'city': 'Patrocínio'})
        storable = {'is_storable': True} if 'is_storable' in cls.env['product.template']._fields else {'type': 'product'}
        cls.coffee = cls.env['product.product'].create({
            'name': 'Green coffee', 'uom_id': cls.env.ref('uom.product_uom_kgm').id, **storable,
            'eudr_relevant': True, 'eudr_cn_code': '0901 11 00'})
        cls.wh = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)

    def _receipt(self, product=None, qty=1000.0):
        product = product or self.coffee
        supplier_loc = self.env.ref('stock.stock_location_suppliers')
        move = {'product_id': product.id, 'product_uom_qty': qty, 'location_id': supplier_loc.id,
                'location_dest_id': self.wh.lot_stock_id.id}
        if 'name' in self.env['stock.move']._fields:
            move['name'] = product.name
        picking = self.env['stock.picking'].create({
            'picking_type_id': self.wh.in_type_id.id, 'partner_id': self.supplier.id,
            'location_id': supplier_loc.id, 'location_dest_id': self.wh.lot_stock_id.id,
            'move_ids': [(0, 0, move)],
        })
        picking.action_confirm()
        return picking


@tagged('post_install', '-at_install')
class TestSourevoFlow(SourevoCommon):

    def test_receipt_to_traces(self):
        api = FakeSourevo()
        picking = self._receipt()
        self.assertTrue(picking.sourevo_eudr_visible)
        with patch(REQUEST, api):
            picking.action_sourevo_prepare()
        line = picking.sourevo_dds_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.name, picking.name)
        self.assertEqual(line.net_weight_kg, 1000.0)
        self.assertEqual(line.operator_id, self.operator)
        self.assertEqual(line.country_id.code, 'ES')
        # Only the verified plot by default, though the pending proposal could be used too.
        self.assertEqual(line.plot_ids.mapped('sourevo_id'), ['plot1'])
        self.assertEqual(self.supplier.sourevo_supplier_id, 'sup1')
        self.assertEqual(self.supplier.sourevo_plots_pending, 1)
        self.assertEqual(picking.sourevo_state, 'draft')

        with patch(REQUEST, api):
            action = picking.action_sourevo_submit()
        wizard = self.env['sourevo.dds.submit'].browse(action['res_id'])
        self.assertFalse(wizard.has_blocking)
        self.assertTrue(wizard.has_warnings)
        self.assertIn('validated tax identity', wizard.summary)
        batch = next(c for c in api.calls if c['path'] == '/batches')
        self.assertEqual(batch['json']['productId'], 'prod1')
        self.assertEqual(batch['json']['netWeightKg'], 1000.0)
        self.assertEqual(batch['json']['plotIds'], ['plot1'])
        product = next(c for c in api.calls if c['path'] == '/products')
        self.assertEqual(product['json']['cnCode'], '09011100')
        dds = next(c for c in api.calls if c['path'] == '/dds')
        self.assertEqual(dds['json'], {'batchId': 'batch1', 'operatorId': 'op1', 'internalReferenceNumber': picking.name,
                                       'activityType': 'IMPORT', 'operatorRole': 'OPERATOR', 'countryOfActivity': 'ES'})
        for call in api.calls:
            self.assertTrue(call['headers']['X-Sourevo-Client'].startswith('Odoo '))
            self.assertEqual(call['headers']['Authorization'], 'Bearer svk_test')
            self.assertEqual('Idempotency-Key' in call['headers'], call['method'] == 'POST')

        with self.assertRaises(UserError):
            wizard.action_submit()  # the warnings are not acknowledged yet
        wizard.acknowledge = True
        with patch(REQUEST, api):
            wizard.action_submit()
        submit = next(c for c in api.calls if c['path'] == '/dds/dds1/submit')
        self.assertEqual(submit['json'], {'acknowledgedWarnings': ['w1']})
        self.assertEqual(line.status, 'SUBMITTED')
        self.assertEqual(line.reference_number, 'SIM26ES00001')
        self.assertTrue(line.simulated)
        self.assertEqual(picking.sourevo_state, 'done')
        self.assertEqual(picking.sourevo_references, 'SIM26ES00001 / SIMVER01')
        self.assertIn('SIM26ES00001', picking.message_ids[0].body)

    def test_blocking_issues_stop_the_submission(self):
        api = FakeSourevo({('GET', '/dds/dds1/check'): {'ready': False, 'warnings': [], 'blocking': [
            {'key': 'b1', 'code': 'BATCH_NO_PLOT', 'level': 'batch', 'entityId': 'batch1'}]}})
        picking = self._receipt()
        with patch(REQUEST, api):
            action = picking.action_sourevo_submit()
        wizard = self.env['sourevo.dds.submit'].browse(action['res_id'])
        self.assertTrue(wizard.has_blocking)
        self.assertIn('no origin plots', wizard.summary)
        with self.assertRaises(UserError):
            wizard.action_submit()
        self.assertNotIn('/dds/dds1/submit', api.paths())

    def test_operator_without_credentials(self):
        api = FakeSourevo({('GET', '/dds/dds1/check'): {'ready': False, 'warnings': [], 'blocking': [
            {'key': 'operator:op1:OPERATOR_NO_CREDENTIALS', 'code': 'OPERATOR_NO_CREDENTIALS', 'level': 'operator',
             'entityId': 'op1'}]}})
        picking = self._receipt()
        with patch(REQUEST, api):
            action = picking.action_sourevo_submit()
        wizard = self.env['sourevo.dds.submit'].browse(action['res_id'])
        self.assertTrue(wizard.has_blocking)
        self.assertTrue(wizard.needs_credentials)
        url = wizard.with_context(lang='en_US').action_open_operators()['url']
        self.assertEqual(url, 'https://sourevo.test/en/dds/operators')

    def test_weight_from_the_product(self):
        bag = self.env['product.product'].create({'name': 'Cocoa bag', 'weight': 62.5, 'eudr_relevant': True,
                                                  'eudr_cn_code': '18010000'})
        picking = self._receipt(bag, qty=10)
        with patch(REQUEST, FakeSourevo()):
            picking.action_sourevo_prepare()
        self.assertEqual(picking.sourevo_dds_ids.net_weight_kg, 625.0)

    def test_no_weight_is_not_invented(self):
        crate = self.env['product.product'].create({'name': 'Rubber crate', 'eudr_relevant': True, 'eudr_cn_code': '40012100'})
        picking = self._receipt(crate, qty=3)
        api = FakeSourevo()
        with patch(REQUEST, api):
            picking.action_sourevo_prepare()
            self.assertEqual(picking.sourevo_dds_ids.net_weight_kg, 0.0)
            with self.assertRaisesRegex(UserError, 'net weight'):
                picking.action_sourevo_submit()
        self.assertNotIn('/batches', api.paths())

    def test_cn_code_and_scientific_name(self):
        with self.assertRaises(ValidationError):
            self.coffee.product_tmpl_id.eudr_cn_code = '0901'
        oak = self.env['product.template'].create({'name': 'Oak planks', 'eudr_relevant': True, 'eudr_cn_code': '44079110'})
        with patch(REQUEST, FakeSourevo()), self.assertRaisesRegex(UserError, 'scientific'):
            oak.action_sourevo_send()
        oak.write({'eudr_scientific_name': 'Quercus robur', 'eudr_common_name': 'Oak'})
        api = FakeSourevo()
        with patch(REQUEST, api):
            oak.action_sourevo_send()
        self.assertEqual(oak.sourevo_product_id, 'prod1')
        self.assertEqual(api.calls[0]['json']['scientificName'], 'Quercus robur')
        oak.eudr_cn_code = '44079190'
        self.assertFalse(oak.sourevo_product_id, 'a new CN code is a new product in Sourevo')

    def test_plan_without_api(self):
        api = FakeSourevo({('GET', '/me'): (403, {'error': {'code': 'plan_not_allowed', 'message': 'no',
                                                            'details': {'reason': 'pack_plan'}}})})
        settings = self.env['res.config.settings'].create({})
        with patch(REQUEST, api), self.assertRaisesRegex(UserError, 'Pro plan'):
            settings.action_sourevo_test()

    def test_settings_test_and_webhook(self):
        settings = self.env['res.config.settings'].create({})
        api = FakeSourevo()
        with patch(REQUEST, api):
            settings.action_sourevo_test()
            settings.action_sourevo_connect_webhook()
        self.assertEqual(self.company.sourevo_mode, 'simulated')
        self.assertEqual(self.company.sourevo_organization, 'Café Import SL')
        self.assertEqual(self.company.sudo().sourevo_webhook_secret, 'whsec_test')
        hook = next(c for c in api.calls if c['path'] == '/webhooks')
        self.assertIn(f'/sourevo/webhook/{self.company.id}?db=', hook['json']['url'])
        self.assertIn('dds.status_changed', hook['json']['events'])

    def test_timeout_retries_with_the_same_key(self):
        import requests as real_requests
        api = FakeSourevo()
        keys = []

        def flaky(method, url, **kw):
            keys.append(kw['headers'].get('Idempotency-Key'))
            if len(keys) == 1:
                raise real_requests.Timeout()
            return api(method, url, **kw)

        with patch(REQUEST, flaky), patch('odoo.addons.sourevo_eudr.models.sourevo_client.time.sleep'):
            self.coffee.product_tmpl_id.action_sourevo_send()
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], keys[1])

    def test_cron_brings_the_reference(self):
        picking = self._receipt()
        api = FakeSourevo({('POST', '/dds/dds1/submit'): dds_json('SUBMITTED', simulated=False),
                           ('POST', '/dds/dds1/refresh'): dds_json('AVAILABLE', '26ESABCDEF', 'VER123', simulated=False),
                           ('GET', '/dds/dds1/check'): {'ready': True, 'blocking': [], 'warnings': []}})
        with patch(REQUEST, api):
            action = picking.action_sourevo_submit()
            self.env['sourevo.dds.submit'].browse(action['res_id']).action_submit()
            self.assertEqual(picking.sourevo_state, 'submitted')
            self.env['sourevo.dds']._cron_sourevo_update()
        self.assertIn('/dds/dds1/refresh', api.paths('POST'))
        self.assertEqual(picking.sourevo_dds_ids.reference_number, '26ESABCDEF')
        self.assertEqual(picking.sourevo_state, 'done')

    def test_upload_plots(self):
        geojson = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {'ProductionPlace': 'Finca 7'},
                   'geometry': {'type': 'Polygon', 'coordinates': [[[-4.01, 5.36], [-4.0, 5.36], [-4.0, 5.37], [-4.01, 5.36]]]}}]}
        api = FakeSourevo({('POST', '/suppliers/sup1/plots'): (201, {'skippedDuplicates': 1, 'data': [
            plot_json('plot7', 'Finca 7', 'DECLARED', {'status': 'PENDING', 'uploadedAt': '2026-11-03T10:00:00Z',
                                                     'confirmedAt': None, 'rejectedAt': None, 'rejectionReason': None})]})})
        wizard = self.env['sourevo.plot.upload'].create({
            'partner_id': self.supplier.id, 'file': base64.b64encode(json.dumps(geojson).encode()).decode()})
        with patch(REQUEST, api):
            wizard.action_upload()
        upload = next(c for c in api.calls if c['path'] == '/suppliers/sup1/plots')
        self.assertEqual(upload['json']['geojson'], geojson)
        self.assertEqual(upload['json']['country'], 'BR')
        plot = self.supplier.sourevo_plot_ids.filtered(lambda p: p.sourevo_id == 'plot7')
        self.assertEqual(plot.proposal_status, 'PENDING')
        self.assertTrue(plot.usable, 'Sourevo only warns about a proposal the supplier has not confirmed')

    def test_signature(self):
        body = b'{"id":"evt"}'
        now = int(time.time())
        good = hmac.new(b'whsec_x', f'{now}.'.encode() + body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature('whsec_x', body, f't={now},v1={good}'))
        self.assertFalse(verify_signature('whsec_y', body, f't={now},v1={good}'))
        self.assertFalse(verify_signature('whsec_x', body + b' ', f't={now},v1={good}'))
        self.assertFalse(verify_signature('whsec_x', body, f't={now},v1={good}', now=now + 301))
        self.assertFalse(verify_signature('whsec_x', body, 'garbage'))


@tagged('post_install', '-at_install')
class TestSourevoWebhook(HttpCase, SourevoCommon):

    def _post(self, event, secret='whsec_test', timestamp=None):
        body = json.dumps(event).encode()
        t = timestamp or int(time.time())
        sig = hmac.new(secret.encode(), f'{t}.'.encode() + body, hashlib.sha256).hexdigest()
        return self.url_open(f'/sourevo/webhook/{self.company.id}', data=body,
                             headers={'Content-Type': 'application/json', 'X-Sourevo-Signature': f't={t},v1={sig}'})

    def test_webhook(self):
        self.company.sudo().sourevo_webhook_secret = 'whsec_test'
        picking = self._receipt()
        with patch(REQUEST, FakeSourevo()):
            picking.action_sourevo_prepare()
        line = picking.sourevo_dds_ids
        line.write({'sourevo_dds_id': 'dds1', 'status': 'SUBMITTED'})
        event = {'id': 'evt1', 'type': 'dds.status_changed', 'createdAt': '2026-11-03T10:00:00Z',
                 'data': {'dds': dds_json('AVAILABLE', '26ESWEBHOOK', 'VERW', simulated=False),
                          'previousStatus': 'SUBMITTED', 'status': 'AVAILABLE'}}
        self.assertEqual(self._post(event, secret='whsec_wrong').status_code, 401)
        self.assertEqual(self._post(event, timestamp=int(time.time()) - 600).status_code, 401)
        self.assertEqual(self._post(event).status_code, 200)
        line.invalidate_recordset()
        self.assertEqual(line.reference_number, '26ESWEBHOOK')
        self.assertEqual(line.status, 'AVAILABLE')
        # A retry repeats the event id: handled once.
        line.write({'reference_number': False})
        self.assertEqual(self._post(event).status_code, 200)
        line.invalidate_recordset()
        self.assertFalse(line.reference_number)

        rejected = {'id': 'evt2', 'type': 'plot.proposal_answered', 'createdAt': '2026-11-03T10:00:00Z',
                    'data': {'answer': 'REJECTED', 'reason': 'Not our land',
                             'plot': plot_json('plot9', 'Finca 9', 'DECLARED',
                                               {'status': 'REJECTED', 'uploadedAt': '2026-11-01T10:00:00Z', 'confirmedAt': None,
                                                'rejectedAt': '2026-11-03T10:00:00Z', 'rejectionReason': 'Not our land'})}}
        self.assertEqual(self._post(rejected).status_code, 200)
        plot = self.env['sourevo.plot'].search([('sourevo_id', '=', 'plot9')])
        self.assertEqual(plot.proposal_status, 'REJECTED')
        self.assertIn('Not our land', self.supplier.activity_ids[-1:].note or '')

        self.assertEqual(self._post({'id': 'evt3', 'type': 'ping', 'createdAt': '2026-11-03T10:00:00Z', 'data': {}}).status_code, 200)
