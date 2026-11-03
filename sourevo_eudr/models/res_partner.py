from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .sourevo_client import SourevoClient

TRUST_LEVELS = [
    ('LEVEL_0_ANONYMOUS', 'Anonymous'),
    ('LEVEL_1_EMAIL_VERIFIED', 'Email verified'),
    ('LEVEL_2_TAX_DECLARED', 'Tax ID declared'),
    ('LEVEL_3_TAX_VALIDATED', 'Tax ID validated'),
]
TRUST_SIGNALS = [('RED', 'Red'), ('AMBER', 'Amber'), ('GREEN', 'Green')]
INVITATION_STATUSES = [
    ('PENDING', 'Pending'),
    ('ACCEPTED', 'Accepted'),
    ('REVOKED', 'Revoked'),
    ('EXPIRED', 'Expired'),
]


class ResPartner(models.Model):
    _inherit = 'res.partner'

    sourevo_supplier_id = fields.Char('Sourevo supplier', copy=False, readonly=True, index=True)
    sourevo_trust_level = fields.Selection(TRUST_LEVELS, 'Trust level', copy=False, readonly=True)
    sourevo_trust_signal = fields.Selection(TRUST_SIGNALS, 'Trust signal', copy=False, readonly=True)
    sourevo_claimed = fields.Boolean('Has a Sourevo account', copy=False, readonly=True)
    sourevo_invitation_status = fields.Selection(INVITATION_STATUSES, 'Portal invitation', copy=False, readonly=True)
    sourevo_invitation_url = fields.Char('Invitation link', copy=False, readonly=True)
    sourevo_plot_ids = fields.One2many('sourevo.plot', 'partner_id', 'EUDR plots')
    sourevo_plot_count = fields.Integer('Plots', compute='_compute_sourevo_plot_count')
    sourevo_plots_verified = fields.Integer('Verified plots', copy=False, readonly=True)
    sourevo_plots_pending = fields.Integer('Proposals waiting', copy=False, readonly=True)
    sourevo_plots_rejected = fields.Integer('Proposals rejected', copy=False, readonly=True)
    sourevo_plots_flagged = fields.Integer('Flagged by satellite', copy=False, readonly=True)
    sourevo_status_date = fields.Datetime('EUDR status updated', copy=False, readonly=True)

    @api.depends('sourevo_plot_ids')
    def _compute_sourevo_plot_count(self):
        for partner in self:
            partner.sourevo_plot_count = len(partner.sourevo_plot_ids)

    def _sourevo_external_ref(self):
        self.ensure_one()
        return f'odoo:res.partner:{self.id}'

    def _sourevo_payload(self):
        self.ensure_one()
        if not self.country_id:
            raise UserError(_('%s needs a country to be sent to Sourevo.', self.display_name))
        address = ', '.join(p for p in [self.street, self.street2, ' '.join(filter(None, [self.zip, self.city])),
                                        self.state_id.name, self.country_id.name] if p)
        payload = {'name': self.name, 'country': self.country_id.code, 'externalRef': self._sourevo_external_ref()}
        if self.is_company:
            payload['legalName'] = self.name[:300]
        if address:
            payload['postalAddress'] = address[:500]
        if self.email:
            payload['email'] = self.email
        if self.phone:
            payload['phone'] = self.phone
        if self.vat:
            payload['taxId'] = self.vat
        return payload

    def _sourevo_ensure_supplier(self):
        """The Sourevo id of the supplier, creating it first (externalRef makes the POST safe to repeat)."""
        self.ensure_one()
        partner = self.commercial_partner_id
        if not partner.sourevo_supplier_id:
            data = SourevoClient(self.env.company).create_supplier(partner._sourevo_payload())
            partner.sourevo_supplier_id = data['id']
            partner._sourevo_apply_supplier(data)
        return partner.sourevo_supplier_id

    def _sourevo_apply_supplier(self, data):
        vals = {}
        if data.get('trustLevel'):
            vals['sourevo_trust_level'] = data['trustLevel']
        if data.get('trustSignal'):
            vals['sourevo_trust_signal'] = data['trustSignal']
        if 'claimed' in data:
            vals['sourevo_claimed'] = bool(data['claimed'])
        if vals:
            self.write(vals)

    def action_sourevo_send(self):
        partners = self.mapped('commercial_partner_id')
        for partner in partners:
            partner._sourevo_ensure_supplier()
        if len(partners) == 1:
            partners.action_sourevo_refresh()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Sourevo'), 'type': 'success', 'sticky': False,
                           'message': _('%s supplier(s) in Sourevo.', len(partners))}}

    def action_sourevo_invite(self):
        self.ensure_one()
        partner = self.commercial_partner_id
        supplier_id = partner._sourevo_ensure_supplier()
        data = SourevoClient(self.env.company).invite_supplier(supplier_id)
        partner.write({'sourevo_invitation_status': 'PENDING', 'sourevo_invitation_url': data.get('url')})
        if data.get('emailStatus') == 'sent':
            message = _('Invitation emailed to %s.', data.get('emailedTo'))
        else:
            message = _('Invitation created. Send this link to the supplier: %s', data.get('url'))
        partner.message_post(body=message)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Sourevo'), 'type': 'success', 'sticky': True, 'message': message}}

    def action_sourevo_refresh(self):
        """Status (GET /suppliers/{id}/status) and plots (GET /suppliers/{id}/plots) of the supplier."""
        client = SourevoClient(self.env.company)
        Plot = self.env['sourevo.plot']
        for partner in self.mapped('commercial_partner_id').filtered('sourevo_supplier_id'):
            status = client.supplier_status(partner.sourevo_supplier_id)
            plots = status.get('plots') or {}
            invitation = status.get('invitation') or {}
            partner.write({
                'sourevo_trust_level': status.get('trustLevel') or False,
                'sourevo_trust_signal': status.get('trustSignal') or False,
                'sourevo_claimed': bool(status.get('claimed')),
                'sourevo_invitation_status': invitation.get('status') or False,
                'sourevo_plots_verified': plots.get('verified') or 0,
                'sourevo_plots_pending': plots.get('proposalsPending') or 0,
                'sourevo_plots_rejected': plots.get('proposalsRejected') or 0,
                'sourevo_plots_flagged': plots.get('satelliteFlagged') or 0,
                'sourevo_status_date': fields.Datetime.now(),
            })
            seen = Plot.browse()
            for row in client.supplier_plots(partner.sourevo_supplier_id):
                seen |= Plot._sourevo_upsert(partner, row)
            (partner.sourevo_plot_ids.filtered(lambda p: p.company_id == self.env.company) - seen).unlink()
        return True

    def action_sourevo_upload_plots(self):
        self.ensure_one()
        partner = self.commercial_partner_id
        partner._sourevo_ensure_supplier()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'sourevo.plot.upload', 'view_mode': 'form', 'target': 'new',
            'name': _('Upload plots'), 'context': {'default_partner_id': partner.id},
        }

    def action_sourevo_view_plots(self):
        self.ensure_one()
        partner = self.commercial_partner_id
        return {
            'type': 'ir.actions.act_window', 'res_model': 'sourevo.plot', 'view_mode': 'tree,form',
            'name': _('EUDR plots of %s', partner.display_name),
            'domain': [('partner_id', '=', partner.id)], 'context': {'default_partner_id': partner.id},
        }
