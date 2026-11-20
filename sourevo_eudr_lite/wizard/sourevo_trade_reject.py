from odoo import fields, models


class SourevoTradeReject(models.TransientModel):
    _name = 'sourevo.trade.reject'
    _description = 'Reject a proposed EUDR number'

    reference_id = fields.Many2one('sourevo.trade.reference', required=True)
    reason = fields.Char('Why', required=True, help='Kept in your register; the supplier does not see it.')

    def action_confirm(self):
        self.ensure_one()
        self.reference_id._reject(self.reason.strip())
        return {'type': 'ir.actions.act_window_close'}
