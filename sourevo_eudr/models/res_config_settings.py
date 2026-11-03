from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.modules import module as odoo_module

from .sourevo_client import SourevoClient, SourevoError

WEBHOOK_EVENTS = ['dds.submitted', 'dds.status_changed', 'plot.proposal_answered', 'plot.satellite_flagged',
                  'supplier.claimed', 'plan.quota_80', 'plan.quota_100']


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sourevo_url = fields.Char(related='company_id.sourevo_url', readonly=False)
    sourevo_api_key = fields.Char(related='company_id.sourevo_api_key', readonly=False, groups='base.group_system')
    sourevo_mode = fields.Selection(related='company_id.sourevo_mode')
    sourevo_organization = fields.Char(related='company_id.sourevo_organization')
    sourevo_operator_id = fields.Many2one(related='company_id.sourevo_operator_id', readonly=False)
    sourevo_operator_role = fields.Selection(related='company_id.sourevo_operator_role', readonly=False)
    sourevo_represented_role = fields.Selection(related='company_id.sourevo_represented_role', readonly=False)
    sourevo_activity_type = fields.Selection(related='company_id.sourevo_activity_type', readonly=False)
    sourevo_webhook_url = fields.Char(related='company_id.sourevo_webhook_url')
    sourevo_last_sync = fields.Datetime(related='company_id.sourevo_last_sync')

    def _sourevo_notify(self, message, kind='success'):
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Sourevo'), 'message': message, 'type': kind, 'sticky': False}}

    def action_sourevo_test(self):
        """GET /me: shows the organization, plan, mode and role, and loads the TRACES operators."""
        self.ensure_one()
        self.execute()
        company = self.company_id
        me = SourevoClient(company).me()
        company.sudo().write({'sourevo_mode': me.get('mode'),
                              'sourevo_organization': (me.get('organization') or {}).get('name')})
        operators = self.env['sourevo.operator']._sourevo_load(company)
        if not company.sourevo_operator_id and len(operators) == 1:
            company.sourevo_operator_id = operators
        plan = me.get('plan') or {}
        plan_name = plan.get('name') or plan.get('productCode') or plan.get('kind') or '—'
        mode = _('live') if me.get('mode') == 'live' else _('simulated (SIM references)')
        return self._sourevo_notify(_(
            'Connected to %(org)s. Plan: %(plan)s. Mode: %(mode)s. Role: %(role)s. TRACES operators: %(count)s.',
            org=(me.get('organization') or {}).get('name') or '—', plan=plan_name, mode=mode,
            role=me.get('role') or '—', count=len(operators)))

    def action_sourevo_load_operators(self):
        self.ensure_one()
        self.execute()
        operators = self.env['sourevo.operator']._sourevo_load(self.company_id)
        return self._sourevo_notify(_('%s TRACES operators loaded.', len(operators)))

    def action_sourevo_connect_webhook(self):
        """Registers this database in Sourevo (POST /webhooks) and keeps the whsec_ secret."""
        self.ensure_one()
        self.execute()
        company = self.company_id
        base = (company.get_base_url() or '').rstrip('/')
        if not base:
            raise UserError(_('This database has no public address (system parameter web.base.url).'))
        # With the database: on a server with several, a call from outside would not know which one.
        url = f'{base}/sourevo/webhook/{company.id}?db={self.env.cr.dbname}'
        client = SourevoClient(company)
        if company.sourevo_webhook_id:
            try:
                client.delete_webhook(company.sourevo_webhook_id)
            except SourevoError:
                pass
        data = client.create_webhook(url, WEBHOOK_EVENTS)
        company.sudo().write({'sourevo_webhook_id': data.get('id'), 'sourevo_webhook_url': url,
                              'sourevo_webhook_secret': data.get('secret')})
        # The test ping arrives in another request, which must already see the stored secret.
        if not odoo_module.current_test:
            self.env.cr.commit()
        try:
            client.test_webhook(data.get('id'))
        except SourevoError as e:
            return self._sourevo_notify(_(
                'Registered, but the test notification failed (%(error)s). Sourevo must reach %(url)s from the '
                'internet; if this database is not public, the scheduled action updates the statements every 15 minutes.',
                error=str(e), url=url), 'warning')
        return self._sourevo_notify(_('Notifications connected: Sourevo sends a test ping now.'))

    def action_sourevo_disconnect_webhook(self):
        self.ensure_one()
        company = self.company_id
        if company.sourevo_webhook_id:
            try:
                SourevoClient(company).delete_webhook(company.sourevo_webhook_id)
            except SourevoError as e:
                if e.status != 404:
                    raise
        company.sudo().write({'sourevo_webhook_id': False, 'sourevo_webhook_url': False, 'sourevo_webhook_secret': False})

    def action_sourevo_update_now(self):
        self.ensure_one()
        self.env['sourevo.dds']._cron_sourevo_update(companies=self.company_id)
        return self._sourevo_notify(_('Statements updated from Sourevo.'))
