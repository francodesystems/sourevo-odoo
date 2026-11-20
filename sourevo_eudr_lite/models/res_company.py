from odoo import fields, models

# The languages of the Sourevo web app (sourevo.com/<lang>/...).
SOUREVO_LANGS = ('en', 'es', 'fr', 'pt', 'de', 'it', 'nl', 'pl')


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Own prefix: the importer module (sourevo_eudr) can be installed in the same database.
    sourevo_trade_url = fields.Char('Sourevo API URL (Lite)', default='https://sourevo.com/api/v1')
    sourevo_trade_api_key = fields.Char('Sourevo API key (Lite)', groups='base.group_system', copy=False,
                                        help='Created in Sourevo, menu API. It starts with svk_.')
    sourevo_trade_organization = fields.Char('Sourevo organization (Lite)', readonly=True, copy=False)
    sourevo_trade_role = fields.Selection([('TRADER', 'Trader'), ('DOWNSTREAM_OPERATOR', 'Downstream operator')],
                                          'EUDR role in Sourevo', readonly=True, copy=False)
    sourevo_trade_webhook_id = fields.Char('Sourevo webhook (Lite)', readonly=True, copy=False)
    sourevo_trade_webhook_url = fields.Char('Lite notifications sent to', readonly=True, copy=False)
    sourevo_trade_webhook_secret = fields.Char('Lite webhook secret', groups='base.group_system', copy=False)
    sourevo_trade_last_sync = fields.Datetime('Last update from Sourevo (Lite)', readonly=True, copy=False)

    def _sourevo_trade_web_url(self, path):
        """A page of the Sourevo web app in the user's language (path without the language: /trade/register)."""
        self.ensure_one()
        base = (self.sourevo_trade_url or 'https://sourevo.com/api/v1').split('/api/')[0].rstrip('/')
        lang = (self.env.lang or 'en')[:2]
        return f'{base}/{lang if lang in SOUREVO_LANGS else "en"}{path}'
