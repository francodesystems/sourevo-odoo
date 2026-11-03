import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class SourevoWebhookEvent(models.Model):
    """The webhook events already handled: a retry repeats the same event id."""

    _name = 'sourevo.webhook.event'
    _description = 'Sourevo webhook event'
    _order = 'id desc'

    name = fields.Char('Event ID', required=True, readonly=True)
    event_type = fields.Char('Type', readonly=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='cascade')

    _sql_constraints = [('name_uniq', 'UNIQUE(company_id, name)', 'This event was already received.')]

    @api.model
    def _sourevo_handle(self, company, event):
        """Applies a webhook event ({id, type, createdAt, data}); returns False if it was already handled."""
        event_id = event.get('id')
        if event_id:
            if self.search_count([('company_id', '=', company.id), ('name', '=', event_id)]):
                return False
            self.create({'name': event_id, 'event_type': event.get('type'), 'company_id': company.id})
        handler = {
            'dds.submitted': self._on_dds,
            'dds.status_changed': self._on_dds,
            'plot.proposal_answered': self._on_proposal_answered,
            'plot.satellite_flagged': self._on_satellite_flagged,
            'supplier.claimed': self._on_supplier_claimed,
            'plan.quota_80': self._on_quota,
            'plan.quota_100': self._on_quota,
        }.get(event.get('type'))
        if handler:
            handler(company, event.get('data') or {}, event.get('type'))
        return True

    def _on_dds(self, company, data, _type):
        dds = data.get('dds') or {}
        if not dds.get('id'):
            return
        lines = self.env['sourevo.dds'].search([('company_id', '=', company.id), ('sourevo_dds_id', '=', dds['id'])])
        lines._sourevo_apply(dds)

    def _partner_of_plot(self, company, plot):
        if not plot.get('supplierId'):
            return self.env['res.partner']
        return self.env['res.partner'].search([('sourevo_supplier_id', '=', plot['supplierId'])], limit=1)

    def _on_proposal_answered(self, company, data, _type):
        plot = data.get('plot') or {}
        partner = self._partner_of_plot(company, plot)
        if not partner or not plot.get('id'):
            return
        record = self.env['sourevo.plot'].with_company(company)._sourevo_upsert(partner, plot)
        answer = data.get('answer')
        if answer == 'REJECTED':
            partner.activity_schedule(
                'mail.mail_activity_data_todo', user_id=partner.user_id.id or self.env.ref('base.user_admin').id,
                summary=_('EUDR plot rejected: %s', record.name),
                note=_('%(supplier)s rejected the plot %(plot)s. Reason: %(reason)s',
                       supplier=partner.display_name, plot=record.name, reason=data.get('reason') or '—'))
        elif answer == 'CORRECTED':
            partner.message_post(body=_('%(supplier)s corrected the plot %(plot)s.', supplier=partner.display_name, plot=record.name))
        else:
            partner.message_post(body=_('%(supplier)s confirmed the plot %(plot)s.', supplier=partner.display_name, plot=record.name))

    def _on_satellite_flagged(self, company, data, _type):
        plot = data.get('plot') or {}
        partner = self._partner_of_plot(company, plot)
        if not partner or not plot.get('id'):
            return
        record = self.env['sourevo.plot'].with_company(company)._sourevo_upsert(partner, plot)
        loss = (data.get('check') or {}).get('lossAfterCutoffHa')
        note = _('The satellite check found tree cover loss after 2020 on the plot %(plot)s of %(supplier)s '
                 '(%(loss)s ha). It needs a human review in Sourevo: it does not mean it was deforested.',
                 plot=record.name, supplier=partner.display_name, loss=loss if loss is not None else '?')
        user = partner.user_id.id or self.env.ref('base.user_admin').id
        partner.activity_schedule('mail.mail_activity_data_todo', user_id=user,
                                  summary=_('EUDR plot to review: %s', record.name), note=note)
        drafts = self.env['sourevo.dds'].search([('company_id', '=', company.id), ('status', 'in', ('new', 'DRAFT')),
                                                 ('plot_ids', 'in', record.ids)])
        for picking in drafts.mapped('picking_id'):
            picking.activity_schedule('mail.mail_activity_data_todo', user_id=picking.user_id.id or user,
                                      summary=_('EUDR plot to review: %s', record.name), note=note)

    def _on_supplier_claimed(self, company, data, _type):
        supplier = data.get('supplier') or {}
        partner = self.env['res.partner'].search([('sourevo_supplier_id', '=', supplier.get('id'))], limit=1) \
            if supplier.get('id') else self.env['res.partner']
        if partner:
            partner._sourevo_apply_supplier(supplier)
            partner.write({'sourevo_claimed': True, 'sourevo_invitation_status': 'ACCEPTED'})
            partner.message_post(body=_('%s now has its own Sourevo account.', partner.display_name))

    def _on_quota(self, company, data, event_type):
        plan = data.get('plan') or {}
        level = data.get('level') or (100 if event_type == 'plan.quota_100' else 80)
        included = plan.get('statementsIncluded')
        company.partner_id.message_post(body=_(
            'Sourevo: %(level)s%% of the statements included in your plan are used (%(included)s in the period %(period)s).',
            level=level, included=included if included is not None else '—', period=data.get('period') or '—'))
        _logger.info('Sourevo quota %s%% for %s', level, company.name)
