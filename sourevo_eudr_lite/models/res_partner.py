import hashlib
import json

from odoo import _, fields, models
from odoo.exceptions import UserError

SUPPLIER_KINDS = [
    ('OPERATOR', 'Operator (imports or produces: gives DDS numbers)'),
    ('DOWNSTREAM_OPERATOR', 'Downstream operator'),
    ('TRADER', 'Trader'),
]


class ResPartner(models.Model):
    _inherit = 'res.partner'

    sourevo_trade_supplier_kind = fields.Selection(SUPPLIER_KINDS, 'EUDR supplier kind',
                                                   help='An operator (importer or producer in the EU) must give you the '
                                                        'reference number of its DDS (EUDR Art. 5.3.a).')
    sourevo_trade_consumer = fields.Boolean('Final consumer (EUDR)',
                                            help='Sales to this contact are recorded without its data: EUDR Art. 5.3.b '
                                                 'only asks for customers that are traders or downstream operators.')
    sourevo_trade_partner_id = fields.Char('Sourevo partner', readonly=True, copy=False)
    sourevo_trade_partner_hash = fields.Char(readonly=True, copy=False)
    sourevo_trade_is_supplier = fields.Boolean(readonly=True, copy=False)
    sourevo_trade_is_customer = fields.Boolean(readonly=True, copy=False)

    def _sourevo_trade_payload(self, supplier, customer):
        self.ensure_one()
        missing = [label for label, ok in ((_('postal address'), self.street or self.city),
                                            (_('email'), self.email), (_('country'), self.country_id)) if not ok]
        if missing:
            raise UserError(_('%(name)s needs %(missing)s for the EUDR register (Art. 5.3).',
                              name=self.display_name, missing=', '.join(missing)))
        if supplier and not self.sourevo_trade_supplier_kind:
            raise UserError(_('Set the EUDR supplier kind of %s (operator, downstream operator or trader).', self.display_name))
        address = ', '.join(p for p in (self.street, self.street2, ' '.join(filter(None, (self.zip, self.city))),
                                        self.state_id.name, self.country_id.name) if p)
        return {
            'isSupplier': supplier,
            'isCustomer': customer,
            'supplierKind': self.sourevo_trade_supplier_kind if supplier else None,
            'name': self.name,
            'tradeName': None,
            'postalAddress': address,
            'email': (self.email or '').strip(),
            'website': self.website or None,
            'countryCode': self.country_id.code,
            'taxId': self.vat or None,
            'externalRef': f'odoo:{self.env.cr.dbname}:partner:{self.id}',
        }

    def _sourevo_trade_sync(self, client, supplier=False, customer=False):
        """The Sourevo id of this contact: created once, corrected when its data or roles change."""
        self.ensure_one()
        partner = self.sudo()
        supplier = supplier or partner.sourevo_trade_is_supplier
        customer = customer or partner.sourevo_trade_is_customer
        payload = partner._sourevo_trade_payload(supplier, customer)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if partner.sourevo_trade_partner_id and digest == partner.sourevo_trade_partner_hash:
            return partner.sourevo_trade_partner_id
        if partner.sourevo_trade_partner_id:
            data = client.correct_partner(partner.sourevo_trade_partner_id, payload)
        else:
            data = client.create_partner(payload)
            if data.get('duplicate') and (not data.get('isSupplier') and supplier or not data.get('isCustomer') and customer
                                          or data.get('name') != payload['name']):
                data = client.correct_partner(data['id'], payload)
        partner.write({'sourevo_trade_partner_id': data['id'], 'sourevo_trade_partner_hash': digest,
                       'sourevo_trade_is_supplier': supplier, 'sourevo_trade_is_customer': customer})
        return data['id']
