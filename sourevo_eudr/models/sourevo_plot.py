from odoo import api, fields, models

from .sourevo_client import SourevoClient

PROPOSAL_STATUSES = [
    ('PENDING', 'Waiting for the supplier'),
    ('CONFIRMED', 'Confirmed'),
    ('CORRECTED', 'Corrected by the supplier'),
    ('REJECTED', 'Rejected'),
]
VERIFICATION_STATUSES = [
    ('DECLARED', 'Declared'),
    ('VERIFIED', 'Verified'),
    ('CORRECTION_REQUESTED', 'Correction requested'),
]
SATELLITE_VERDICTS = [
    ('NO_LOSS_DETECTED', 'No loss detected'),
    ('LOSS_DETECTED', 'Needs review'),
    ('NO_FOREST_2020', 'No forest in 2020'),
    ('INCONCLUSIVE', 'Inconclusive'),
    ('FAILED', 'Failed'),
]


class SourevoPlot(models.Model):
    """A production plot of a supplier, as Sourevo has it (GET /suppliers/{id}/plots)."""

    _name = 'sourevo.plot'
    _description = 'Sourevo production plot'
    _order = 'partner_id, name'

    name = fields.Char(required=True, readonly=True)
    sourevo_id = fields.Char('Sourevo ID', required=True, readonly=True, index=True)
    partner_id = fields.Many2one('res.partner', 'Supplier', required=True, ondelete='cascade', readonly=True, index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, readonly=True)
    country_code = fields.Char('Country', readonly=True)
    producer_name = fields.Char('Producer', readonly=True)
    area_ha = fields.Float('Area (ha)', digits=(16, 4), readonly=True)
    geometry_type = fields.Char('Geometry', readonly=True)
    source = fields.Selection([('SUPPLIER', 'Supplier'), ('IMPORTER', 'Us')], 'Uploaded by', readonly=True)
    proposal_status = fields.Selection(PROPOSAL_STATUSES, 'Proposal', readonly=True)
    rejection_reason = fields.Char('Rejection reason', readonly=True)
    verification_status = fields.Selection(VERIFICATION_STATUSES, 'Verification', readonly=True)
    satellite_verdict = fields.Selection(SATELLITE_VERDICTS, 'Satellite check', readonly=True)
    usable = fields.Boolean('Usable in a statement', compute='_compute_usable', store=True)

    _sql_constraints = [('sourevo_id_uniq', 'UNIQUE(company_id, sourevo_id)', 'This plot is already in Odoo.')]

    @api.depends('proposal_status', 'verification_status')
    def _compute_usable(self):
        for plot in self:
            # A proposal waiting for the supplier can go in a statement: Sourevo warns (PLOT_UPLOADED_BY_IMPORTER).
            plot.usable = plot.proposal_status != 'REJECTED' and plot.verification_status != 'CORRECTION_REQUESTED'

    @api.model
    def _sourevo_values(self, row):
        proposal = row.get('proposal') or {}
        verification = row.get('verification') or {}
        satellite = row.get('satellite') or {}
        return {
            'name': row.get('name') or row['id'],
            'country_code': row.get('country'),
            'producer_name': row.get('producerName'),
            'area_ha': row.get('areaHa') or 0.0,
            'geometry_type': (row.get('geometry') or {}).get('type'),
            'source': row.get('source'),
            'proposal_status': proposal.get('status') or False,
            'rejection_reason': proposal.get('rejectionReason'),
            'verification_status': verification.get('status') or False,
            'satellite_verdict': satellite.get('verdict') or False,
        }

    @api.model
    def _sourevo_upsert(self, partner, row):
        """Creates or updates the plot of ``partner`` from a Plot of the API; returns it."""
        company = partner.env.company
        plot = self.search([('company_id', '=', company.id), ('sourevo_id', '=', row['id'])], limit=1)
        vals = self._sourevo_values(row)
        if plot:
            plot.write(vals)
        else:
            plot = self.create(dict(vals, sourevo_id=row['id'], partner_id=partner.id, company_id=company.id))
        return plot

    def action_sourevo_verify(self):
        """Approves the plots for our organization (POST /plots/{id}/verify)."""
        client = SourevoClient(self.env.company)
        for plot in self:
            plot.write(self._sourevo_values(client.verify_plot(plot.sourevo_id)))
        return True
