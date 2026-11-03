import base64
import json

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..models.sourevo_client import SourevoClient


class SourevoPlotUpload(models.TransientModel):
    """Uploads a GeoJSON file as plot proposals to the supplier (POST /suppliers/{id}/plots)."""

    _name = 'sourevo.plot.upload'
    _description = 'Upload EUDR plots to Sourevo'

    partner_id = fields.Many2one('res.partner', 'Supplier', required=True, readonly=True)
    file = fields.Binary('GeoJSON file', required=True)
    filename = fields.Char()
    country_id = fields.Many2one('res.country', 'Country of production',
                                 help='For the plots whose file does not say it (ProducerCountry).')
    producer_name = fields.Char('Producer', help='For the plots whose file does not say it (ProducerName). '
                                                 'Empty: the supplier.')

    def action_upload(self):
        self.ensure_one()
        # Odoo 20 gives the content (BinaryValue); 17 to 19, base64.
        raw = self.file.content if hasattr(self.file, 'content') else base64.b64decode(self.file)
        try:
            geojson = json.loads(raw)
        except (ValueError, TypeError) as e:
            raise UserError(_('The file is not GeoJSON: %s', e)) from e
        partner = self.partner_id.commercial_partner_id
        payload = {'geojson': geojson}
        country = self.country_id or partner.country_id
        if country:
            payload['country'] = country.code
        if self.producer_name:
            payload['producerName'] = self.producer_name
        data = SourevoClient(self.env.company).upload_plots(partner._sourevo_ensure_supplier(), payload)
        Plot = self.env['sourevo.plot']
        for row in data.get('data') or []:
            Plot._sourevo_upsert(partner, row)
        created = len(data.get('data') or [])
        skipped = data.get('skippedDuplicates') or 0
        message = _('%(created)s plot(s) sent to %(supplier)s for confirmation in their portal; %(skipped)s repeated.',
                    created=created, supplier=partner.display_name, skipped=skipped)
        partner.message_post(body=message)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _('Sourevo'), 'type': 'success', 'sticky': False, 'message': message,
                           'next': {'type': 'ir.actions.act_window_close'}}}
