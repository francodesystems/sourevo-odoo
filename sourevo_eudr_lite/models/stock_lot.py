from odoo import api, fields, models

from .stock_picking import reference_text


class StockLot(models.Model):
    _inherit = 'stock.lot'

    sourevo_trade_reference_text = fields.Char('EUDR reference numbers', compute='_compute_sourevo_trade_reference_text',
                                               help='The numbers of the receipts that brought this lot in.')

    @api.depends_context('company')
    def _compute_sourevo_trade_reference_text(self):
        for lot in self:
            lines = self.env['stock.move.line'].search([('lot_id', '=', lot.id), ('state', '=', 'done'),
                                                        ('picking_code', '=', 'incoming')])
            refs = lines.picking_id.sourevo_trade_reference_ids.filtered(lambda r: r.state == 'accepted')
            lot.sourevo_trade_reference_text = reference_text(refs)
