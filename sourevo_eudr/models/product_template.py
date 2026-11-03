import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .sourevo_client import SourevoClient

# CN chapters where Sourevo (and TRACES) need the scientific and common name: wood, pulp and paper.
SCIENTIFIC_NAME_CHAPTERS = ('44', '47', '48')


def clean_cn_code(code):
    return re.sub(r'[\s.]', '', code or '')


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    eudr_relevant = fields.Boolean('EUDR', help='Subject to the EU Deforestation Regulation (EU) 2023/1115: '
                                                'its receipts need a due diligence statement in TRACES.')
    eudr_cn_code = fields.Char('CN code', size=10, help='Combined Nomenclature code, 8 digits (e.g. 09011100).')
    eudr_scientific_name = fields.Char('Scientific name', help='Required for wood (chapter 44), pulp and paper (47 and 48).')
    eudr_common_name = fields.Char('Common name')
    eudr_supplementary_unit = fields.Char(
        'Supplementary unit', size=10,
        help='Only for CN codes with a supplementary unit (e.g. p/st for pieces): the receipt sends the quantity in it.')
    sourevo_product_id = fields.Char('Sourevo product', copy=False, readonly=True)

    @api.constrains('eudr_cn_code')
    def _check_eudr_cn_code(self):
        for template in self.filtered('eudr_cn_code'):
            if not re.fullmatch(r'\d{8}', clean_cn_code(template.eudr_cn_code)):
                raise ValidationError(_('The CN code of %s must have 8 digits.', template.display_name))

    def write(self, vals):
        # A different CN code or name is a different product in Sourevo (products cannot be changed there).
        if {'eudr_cn_code', 'eudr_scientific_name', 'eudr_common_name'} & set(vals) and 'sourevo_product_id' not in vals:
            vals = dict(vals, sourevo_product_id=False)
        return super().write(vals)

    def _sourevo_needs_scientific_name(self):
        self.ensure_one()
        return clean_cn_code(self.eudr_cn_code)[:2] in SCIENTIFIC_NAME_CHAPTERS

    def _sourevo_payload(self):
        self.ensure_one()
        cn = clean_cn_code(self.eudr_cn_code)
        if not cn:
            raise UserError(_('%s needs its CN code (Inventory tab, EUDR) to be sent to Sourevo.', self.display_name))
        if self._sourevo_needs_scientific_name() and not (self.eudr_scientific_name and self.eudr_common_name):
            raise UserError(_('%s is wood, pulp or paper: it needs the scientific and the common name.', self.display_name))
        payload = {
            'description': (self.name or '')[:150],
            'cnCode': cn,
            # The CN code goes in the reference: a product changed in Odoo is a new one in Sourevo.
            'externalRef': f'odoo:product.template:{self.id}:{cn}',
        }
        if self.eudr_scientific_name:
            payload['scientificName'] = self.eudr_scientific_name
        if self.eudr_common_name:
            payload['commonName'] = self.eudr_common_name
        return payload

    def _sourevo_ensure_product(self):
        self.ensure_one()
        if not self.sourevo_product_id:
            data = SourevoClient(self.env.company).create_product(self._sourevo_payload())
            self.sourevo_product_id = data['id']
        return self.sourevo_product_id

    def action_sourevo_send(self):
        for template in self:
            template._sourevo_ensure_product()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Sourevo'), 'type': 'success', 'sticky': False,
                           'message': _('%s product(s) in Sourevo.', len(self))}}
