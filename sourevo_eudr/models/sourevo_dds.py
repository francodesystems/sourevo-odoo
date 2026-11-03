import json
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.modules import module as odoo_module

from .check_messages import issue_text
from .res_company import ACTIVITY_TYPES, OPERATOR_ROLES, REPRESENTED_ROLES
from .sourevo_client import SourevoClient, SourevoError

_logger = logging.getLogger(__name__)

DDS_STATUSES = [
    ('new', 'Not sent'),
    ('DRAFT', 'Draft'),
    ('SUBMITTED', 'Submitted'),
    ('AVAILABLE', 'Available'),
    ('REJECTED', 'Rejected'),
    ('CANCELLED', 'Cancelled'),
    ('WITHDRAWN', 'Withdrawn'),
    ('ARCHIVED', 'Archived'),
]
RISK_CONCLUSIONS = [
    ('NEGLIGIBLE', 'Negligible risk'),
    ('NON_NEGLIGIBLE_MITIGATED', 'Non-negligible risk, mitigated'),
]


def same_kind(uom, reference):
    """Whether ``uom`` measures the same thing as ``reference`` (both weights, both volumes)."""
    if 'category_id' in uom._fields:
        return uom.category_id == reference.category_id
    return uom._has_common_reference(reference)


class SourevoDds(models.Model):
    """The due diligence statement of one EUDR product of a goods receipt.

    In Sourevo a batch has a single product, so a receipt with several EUDR
    products has one batch and one statement for each of them.
    """

    _name = 'sourevo.dds'
    _description = 'EUDR due diligence statement'
    _order = 'picking_id desc, id'

    name = fields.Char('Internal reference', required=True,
                       help='Unique per operator; TRACES accepts 50 characters. By default, the receipt.')
    picking_id = fields.Many2one('stock.picking', 'Receipt', required=True, ondelete='cascade', index=True, readonly=True)
    company_id = fields.Many2one(related='picking_id.company_id', store=True)
    product_id = fields.Many2one('product.product', 'Product', required=True, readonly=True)
    partner_id = fields.Many2one('res.partner', 'Supplier', required=True, readonly=True)
    quantity = fields.Float('Quantity', digits='Product Unit', readonly=True)
    uom_name = fields.Char('Unit', readonly=True)
    net_weight_kg = fields.Float('Net weight (kg)', digits=(16, 3))
    volume_m3 = fields.Float('Volume (m³)', digits=(16, 3))
    supplementary_unit = fields.Char('Supplementary unit', size=10)
    supplementary_qty = fields.Float('Supplementary quantity', digits=(16, 3))
    plot_ids = fields.Many2many('sourevo.plot', string='Origin plots', domain="[('partner_id', '=', partner_id)]")
    operator_id = fields.Many2one('sourevo.operator', 'TRACES operator', domain="[('company_id', '=', company_id)]")
    operator_role = fields.Selection(OPERATOR_ROLES, 'Operator role', required=True, default='OPERATOR')
    represented_role = fields.Selection(REPRESENTED_ROLES, 'Represented role')
    activity_type = fields.Selection(ACTIVITY_TYPES, 'Activity', required=True, default='IMPORT')
    country_id = fields.Many2one('res.country', 'Country of activity', required=True)
    comment = fields.Text('Comment')
    risk_conclusion = fields.Selection(RISK_CONCLUSIONS, 'Risk assessment')
    risk_notes = fields.Text('Risk assessment notes')

    sourevo_batch_id = fields.Char('Sourevo batch', copy=False, readonly=True)
    sourevo_dds_id = fields.Char('Sourevo statement', copy=False, readonly=True, index=True)
    status = fields.Selection(DDS_STATUSES, 'Status', default='new', required=True, readonly=True, copy=False)
    submitting = fields.Boolean('Being submitted', readonly=True, copy=False)
    simulated = fields.Boolean('Simulated', readonly=True, copy=False,
                               help='Submitted to the simulated TRACES of the Sourevo trial: it never reached the Commission.')
    reference_number = fields.Char('Reference number', readonly=True, copy=False,
                                   help='The TRACES reference number that customs ask for.')
    verification_number = fields.Char('Verification number', readonly=True, copy=False)
    traces_uuid = fields.Char('TRACES UUID', readonly=True, copy=False)
    check_date = fields.Datetime('Checked on', readonly=True, copy=False)
    check_ready = fields.Boolean('Ready to submit', readonly=True, copy=False)
    check_blocking = fields.Text('Blocking issues', readonly=True, copy=False)
    check_warnings = fields.Text('Warnings', readonly=True, copy=False)
    check_warning_keys = fields.Text(readonly=True, copy=False)
    check_blocking_codes = fields.Char(readonly=True, copy=False)
    last_synced = fields.Datetime('Updated from Sourevo', readonly=True, copy=False)
    locked = fields.Boolean(compute='_compute_locked')

    @api.depends('sourevo_batch_id', 'status')
    def _compute_locked(self):
        for line in self:
            line.locked = bool(line.sourevo_batch_id) or line.status != 'new'

    # Preparing the lines of a receipt

    @api.model
    def _sourevo_quantities(self, product, moves):
        """Quantity, unit, net weight in kg and volume in m³ of ``moves`` of ``product``."""
        kg = self.env.ref('uom.product_uom_kgm')
        m3 = self.env.ref('uom.product_uom_cubic_meter', raise_if_not_found=False)
        quantity = weight = volume = 0.0
        for move in moves:
            uom = move.uom_id if 'uom_id' in move._fields else move.product_uom
            qty = move.quantity or move.product_uom_qty
            quantity += uom._compute_quantity(qty, product.uom_id)
            if same_kind(uom, kg):
                weight += uom._compute_quantity(qty, kg)
            elif m3 and same_kind(uom, m3):
                volume += uom._compute_quantity(qty, m3)
        if not weight and product.weight and not same_kind(product.uom_id, kg):
            weight_uom = product.product_tmpl_id._get_weight_uom_id_from_ir_config_parameter()
            weight = weight_uom._compute_quantity(product.weight * quantity, kg)
        return quantity, product.uom_id.name, round(weight, 3), round(volume, 3)

    @api.model
    def _sourevo_default_plots(self, partner):
        usable = partner.sourevo_plot_ids.filtered(lambda p: p.usable and p.company_id == self.env.company)
        return usable.filtered(lambda p: p.verification_status == 'VERIFIED') or usable

    @api.model
    def _sourevo_prepare(self, picking):
        """One line per EUDR product of the receipt not prepared yet; returns the new lines."""
        company = picking.company_id
        partner = picking.partner_id.commercial_partner_id
        if not partner:
            raise UserError(_('The receipt %s has no supplier.', picking.name))
        if not partner.sourevo_supplier_id:
            partner._sourevo_ensure_supplier()
        partner.action_sourevo_refresh()
        moves = picking.move_ids.filtered(lambda m: m.state != 'cancel' and m.product_id.eudr_relevant)
        done = picking.sourevo_dds_ids.mapped('product_id')
        products = moves.mapped('product_id') - done
        several = len(moves.mapped('product_id')) > 1
        country = company.country_id or self.env.ref('base.es', raise_if_not_found=False)
        lines = self.browse()
        for index, product in enumerate(products, start=len(done) + 1):
            quantity, uom_name, weight, volume = self._sourevo_quantities(product, moves.filtered(lambda m: m.product_id == product))
            template = product.product_tmpl_id
            vals = {
                'name': f'{picking.name}-{index}' if several else picking.name,
                'picking_id': picking.id, 'product_id': product.id, 'partner_id': partner.id,
                'quantity': quantity, 'uom_name': uom_name, 'net_weight_kg': weight, 'volume_m3': volume,
                'plot_ids': [(6, 0, self._sourevo_default_plots(partner).ids)],
                'operator_id': company.sourevo_operator_id.id,
                'operator_role': company.sourevo_operator_role or 'OPERATOR',
                'represented_role': company.sourevo_represented_role,
                'activity_type': company.sourevo_activity_type or 'IMPORT',
                'country_id': country.id if country else False,
            }
            if template.eudr_supplementary_unit:
                vals.update(supplementary_unit=template.eudr_supplementary_unit, supplementary_qty=quantity)
            lines |= self.create(vals)
        return lines

    # Sending to Sourevo

    def _sourevo_batch_payload(self):
        self.ensure_one()
        if not self.net_weight_kg and not self.volume_m3:
            raise UserError(_(
                'Enter the net weight in kg of %(product)s in %(receipt)s: its unit is not a weight and the product '
                'has no weight.', product=self.product_id.display_name, receipt=self.picking_id.name))
        payload = {
            'productId': self.product_id.product_tmpl_id._sourevo_ensure_product(),
            'externalRef': f'{self.picking_id.name}/{self.id}'[:100],
            'plotIds': self.plot_ids.mapped('sourevo_id'),
        }
        if self.net_weight_kg:
            payload['netWeightKg'] = round(self.net_weight_kg, 3)
        if self.volume_m3:
            payload['volumeM3'] = round(self.volume_m3, 3)
        if self.supplementary_unit and self.supplementary_qty:
            payload['supplementaryUnit'] = self.supplementary_unit
            payload['supplementaryUnitQuantity'] = self.supplementary_qty
        return payload

    def _sourevo_dds_payload(self):
        self.ensure_one()
        if not self.operator_id:
            raise UserError(_('Choose the TRACES operator of %s (Settings > Sourevo sets the default one).', self.name))
        if self.operator_role == 'AUTHORISED_REPRESENTATIVE' and not self.represented_role:
            raise UserError(_('An authorised representative needs the represented role (%s).', self.name))
        payload = {
            'batchId': self.sourevo_batch_id,
            'operatorId': self.operator_id.sourevo_id,
            'internalReferenceNumber': self.name,
            'activityType': self.activity_type,
            'operatorRole': self.operator_role,
            'countryOfActivity': self.country_id.code,
        }
        if self.operator_role == 'AUTHORISED_REPRESENTATIVE':
            payload['representedRole'] = self.represented_role
        if self.comment:
            payload['comment'] = self.comment
        if self.risk_conclusion:
            if not (self.risk_notes or '').strip():
                raise UserError(_('The risk assessment of %s needs its notes.', self.name))
            payload['riskAssessment'] = {'conclusion': self.risk_conclusion, 'notes': self.risk_notes.strip()}
        return payload

    def _sourevo_create_remote(self):
        """Creates the batch and the draft statement in Sourevo for the lines that do not have them."""
        client = SourevoClient(self.env.company)
        for line in self.filtered(lambda l: l.status == 'new'):
            if not line.sourevo_batch_id:
                # Safe to repeat: the same externalRef returns the same batch.
                line.sourevo_batch_id = client.create_batch(line._sourevo_batch_payload())['id']
            line._sourevo_apply(client.create_dds(line._sourevo_dds_payload()))
            # The draft exists in Sourevo now: an error on the next line must not lose it.
            line._sourevo_commit()

    def _sourevo_check(self):
        client = SourevoClient(self.env.company)
        for line in self.filtered(lambda l: l.status == 'DRAFT' and l.sourevo_dds_id):
            report = client.check_dds(line.sourevo_dds_id)
            line._sourevo_apply_check(report)

    def _sourevo_apply_check(self, report):
        self.ensure_one()
        names = {p.sourevo_id: p.name for p in self.plot_ids}
        lang = self.env.lang or self.env.user.lang or 'en_US'
        blocking = report.get('blocking') or []
        warnings = report.get('warnings') or []
        self.write({
            'check_date': fields.Datetime.now(),
            'check_ready': bool(report.get('ready')) and not blocking,
            'check_blocking': '\n'.join(issue_text(i, names, lang) for i in blocking) or False,
            'check_warnings': '\n'.join(issue_text(i, names, lang) for i in warnings) or False,
            'check_warning_keys': json.dumps([i['key'] for i in warnings if i.get('key')]),
            'check_blocking_codes': ','.join(i.get('code') or '' for i in blocking) or False,
        })

    def _sourevo_submit(self):
        client = SourevoClient(self.env.company)
        for line in self.filtered(lambda l: l.status == 'DRAFT' and l.check_ready):
            keys = json.loads(line.check_warning_keys or '[]')
            try:
                data = client.submit_dds(line.sourevo_dds_id, keys)
            except SourevoError as e:
                if e.reason in ('acknowledgement_required', 'pre_submission_blocked'):
                    line._sourevo_check()
                raise
            line._sourevo_apply(data)
            line._sourevo_commit()

    def _sourevo_apply(self, dds):
        """Brings a Dds of the API to the line; tells the receipt when TRACES gives the reference."""
        for line in self:
            before = (line.status, line.reference_number)
            vals = {
                'sourevo_dds_id': dds.get('id') or line.sourevo_dds_id,
                'status': dds.get('status') or line.status,
                'submitting': bool(dds.get('submitting')),
                'simulated': bool(dds.get('simulated')),
                'reference_number': dds.get('referenceNumber') or line.reference_number,
                'verification_number': dds.get('verificationNumber') or line.verification_number,
                'traces_uuid': dds.get('tracesUuid') or line.traces_uuid,
                'last_synced': fields.Datetime.now(),
            }
            if dds.get('batchId'):
                vals['sourevo_batch_id'] = dds['batchId']
            line.write(vals)
            line._sourevo_notify_change(*before)

    def _sourevo_notify_change(self, old_status, old_reference):
        self.ensure_one()
        picking = self.picking_id
        if self.reference_number and self.reference_number != old_reference:
            body = _('Due diligence statement %(name)s (%(product)s) in TRACES: reference number %(ref)s, '
                     'verification number %(ver)s.', name=self.name, product=self.product_id.display_name,
                     ref=self.reference_number, ver=self.verification_number or '—')
            if self.simulated:
                body += ' ' + _('Simulated (Sourevo trial): it never reached TRACES.')
            picking.message_post(body=body)
        if self.status != old_status and self.status in ('REJECTED', 'CANCELLED', 'WITHDRAWN'):
            label = dict(self._fields['status']._description_selection(self.env)).get(self.status)
            picking.activity_schedule(
                'mail.mail_activity_data_todo', user_id=picking.user_id.id or self.env.uid,
                summary=_('EUDR statement %(name)s: %(status)s', name=self.name, status=label),
                note=_('TRACES changed the status of the statement %(name)s to %(status)s. Review it in Sourevo.',
                       name=self.name, status=label))

    def _sourevo_commit(self):
        # Not in tests: their transaction is rolled back at the end.
        if not odoo_module.current_test:
            self.env.cr.commit()

    # Buttons

    def action_sourevo_refresh(self):
        client = SourevoClient(self.env.company)
        for line in self.filtered('sourevo_dds_id'):
            line._sourevo_apply(line._sourevo_fetch(client))
        return True

    def _sourevo_fetch(self, client):
        """The statement as TRACES has it now: POST refresh when it is in TRACES, GET otherwise."""
        self.ensure_one()
        if self.status in ('SUBMITTED', 'AVAILABLE') and not self.simulated:
            try:
                return client.refresh_dds(self.sourevo_dds_id)
            except SourevoError as e:
                _logger.info('Sourevo refresh of %s failed (%s), reading it instead', self.sourevo_dds_id, e)
        return client.dds(self.sourevo_dds_id)

    def action_sourevo_discard(self):
        """Deletes the draft in Sourevo and the line in Odoo: prepare the receipt again to start over."""
        client = SourevoClient(self.env.company)
        for line in self:
            if line.status not in ('new', 'DRAFT'):
                raise UserError(_('%s is already in TRACES: retract it in Sourevo.', line.name))
            if line.sourevo_dds_id:
                try:
                    client.delete_dds(line.sourevo_dds_id)
                except SourevoError as e:
                    if e.status != 404:
                        raise
        self.unlink()
        return True

    # Scheduled action

    @api.model
    def _cron_sourevo_update(self, companies=None):
        """Every 15 minutes: the statements waiting for TRACES, for databases the webhook cannot reach."""
        companies = companies or self.env['res.company'].sudo().search([('sourevo_api_key', '!=', False)])
        for company in companies:
            lines = self.sudo().search([
                ('company_id', '=', company.id), ('sourevo_dds_id', '!=', False),
                '|', ('submitting', '=', True),
                '&', ('status', 'in', ('SUBMITTED', 'AVAILABLE')), ('reference_number', '=', False),
            ], limit=100)
            if not lines:
                company.sudo().sourevo_last_sync = fields.Datetime.now()
                continue
            lines = lines.with_company(company)
            try:
                client = SourevoClient(company)
                for line in lines:
                    line._sourevo_apply(line._sourevo_fetch(client))
                    line._sourevo_commit()
                company.sudo().sourevo_last_sync = fields.Datetime.now()
            except UserError as e:
                if not odoo_module.current_test:
                    self.env.cr.rollback()
                _logger.warning('Sourevo update of %s failed: %s', company.name, e)
        self.env['sourevo.webhook.event'].sudo().search(
            [('create_date', '<', fields.Datetime.now() - timedelta(days=7))]).unlink()

