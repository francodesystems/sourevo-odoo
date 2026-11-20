import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

UNITS = [('kg', 'kg'), ('t', 'tonnes'), ('m3', 'm³'), ('l', 'litres'), ('units', 'units'), ('head', 'head')]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    sourevo_trade_eudr = fields.Boolean('EUDR product (trade records)',
                                        help='Coffee, cocoa, wood, soy, palm oil, rubber, cattle or a product of Annex I '
                                             'of the EUDR: its receipts and deliveries go to the EUDR register.')
    sourevo_trade_cn_code = fields.Char('CN or HS code', help='4, 6 or 8 digits, e.g. 0901 11 00.')
    sourevo_trade_unit = fields.Selection(UNITS, 'Unit in the EUDR register', default='kg',
                                          help='The unit of the quantities sent to Sourevo; they are converted to the '
                                               'unit of measure of the product first, so both must match.')

    @api.constrains('sourevo_trade_eudr', 'sourevo_trade_cn_code')
    def _check_sourevo_trade_cn_code(self):
        for template in self:
            if template.sourevo_trade_eudr and not normalize_cn(template.sourevo_trade_cn_code):
                raise ValidationError(_('The CN or HS code of an EUDR product has 4, 6 or 8 digits.'))


def normalize_cn(raw):
    digits = re.sub(r'\D', '', raw or '')
    return digits if re.fullmatch(r'\d{4}(\d{2}){0,2}', digits) else None
