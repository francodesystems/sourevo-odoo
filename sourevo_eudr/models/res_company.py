from odoo import fields, models

# TRACES V4 (Regulation (EU) 2025/2650): only the operator or its authorised representative submits a
# statement; traders no longer do, so the module does not offer that role.
OPERATOR_ROLES = [
    ('OPERATOR', 'Operator'),
    ('AUTHORISED_REPRESENTATIVE', 'Authorised representative of an operator'),
]
# The languages of the Sourevo web app (sourevo.com/<lang>/...).
SOUREVO_LANGS = ('en', 'es', 'fr', 'pt', 'de', 'it', 'nl', 'pl')

ACTIVITY_TYPES = [
    ('IMPORT', 'Import'),
    ('EXPORT', 'Export'),
    ('DOMESTIC', 'Domestic'),
]


class ResCompany(models.Model):
    _inherit = 'res.company'

    sourevo_url = fields.Char('Sourevo API URL', default='https://sourevo.com/api/v1')
    sourevo_api_key = fields.Char('Sourevo API key', groups='base.group_system', copy=False,
                                  help='Created in Sourevo, menu API. It starts with svk_.')
    sourevo_mode = fields.Selection([('live', 'Live'), ('test', 'Test (TRACES acceptance, trial)'),
                                     ('simulated', 'Simulated (trial)')], 'Sourevo mode',
                                    readonly=True, copy=False)
    sourevo_organization = fields.Char('Sourevo organization', readonly=True, copy=False)
    sourevo_operator_id = fields.Many2one('sourevo.operator', 'Default company in TRACES', copy=False,
                                          domain="[('company_id', '=', id)]")
    sourevo_operator_role = fields.Selection(OPERATOR_ROLES, 'Default operator role', default='OPERATOR')
    sourevo_activity_type = fields.Selection(ACTIVITY_TYPES, 'Default activity', default='IMPORT')
    sourevo_webhook_id = fields.Char('Sourevo webhook', readonly=True, copy=False)
    sourevo_webhook_url = fields.Char('Notifications sent to', readonly=True, copy=False)
    sourevo_webhook_secret = fields.Char('Webhook secret', groups='base.group_system', copy=False)
    sourevo_last_sync = fields.Datetime('Last update from Sourevo', readonly=True, copy=False)

    def _sourevo_web_url(self, path):
        """A page of the Sourevo web app, in the language of the user (path without the language: /dds/operators)."""
        self.ensure_one()
        base = (self.sourevo_url or 'https://sourevo.com/api/v1').split('/api/')[0].rstrip('/')
        lang = (self.env.lang or 'en')[:2]
        return f'{base}/{lang if lang in SOUREVO_LANGS else "en"}{path}'
