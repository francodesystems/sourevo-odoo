import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .product_template import normalize_cn
from .trade_client import SourevoTradeClient, SourevoTradeError

_logger = logging.getLogger(__name__)

# Errors worth retrying alone: the next run of the scheduled action sends the line again.
TRANSIENT = ('timeout', 'network', 'rate_limited', 'service_unavailable', 'internal_error')


class SourevoTradeLine(models.Model):
    """One EUDR move of a validated receipt (a purchase in Sourevo) or delivery (a sale)."""

    _name = 'sourevo.trade.line'
    _description = 'EUDR register line'
    _order = 'id'

    picking_id = fields.Many2one('stock.picking', required=True, ondelete='cascade', index=True)
    move_id = fields.Many2one('stock.move', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='picking_id.company_id', store=True)
    direction = fields.Selection([('in', 'Purchase'), ('out', 'Sale')], required=True)
    product_id = fields.Many2one(related='move_id.product_id')
    sourevo_id = fields.Char('Sourevo record', readonly=True, copy=False)
    state = fields.Selection([('pending', 'To send'), ('sent', 'In Sourevo'), ('error', 'Error')], default='pending',
                             required=True, readonly=True)
    error = fields.Char(readonly=True)
    transient = fields.Boolean(readonly=True)
    warning = fields.Char('Sourevo warning', readonly=True)

    _sql_constraints = [('move_uniq', 'unique(move_id)', 'An EUDR move is recorded once.')]

    def _external_ref(self):
        return f'odoo:{self.env.cr.dbname}:move:{self.move_id.id}'

    def _quantity(self):
        move = self.move_id
        uom = move['uom_id' if 'uom_id' in move._fields else 'product_uom']
        return round(uom._compute_quantity(move.quantity, move.product_id.uom_id), 3)

    def _line_payload(self):
        move = self.move_id
        template = move.product_id.product_tmpl_id
        return {
            'date': fields.Date.to_string(self.picking_id.date_done or fields.Datetime.now()),
            'description': (move.product_id.display_name or move.name or '')[:300],
            'cnCode': normalize_cn(template.sourevo_trade_cn_code),
            'quantity': self._quantity(),
            'unit': template.sourevo_trade_unit or 'kg',
            'externalRef': self._external_ref(),
        }

    def _send_purchase(self, client):
        picking = self.picking_id
        partner = picking.partner_id.commercial_partner_id
        if not partner:
            raise UserError(_('The receipt %s has no supplier.', picking.name))
        references = picking.sourevo_trade_reference_ids.filtered(lambda r: r.state == 'accepted')
        data = client.create_purchase(dict(self._line_payload(), partnerId=partner._sourevo_trade_sync(client, supplier=True),
                                           references=[r._payload() for r in references]))
        known = {(r.get('referenceNumber'), r.get('verificationNumber')) for r in data.get('references') or []}
        for ref in references:
            if (ref.reference_number.strip(), ref.verification_number.strip()) not in known:
                data = client.add_reference(data['id'], ref._payload())
        return data

    def _send_sale(self, client):
        picking = self.picking_id
        partner = picking.partner_id.commercial_partner_id
        sources = picking.sourevo_trade_source_picking_ids
        sources.sourevo_trade_line_ids.filtered(lambda l: l.state != 'sent')._sourevo_trade_send(silent=True)
        in_lines = sources.sourevo_trade_line_ids.filtered(lambda l: l.sourevo_id)
        # Same product first; a downstream operator that transforms links all the inputs.
        same = in_lines.filtered(lambda l: l.product_id == self.product_id)
        purchase_ids = (same or in_lines).mapped('sourevo_id')
        consumer = not partner or partner.sourevo_trade_consumer
        partner_id = None if consumer else partner._sourevo_trade_sync(client, customer=True)
        return client.create_sale(dict(self._line_payload(), partnerId=partner_id, purchaseIds=purchase_ids))

    def _sourevo_trade_send(self, silent=False):
        """Sends each line (again); an error stays on the line instead of stopping the caller."""
        for line in self:
            company = line.picking_id.company_id
            if not company.sudo().sourevo_trade_api_key:
                continue
            try:
                client = SourevoTradeClient(company)
                data = line._send_purchase(client) if line.direction == 'in' else line._send_sale(client)
                warnings = data.get('warnings') or []
                line.write({'sourevo_id': data['id'], 'state': 'sent', 'error': False, 'transient': False,
                            'warning': _('No reference number: an operator must give you one (EUDR Art. 5.1).')
                            if 'missing_reference' in warnings else False})
                if line.direction == 'in':
                    line.picking_id._sourevo_trade_take_proposals(data)
            except SourevoTradeError as e:
                line.write({'state': 'error', 'error': str(e), 'transient': (e.code or e.reason) in TRANSIENT or (e.status or 0) >= 500})
                if not silent:
                    raise
            except UserError as e:
                line.write({'state': 'error', 'error': str(e), 'transient': False})
                if not silent:
                    raise

    @api.model
    def _cron_sourevo_trade(self, companies=None):
        """Sends what is pending or failed for a passing reason, and reads the proposals of receipts still waiting."""
        companies = companies or self.env['res.company'].sudo().search([('sourevo_trade_api_key', '!=', False)])
        for company in companies:
            lines = self.sudo().search([('company_id', '=', company.id), '|', ('state', '=', 'pending'),
                                        '&', ('state', '=', 'error'), ('transient', '=', True)], limit=200)
            lines._sourevo_trade_send(silent=True)
            waiting = self.env['stock.picking'].sudo().search([
                ('company_id', '=', company.id), ('sourevo_trade_asked_at', '!=', False), ('sourevo_trade_missing', '=', True)], limit=100)
            client = SourevoTradeClient(company)
            for picking in waiting:
                for line in picking.sourevo_trade_line_ids.filtered(lambda l: l.direction == 'in' and l.sourevo_id)[:1]:
                    try:
                        picking._sourevo_trade_take_proposals(client.purchase(line.sourevo_id))
                    except SourevoTradeError as e:
                        _logger.info('Sourevo Lite: %s', e)
            company.sudo().sourevo_trade_last_sync = fields.Datetime.now()
