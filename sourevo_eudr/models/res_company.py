from odoo import fields, models

OPERATOR_ROLES = [
    ('OPERATOR', 'Operator'),
    ('TRADER', 'Trader'),
    ('AUTHORISED_REPRESENTATIVE', 'Authorised representative'),
]
ACTIVITY_TYPES = [
    ('IMPORT', 'Import'),
    ('EXPORT', 'Export'),
    ('DOMESTIC', 'Domestic'),
    ('TRADE', 'Trade'),
]
REPRESENTED_ROLES = [
    ('OPERATOR', 'Operator'),
    ('TRADER', 'Trader'),
]


class ResCompany(models.Model):
    _inherit = 'res.company'

    sourevo_url = fields.Char('Sourevo API URL', default='https://sourevo.com/api/v1')
    sourevo_api_key = fields.Char('Sourevo API key', groups='base.group_system', copy=False,
                                  help='Created in Sourevo, menu API. It starts with svk_.')
    sourevo_mode = fields.Selection([('live', 'Live'), ('simulated', 'Simulated (trial)')], 'Sourevo mode',
                                    readonly=True, copy=False)
    sourevo_organization = fields.Char('Sourevo organization', readonly=True, copy=False)
    sourevo_operator_id = fields.Many2one('sourevo.operator', 'Default TRACES operator', copy=False,
                                          domain="[('company_id', '=', id)]")
    sourevo_operator_role = fields.Selection(OPERATOR_ROLES, 'Default operator role', default='OPERATOR')
    sourevo_represented_role = fields.Selection(REPRESENTED_ROLES, 'Default represented role')
    sourevo_activity_type = fields.Selection(ACTIVITY_TYPES, 'Default activity', default='IMPORT')
    sourevo_webhook_id = fields.Char('Sourevo webhook', readonly=True, copy=False)
    sourevo_webhook_url = fields.Char('Notifications sent to', readonly=True, copy=False)
    sourevo_webhook_secret = fields.Char('Webhook secret', groups='base.group_system', copy=False)
    sourevo_last_sync = fields.Datetime('Last update from Sourevo', readonly=True, copy=False)
