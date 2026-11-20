import hashlib
import hmac
import json
import re
import time
from unittest.mock import patch

import requests

from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, tagged

REQUEST = 'odoo.addons.sourevo_eudr_lite.models.trade_client.requests.request'


class FakeResponse:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data


def purchase_json(id_='pur1', references=(), warnings=()):
    return {'id': id_, 'partner': {'id': 'par1'}, 'date': '2026-12-31', 'description': 'Green coffee', 'cnCode': '09011100',
            'quantity': 1000, 'unit': 'kg', 'externalRef': 'x', 'archived': False, 'references': list(references),
            'warnings': list(warnings)}


def ref_json(id_='ref1', number='25ESAAA', verification='VERIF1', state='ACCEPTED'):
    return {'id': id_, 'kind': 'DDS', 'referenceNumber': number, 'verificationNumber': verification, 'state': state,
            'source': 'SUPPLIER_LINK' if state == 'PROPOSED' else 'IMPORTER', 'removed': False, 'tracesCheck': None,
            'createdAt': '2026-12-31T10:00:00Z'}


class FakeSourevo:
    """Answers like the /trade endpoints of the Sourevo API; ``routes`` overrides an answer by (method, path)."""

    def __init__(self, routes=None):
        self.calls = []
        self.routes = routes or {}
        self.purchases = 0
        self.sales = 0

    def __call__(self, method, url, json=None, params=None, headers=None, timeout=None):
        path = re.sub(r'^https://sourevo\.test/api/v1', '', url)
        self.calls.append({'method': method, 'path': path, 'json': json, 'params': params, 'headers': headers})
        if (method, path) in self.routes:
            answer = self.routes[(method, path)]
            if isinstance(answer, Exception):
                raise answer
            return FakeResponse(*answer) if isinstance(answer, tuple) else FakeResponse(200, answer)
        if (method, path) == ('POST', '/trade/partners'):
            return FakeResponse(201, dict(json, id=f'par-{json["externalRef"]}'))
        if method == 'PATCH' and path.startswith('/trade/partners/'):
            return FakeResponse(200, dict(json, id=path.split('/')[-1]))
        if (method, path) == ('POST', '/trade/purchases'):
            self.purchases += 1
            refs = [ref_json(f'ref{self.purchases}{i}', r['referenceNumber'], r['verificationNumber'])
                    for i, r in enumerate(json.get('references') or [])]
            return FakeResponse(201, purchase_json(f'pur{self.purchases}', refs, () if refs else ('missing_reference',)))
        if (method, path) == ('POST', '/trade/sales'):
            self.sales += 1
            return FakeResponse(201, dict(json, id=f'sal{self.sales}', references=[]))
        if method == 'POST' and path.endswith('/reference-request'):
            return FakeResponse(201, {'requestId': 'req1', 'email': 'ops@import.test', 'emailed': True,
                                      'expiresAt': '2027-01-30T00:00:00Z'})
        if method == 'POST' and path.endswith('/decision'):
            return FakeResponse(200, purchase_json())
        if (method, path) == ('GET', '/me'):
            return FakeResponse(200, {'organization': {'id': 'org1', 'name': 'Tostadores Norte', 'taxId': 'ESB1'},
                                      'mode': 'simulated', 'plan': {'status': 'notImporter'}, 'role': 'OWNER',
                                      'trade': {'role': 'TRADER', 'since': '2026-11-19T10:00:00Z'}})
        return FakeResponse(404, {'error': {'code': 'not_found', 'message': f'{method} {path}'}})

    def paths(self, method=None):
        return [c['path'] for c in self.calls if not method or c['method'] == method]


class LiteCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.sudo().write({'sourevo_trade_api_key': 'svk_test', 'sourevo_trade_url': 'https://sourevo.test/api/v1'})
        cls.supplier = cls.env['res.partner'].create({
            'name': 'Import SA', 'is_company': True, 'country_id': cls.env.ref('base.fr').id, 'email': 'ops@import.test',
            'street': 'Quai 1', 'zip': '76600', 'city': 'Le Havre', 'sourevo_trade_supplier_kind': 'OPERATOR'})
        cls.customer = cls.env['res.partner'].create({
            'name': 'Café Bar SL', 'is_company': True, 'country_id': cls.env.ref('base.es').id, 'email': 'bar@test.es',
            'street': 'Calle 2', 'city': 'Madrid'})
        storable = {'is_storable': True} if 'is_storable' in cls.env['product.template']._fields else {'type': 'product'}
        cls.coffee = cls.env['product.product'].create({
            'name': 'Green coffee', 'uom_id': cls.env.ref('uom.product_uom_kgm').id, 'tracking': 'lot', **storable,
            'sourevo_trade_eudr': True, 'sourevo_trade_cn_code': '0901 11 00', 'sourevo_trade_unit': 'kg'})
        cls.wh = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)

    def _picking(self, kind, partner, qty, lot=None):
        incoming = kind == 'in'
        outer = self.env.ref('stock.stock_location_suppliers' if incoming else 'stock.stock_location_customers')
        src, dst = (outer, self.wh.lot_stock_id) if incoming else (self.wh.lot_stock_id, outer)
        move = {'product_id': self.coffee.id, 'product_uom_qty': qty, 'location_id': src.id, 'location_dest_id': dst.id}
        if 'name' in self.env['stock.move']._fields:
            move['name'] = self.coffee.name
        picking = self.env['stock.picking'].create({
            'picking_type_id': (self.wh.in_type_id if incoming else self.wh.out_type_id).id, 'partner_id': partner.id,
            'location_id': src.id, 'location_dest_id': dst.id, 'move_ids': [(0, 0, move)]})
        picking.action_confirm()
        picking.action_assign()
        if incoming:
            for ml in picking.move_ids.move_line_ids:
                ml.write({'lot_name': lot or 'LOT1', 'quantity': qty})
        picking.move_ids.picked = True
        return picking

    def _receive(self, api, qty=1000.0, refs=(), lot='LOT1'):
        picking = self._picking('in', self.supplier, qty, lot)
        for number, verification in refs:
            self.env['sourevo.trade.reference'].create({'picking_id': picking.id, 'reference_number': number,
                                                        'verification_number': verification})
        with patch(REQUEST, api):
            picking._action_done()
        return picking


@tagged('post_install', '-at_install')
class TestLiteFlow(LiteCommon):

    def test_receipt_with_number_becomes_a_purchase(self):
        api = FakeSourevo()
        picking = self._receive(api, refs=[('25FRAAA', 'VERIF1')])
        self.assertEqual(picking.state, 'done')
        line = picking.sourevo_trade_line_ids
        self.assertEqual((line.state, line.sourevo_id, line.direction), ('sent', 'pur1', 'in'))
        partner_call = next(c for c in api.calls if c['path'] == '/trade/partners')
        self.assertEqual(partner_call['json']['supplierKind'], 'OPERATOR')
        self.assertEqual(partner_call['json']['postalAddress'], 'Quai 1, 76600 Le Havre, France')
        self.assertTrue(partner_call['headers']['Idempotency-Key'])
        body = next(c for c in api.calls if c['path'] == '/trade/purchases')['json']
        self.assertEqual((body['cnCode'], body['quantity'], body['unit']), ('09011100', 1000.0, 'kg'))
        self.assertEqual(body['references'], [{'kind': 'DDS', 'referenceNumber': '25FRAAA', 'verificationNumber': 'VERIF1'}])
        self.assertTrue(body['externalRef'].endswith(f':move:{picking.move_ids.id}'))
        self.assertEqual(picking.sourevo_trade_reference_text, '25FRAAA / VERIF1')
        self.assertFalse(picking.sourevo_trade_missing)
        lot = picking.move_ids.move_line_ids.lot_id
        self.assertEqual(lot.sourevo_trade_reference_text, '25FRAAA / VERIF1')
        # The contact is sent once while it does not change.
        self._receive(api, lot='LOT2')
        self.assertEqual(api.paths().count('/trade/partners'), 1)

    def test_missing_number_ask_and_accept(self):
        api = FakeSourevo()
        picking = self._receive(api)
        self.assertTrue(picking.sourevo_trade_missing)
        self.assertTrue(picking.sourevo_trade_line_ids.warning)
        with patch(REQUEST, api):
            picking.action_sourevo_trade_ask()
        self.assertIn('/trade/purchases/pur1/reference-request', api.paths('POST'))
        self.assertTrue(picking.sourevo_trade_asked_at)
        # The scheduled action reads the proposal (no webhook on this database).
        api.routes[('GET', '/trade/purchases/pur1')] = purchase_json(references=[ref_json('rp1', '25FRBBB', 'VERIF2', 'PROPOSED')])
        with patch(REQUEST, api):
            self.env['sourevo.trade.line']._cron_sourevo_trade(companies=self.company)
            self.env['sourevo.trade.line']._cron_sourevo_trade(companies=self.company)
        proposal = picking.sourevo_trade_reference_ids
        self.assertEqual((len(proposal), proposal.state), (1, 'proposed'))
        self.assertTrue(picking.sourevo_trade_proposed)
        self.assertTrue(picking.activity_ids)
        with patch(REQUEST, api):
            proposal.action_accept()
        decision = next(c for c in api.calls if c['path'] == '/trade/references/rp1/decision')
        self.assertEqual(decision['json'], {'accept': True})
        self.assertEqual(proposal.state, 'accepted')
        self.assertFalse(picking.sourevo_trade_missing)

    def test_reject_needs_a_reason(self):
        api = FakeSourevo()
        picking = self._receive(api)
        ref = self.env['sourevo.trade.reference'].create({'picking_id': picking.id, 'reference_number': 'X1',
                                                          'verification_number': 'VERIF9', 'state': 'proposed',
                                                          'sourevo_reference_id': 'rp9'})
        wizard = self.env['sourevo.trade.reject'].create({'reference_id': ref.id, 'reason': 'Another delivery'})
        with patch(REQUEST, api):
            wizard.action_confirm()
        self.assertEqual((ref.state, ref.reject_reason), ('rejected', 'Another delivery'))
        self.assertEqual(api.calls[-1]['json'], {'accept': False, 'reason': 'Another delivery'})

    def test_delivery_inherits_from_lots_and_links_the_purchase(self):
        api = FakeSourevo()
        receipt = self._receive(api, refs=[('25FRAAA', 'VERIF1')])
        delivery = self._picking('out', self.customer, 400.0)
        self.assertEqual(delivery.sourevo_trade_source_picking_ids, receipt)
        self.assertEqual(delivery.sourevo_trade_reference_text, '25FRAAA / VERIF1')
        with patch(REQUEST, api):
            delivery._action_done()
        sale = next(c for c in api.calls if c['path'] == '/trade/sales')['json']
        self.assertEqual((sale['purchaseIds'], sale['quantity']), (['pur1'], 400.0))
        self.assertTrue(sale['partnerId'].startswith('par-'))
        customer_call = [c for c in api.calls if c['path'] == '/trade/partners'][-1]['json']
        self.assertEqual((customer_call['isCustomer'], customer_call['supplierKind']), (True, None))
        self.assertEqual(delivery.sourevo_trade_line_ids.state, 'sent')

    def test_final_consumer_without_partner_data(self):
        api = FakeSourevo()
        self._receive(api, refs=[('25FRAAA', 'VERIF1')])
        self.customer.write({'sourevo_trade_consumer': True, 'email': False})
        delivery = self._picking('out', self.customer, 10.0)
        with patch(REQUEST, api):
            delivery._action_done()
        sale = next(c for c in api.calls if c['path'] == '/trade/sales')['json']
        self.assertIsNone(sale['partnerId'])

    def test_network_failure_never_blocks_the_validation(self):
        api = FakeSourevo({('POST', '/trade/purchases'): requests.ConnectionError('down')})
        picking = self._receive(api, refs=[('25FRAAA', 'VERIF1')])
        self.assertEqual(picking.state, 'done')
        line = picking.sourevo_trade_line_ids
        self.assertEqual((line.state, line.transient), ('error', True))
        self.assertEqual(picking.sourevo_trade_state, 'error')
        del api.routes[('POST', '/trade/purchases')]
        with patch(REQUEST, api):
            self.env['sourevo.trade.line']._cron_sourevo_trade(companies=self.company)
        self.assertEqual(line.state, 'sent')

    def test_missing_contact_data_is_explained(self):
        api = FakeSourevo()
        self.supplier.email = False
        picking = self._receive(api)
        line = picking.sourevo_trade_line_ids
        self.assertEqual((line.state, line.transient), ('error', False))
        self.assertIn('email', line.error)
        with patch(REQUEST, api), self.assertRaises(UserError):
            picking.action_sourevo_trade_send()

    def test_errors_are_readable(self):
        api = FakeSourevo({('POST', '/trade/purchases'): (422, {'error': {'code': 'plan_not_allowed', 'message': 'x',
                                                                          'details': {'reason': 'trade_not_enabled'}}})})
        picking = self._receive(api)
        self.assertIn('Trade > Settings', picking.sourevo_trade_line_ids.error)

    def test_connection(self):
        settings = self.env['res.config.settings'].create({})
        api = FakeSourevo()
        with patch(REQUEST, api):
            action = settings.action_sourevo_trade_test()
        self.assertEqual(action['params']['type'], 'success')
        self.assertEqual(self.company.sourevo_trade_role, 'TRADER')
        api.routes[('GET', '/me')] = {'organization': {'name': 'Acme'}, 'trade': None}
        with patch(REQUEST, api):
            action = settings.action_sourevo_trade_test()
        self.assertEqual(action['params']['type'], 'warning')

    def test_reports_print_the_numbers(self):
        api = FakeSourevo()
        self._receive(api, refs=[('25FRAAA', 'VERIF1')])
        delivery = self._picking('out', self.customer, 400.0)
        with patch(REQUEST, api):
            delivery._action_done()
        html = self.env['ir.actions.report']._render_qweb_html('stock.report_deliveryslip', delivery.ids)[0]
        self.assertIn(b'25FRAAA / VERIF1', html)

    def test_invoice_prints_the_numbers_of_its_deliveries(self):
        api = FakeSourevo()
        self._receive(api, refs=[('25FRAAA', 'VERIF1')])
        order = self.env['sale.order'].create({'partner_id': self.customer.id, 'order_line': [
            (0, 0, {'product_id': self.coffee.id, 'product_uom_qty': 300.0, 'price_unit': 5.0})]})
        order.action_confirm()
        delivery = order.picking_ids
        delivery.action_assign()
        delivery.move_ids.picked = True
        with patch(REQUEST, api):
            delivery._action_done()
        invoice = order._create_invoices()
        self.assertEqual(invoice.sourevo_trade_reference_text, '25FRAAA / VERIF1')
        html = self.env['ir.actions.report']._render_qweb_html('account.report_invoice', invoice.ids)[0]
        self.assertIn(b'25FRAAA / VERIF1', html)


@tagged('post_install', '-at_install')
class TestLiteWebhook(HttpCase, LiteCommon):

    def _post(self, event, secret='whsec_test', timestamp=None):
        body = json.dumps(event).encode()
        t = timestamp or int(time.time())
        sig = hmac.new(secret.encode(), f'{t}.'.encode() + body, hashlib.sha256).hexdigest()
        return self.url_open(f'/sourevo/trade-webhook/{self.company.id}', data=body,
                             headers={'Content-Type': 'application/json', 'X-Sourevo-Signature': f't={t},v1={sig}'})

    def test_proposal_arrives(self):
        self.company.sudo().sourevo_trade_webhook_secret = 'whsec_test'
        picking = self._receive(FakeSourevo())
        event = {'id': 'evt1', 'type': 'trade.reference_proposed', 'createdAt': '2026-12-31T10:00:00Z',
                 'data': {'reference': ref_json('rp1', '25FRWEB', 'VERIFW', 'PROPOSED'),
                          'purchase': purchase_json('pur1', [ref_json('rp1', '25FRWEB', 'VERIFW', 'PROPOSED')])}}
        self.assertEqual(self._post(event, secret='whsec_wrong').status_code, 401)
        self.assertEqual(self._post(event).status_code, 200)
        self.assertEqual(self._post(event).status_code, 200)
        self.assertEqual(picking.sourevo_trade_reference_ids.mapped('reference_number'), ['25FRWEB'])
        self.assertEqual(self._post({'id': 'evt2', 'type': 'ping', 'createdAt': '2026-12-31T10:00:00Z', 'data': {}}).status_code, 200)
