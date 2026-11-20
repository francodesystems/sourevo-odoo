from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.modules import module as odoo_module

from .trade_client import SourevoTradeClient, SourevoTradeError

WEBHOOK_EVENTS = ['trade.reference_proposed']


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sourevo_trade_url = fields.Char(related='company_id.sourevo_trade_url', readonly=False)
    sourevo_trade_api_key = fields.Char(related='company_id.sourevo_trade_api_key', readonly=False, groups='base.group_system')
    sourevo_trade_organization = fields.Char(related='company_id.sourevo_trade_organization')
    sourevo_trade_role = fields.Selection(related='company_id.sourevo_trade_role')
    sourevo_trade_webhook_url = fields.Char(related='company_id.sourevo_trade_webhook_url')
    sourevo_trade_last_sync = fields.Datetime(related='company_id.sourevo_trade_last_sync')

    def _sourevo_trade_notify(self, message, kind='success'):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Sourevo EUDR Lite'), 'message': message, 'type': kind, 'sticky': kind != 'success'}}

    def action_sourevo_trade_test(self):
        """GET /me: the organization and whether its trade records are on."""
        self.ensure_one()
        self.execute()
        company = self.company_id
        me = SourevoTradeClient(company).me()
        trade = me.get('trade') or {}
        name = (me.get('organization') or {}).get('name')
        company.sudo().write({'sourevo_trade_organization': name, 'sourevo_trade_role': trade.get('role') or False})
        if not trade:
            return self._sourevo_trade_notify(_(
                'Connected to %(org)s, but its trade records are off. Turn them on in Sourevo: Trade > Settings.',
                org=name or '—'), 'warning')
        role = dict(self.env['res.company']._fields['sourevo_trade_role']._description_selection(self.env)).get(trade.get('role'))
        return self._sourevo_trade_notify(_('Connected to %(org)s as %(role)s.', org=name or '—', role=role or '—'))

    def action_sourevo_trade_connect_webhook(self):
        """Registers this database in Sourevo (POST /webhooks) and keeps the whsec_ secret."""
        self.ensure_one()
        self.execute()
        company = self.company_id
        base = (company.get_base_url() or '').rstrip('/')
        if not base:
            raise UserError(_('This database has no public address (system parameter web.base.url).'))
        url = f'{base}/sourevo/trade-webhook/{company.id}?db={self.env.cr.dbname}'
        client = SourevoTradeClient(company)
        if company.sourevo_trade_webhook_id:
            try:
                client.delete_webhook(company.sourevo_trade_webhook_id)
            except SourevoTradeError:
                pass
        data = client.create_webhook(url, WEBHOOK_EVENTS)
        company.sudo().write({'sourevo_trade_webhook_id': data.get('id'), 'sourevo_trade_webhook_url': url,
                              'sourevo_trade_webhook_secret': data.get('secret')})
        # The test ping arrives in another request, which must already see the stored secret.
        if not odoo_module.current_test:
            self.env.cr.commit()
        try:
            client.test_webhook(data.get('id'))
        except SourevoTradeError as e:
            return self._sourevo_trade_notify(_(
                'Registered, but the test notification failed (%(error)s). Sourevo must reach %(url)s from the '
                'internet; if this database is not public, the scheduled action checks every 15 minutes.',
                error=str(e), url=url), 'warning')
        return self._sourevo_trade_notify(_('Notifications connected: Sourevo sends a test ping now.'))

    def action_sourevo_trade_disconnect_webhook(self):
        self.ensure_one()
        company = self.company_id
        if company.sourevo_trade_webhook_id:
            try:
                SourevoTradeClient(company).delete_webhook(company.sourevo_trade_webhook_id)
            except SourevoTradeError as e:
                if e.status != 404:
                    raise
        company.sudo().write({'sourevo_trade_webhook_id': False, 'sourevo_trade_webhook_url': False,
                              'sourevo_trade_webhook_secret': False})

    def action_sourevo_trade_update_now(self):
        self.ensure_one()
        self.env['sourevo.trade.line']._cron_sourevo_trade(companies=self.company_id)
        return self._sourevo_trade_notify(_('EUDR records updated with Sourevo.'))

    def action_sourevo_trade_open_register(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'target': 'new',
                'url': self.company_id._sourevo_trade_web_url('/trade/register')}
