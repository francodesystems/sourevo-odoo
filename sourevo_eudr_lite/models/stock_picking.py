from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .trade_client import SourevoTradeClient


def reference_text(references):
    return ', '.join(f'{r.reference_number} / {r.verification_number}' for r in references) or False


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    sourevo_trade_visible = fields.Boolean(compute='_compute_sourevo_trade_visible')
    sourevo_trade_reference_ids = fields.One2many('sourevo.trade.reference', 'picking_id', 'EUDR reference numbers')
    sourevo_trade_line_ids = fields.One2many('sourevo.trade.line', 'picking_id', 'EUDR register lines', readonly=True)
    sourevo_trade_source_picking_ids = fields.Many2many(
        'stock.picking', 'sourevo_trade_picking_source_rel', 'picking_id', 'source_id', 'EUDR receipts of origin',
        compute='_compute_sourevo_trade_sources', store=True, readonly=False,
        domain="[('picking_type_code', '=', 'incoming'), ('state', '=', 'done'), ('company_id', '=', company_id)]",
        help='The receipts whose reference numbers this delivery passes on: taken from the lots delivered; '
             'choose them when the products have no lots.')
    sourevo_trade_reference_text = fields.Char('EUDR numbers', compute='_compute_sourevo_trade_text',
                                               help='Reference and verification numbers of the due diligence statements.')
    sourevo_trade_missing = fields.Boolean('EUDR number missing', compute='_compute_sourevo_trade_missing', store=True)
    sourevo_trade_proposed = fields.Boolean(compute='_compute_sourevo_trade_proposed')
    sourevo_trade_state = fields.Selection([('none', 'Not recorded'), ('pending', 'To send'), ('sent', 'In Sourevo'),
                                            ('error', 'Error')], 'EUDR register', compute='_compute_sourevo_trade_state')
    sourevo_trade_error = fields.Char(compute='_compute_sourevo_trade_state')
    sourevo_trade_asked_at = fields.Datetime('Supplier asked on', readonly=True, copy=False)

    def _sourevo_trade_moves(self):
        self.ensure_one()
        return self.move_ids.filtered(lambda m: m.state != 'cancel' and m.product_id.product_tmpl_id.sourevo_trade_eudr)

    @api.depends('picking_type_code', 'move_ids.product_id')
    def _compute_sourevo_trade_visible(self):
        for picking in self:
            picking.sourevo_trade_visible = picking.picking_type_code in ('incoming', 'outgoing') and bool(picking._sourevo_trade_moves())

    @api.depends('picking_type_code', 'move_ids.move_line_ids.lot_id')
    def _compute_sourevo_trade_sources(self):
        for picking in self:
            if picking.picking_type_code != 'outgoing':
                picking.sourevo_trade_source_picking_ids = False
                continue
            lots = picking.move_ids.move_line_ids.lot_id
            if not lots:
                continue
            incoming = self.env['stock.move.line'].search([
                ('lot_id', 'in', lots.ids), ('state', '=', 'done'), ('picking_code', '=', 'incoming')])
            picking.sourevo_trade_source_picking_ids = incoming.picking_id

    @api.depends('picking_type_code', 'sourevo_trade_reference_ids.state', 'sourevo_trade_source_picking_ids')
    def _compute_sourevo_trade_text(self):
        for picking in self:
            if picking.picking_type_code == 'outgoing':
                refs = picking.sourevo_trade_source_picking_ids.sourevo_trade_reference_ids
            else:
                refs = picking.sourevo_trade_reference_ids
            picking.sourevo_trade_reference_text = reference_text(refs.filtered(lambda r: r.state == 'accepted'))

    @api.depends('picking_type_code', 'partner_id.sourevo_trade_supplier_kind', 'partner_id.commercial_partner_id',
                 'sourevo_trade_reference_ids.state', 'move_ids.product_id')
    def _compute_sourevo_trade_missing(self):
        for picking in self:
            operator = picking.partner_id.commercial_partner_id.sourevo_trade_supplier_kind == 'OPERATOR'
            picking.sourevo_trade_missing = (picking.picking_type_code == 'incoming' and operator
                                             and bool(picking._sourevo_trade_moves())
                                             and not picking.sourevo_trade_reference_ids.filtered(lambda r: r.state == 'accepted'))

    @api.depends('sourevo_trade_reference_ids.state')
    def _compute_sourevo_trade_proposed(self):
        for picking in self:
            picking.sourevo_trade_proposed = bool(picking.sourevo_trade_reference_ids.filtered(lambda r: r.state == 'proposed'))

    @api.depends('sourevo_trade_line_ids.state', 'sourevo_trade_line_ids.error')
    def _compute_sourevo_trade_state(self):
        for picking in self:
            states = set(picking.sourevo_trade_line_ids.mapped('state'))
            picking.sourevo_trade_state = ('error' if 'error' in states else 'pending' if 'pending' in states
                                           else 'sent' if states else 'none')
            picking.sourevo_trade_error = ' · '.join(filter(None, picking.sourevo_trade_line_ids.mapped('error'))) or False

    def _sourevo_trade_record(self):
        """One register line per EUDR move of each validated receipt or delivery; then sends them."""
        Line = self.env['sourevo.trade.line'].sudo()
        for picking in self.filtered(lambda p: p.state == 'done' and p.picking_type_code in ('incoming', 'outgoing')):
            known = picking.sourevo_trade_line_ids.move_id
            for move in picking._sourevo_trade_moves().filtered(lambda m: m.quantity and m not in known):
                Line.create({'picking_id': picking.id, 'move_id': move.id,
                             'direction': 'in' if picking.picking_type_code == 'incoming' else 'out'})
        # Receipts first: a delivery of the same batch links to their purchases.
        lines = self.sourevo_trade_line_ids.filtered(lambda l: l.state != 'sent').sorted(lambda l: l.direction != 'in')
        lines._sourevo_trade_send(silent=True)

    def _action_done(self):
        res = super()._action_done()
        # Recording never stops the validation: a failure stays on the line, shown in the EUDR tab.
        self._sourevo_trade_record()
        return res

    def action_sourevo_trade_send(self):
        self._sourevo_trade_record()
        failed = self.sourevo_trade_line_ids.filtered(lambda l: l.state == 'error')
        if failed:
            raise UserError(failed[0].error)
        return True

    def action_sourevo_trade_ask(self):
        """Sourevo emails the supplier a one-time link to type the number; the answer comes back as a proposal."""
        self.ensure_one()
        if self.state != 'done':
            raise UserError(_('Validate the receipt first: Sourevo asks for the number of a recorded purchase.'))
        self.action_sourevo_trade_send()
        line = self.sourevo_trade_line_ids.filtered(lambda l: l.direction == 'in' and l.sourevo_id)[:1]
        if not line:
            raise UserError(_('%s has no EUDR products.', self.name))
        data = SourevoTradeClient(self.company_id).request_reference(line.sourevo_id, {})
        self.sourevo_trade_asked_at = fields.Datetime.now()
        self.message_post(body=_('Sourevo asked %s for the EUDR reference number.', data.get('email') or self.partner_id.email))
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Sourevo EUDR Lite'), 'type': 'success',
                           'message': _('Request sent to %s. The answer arrives here as a proposal.', data.get('email') or '—')}}

    def _sourevo_trade_take_proposals(self, purchase):
        """Stores the numbers the supplier proposed in Sourevo for this receipt, once, with an activity."""
        self.ensure_one()
        Ref = self.env['sourevo.trade.reference'].sudo()
        new = Ref
        for r in purchase.get('references') or []:
            if r.get('state') != 'PROPOSED' or r.get('removed'):
                continue
            if self.sourevo_trade_reference_ids.filtered(lambda x: x.sourevo_reference_id == r.get('id')):
                continue
            new |= Ref.create({'picking_id': self.id, 'kind': r.get('kind') or 'DDS', 'state': 'proposed',
                               'reference_number': r.get('referenceNumber'), 'verification_number': r.get('verificationNumber'),
                               'sourevo_reference_id': r.get('id')})
        if new:
            user = self.user_id or self.env.ref('base.user_admin', raise_if_not_found=False) or self.env.user
            self.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                   summary=_('EUDR: the supplier proposed a reference number'),
                                   note=_('Accept or reject it in the EUDR tab: %s', reference_text(new)))
        return new
