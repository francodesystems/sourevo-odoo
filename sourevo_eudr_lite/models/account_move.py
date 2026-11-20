from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    sourevo_trade_reference_text = fields.Char('EUDR reference numbers', compute='_compute_sourevo_trade_reference_text')

    @api.depends('invoice_line_ids.sale_line_ids.move_ids.state')
    def _compute_sourevo_trade_reference_text(self):
        for move in self:
            pickings = move.invoice_line_ids.sale_line_ids.move_ids.filtered(
                lambda m: m.state == 'done' and m.picking_id.picking_type_code == 'outgoing').picking_id
            texts = [t for t in pickings.mapped('sourevo_trade_reference_text') if t]
            move.sourevo_trade_reference_text = ', '.join(dict.fromkeys(', '.join(texts).split(', '))) if texts else False
