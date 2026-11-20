from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .trade_client import SourevoTradeClient

KINDS = [('DDS', 'Due diligence statement'), ('SIMPLIFIED_DECLARATION', 'Simplified declaration')]


class SourevoTradeReference(models.Model):
    """A reference number of a receipt (EUDR Art. 5.3.a): typed in Odoo or proposed by the supplier through Sourevo."""

    _name = 'sourevo.trade.reference'
    _description = 'EUDR reference number of a receipt'
    _order = 'id'

    picking_id = fields.Many2one('stock.picking', 'Receipt', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='picking_id.company_id', store=True)
    kind = fields.Selection(KINDS, 'Kind', required=True, default='DDS')
    reference_number = fields.Char('Reference number', required=True)
    verification_number = fields.Char('Verification number', required=True)
    state = fields.Selection([('accepted', 'Accepted'), ('proposed', 'Proposed by the supplier'), ('rejected', 'Rejected')],
                             'Status', required=True, default='accepted', readonly=True)
    sourevo_reference_id = fields.Char('Sourevo reference', readonly=True, copy=False)
    reject_reason = fields.Char('Reason', readonly=True)

    @api.constrains('reference_number', 'verification_number')
    def _check_numbers(self):
        for ref in self:
            if len(ref.reference_number.strip()) > 50 or not 5 <= len(ref.verification_number.strip()) <= 35:
                raise UserError(_('The reference number has up to 50 characters and the verification number 5 to 35.'))

    def _payload(self):
        return {'kind': self.kind, 'referenceNumber': self.reference_number.strip(),
                'verificationNumber': self.verification_number.strip()}

    def action_accept(self):
        for ref in self.filtered(lambda r: r.state == 'proposed'):
            company = ref.picking_id.company_id
            SourevoTradeClient(company).decide(ref.sourevo_reference_id, True)
            ref.state = 'accepted'
            # The other EUDR lines of the receipt get the number too.
            ref.picking_id.sourevo_trade_line_ids._sourevo_trade_send(silent=True)
            ref.picking_id.activity_feedback(['mail.mail_activity_data_todo'], feedback=_('EUDR number accepted.'))
        return True

    def action_reject(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'sourevo.trade.reject', 'view_mode': 'form', 'target': 'new',
                'name': _('Reject the number'), 'context': {'default_reference_id': self.id}}

    def _reject(self, reason):
        self.ensure_one()
        if self.state != 'proposed':
            raise UserError(_('Only a proposed number can be rejected.'))
        SourevoTradeClient(self.picking_id.company_id).decide(self.sourevo_reference_id, False, reason)
        self.write({'state': 'rejected', 'reject_reason': reason})
