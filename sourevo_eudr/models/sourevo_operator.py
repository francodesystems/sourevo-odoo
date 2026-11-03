from odoo import api, fields, models

from .sourevo_client import SourevoClient


class SourevoOperator(models.Model):
    """A company that submits to TRACES in Sourevo (GET /operators)."""

    _name = 'sourevo.operator'
    _description = 'Sourevo TRACES operator'
    _order = 'name'

    name = fields.Char('Legal name', required=True)
    sourevo_id = fields.Char('Sourevo ID', required=True, readonly=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, ondelete='cascade')
    country_code = fields.Char('Country')
    eori_number = fields.Char('EORI')
    has_credentials = fields.Boolean('TRACES credentials')
    active = fields.Boolean(default=True)

    _sourevo_id_uniq = models.Constraint('UNIQUE(company_id, sourevo_id)', 'This operator is already loaded.')

    @api.depends('name', 'country_code', 'has_credentials')
    def _compute_display_name(self):
        for op in self:
            name = op.name or ''
            if op.country_code:
                name = f'{name} ({op.country_code})'
            op.display_name = name

    @api.model
    def _sourevo_load(self, company):
        """Brings the operators of the Sourevo account of ``company``; the missing ones are archived."""
        rows = SourevoClient(company).operators()
        existing = self.with_context(active_test=False).search([('company_id', '=', company.id)])
        by_id = {op.sourevo_id: op for op in existing}
        seen = self.browse()
        for row in rows:
            vals = {'name': row.get('legalName') or row['id'], 'country_code': row.get('country'),
                    'eori_number': row.get('eoriNumber'), 'has_credentials': bool(row.get('hasCredentials')), 'active': True}
            op = by_id.get(row['id'])
            if op:
                op.write(vals)
            else:
                op = self.create(dict(vals, sourevo_id=row['id'], company_id=company.id))
            seen |= op
        (existing - seen).write({'active': False})
        return seen
