from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    sourevo_dds_ids = fields.One2many('sourevo.dds', 'picking_id', 'EUDR statements')
    sourevo_eudr_visible = fields.Boolean(compute='_compute_sourevo_eudr')
    sourevo_eudr_pending = fields.Boolean('EUDR products without a statement', compute='_compute_sourevo_eudr')
    sourevo_state = fields.Selection([
        ('none', 'No statement'),
        ('draft', 'To submit'),
        ('submitted', 'Waiting for TRACES'),
        ('done', 'In TRACES'),
        ('problem', 'Rejected or withdrawn'),
    ], 'EUDR', compute='_compute_sourevo_state')
    sourevo_references = fields.Char('TRACES reference', compute='_compute_sourevo_state',
                                     help='Reference and verification numbers of the due diligence statements, for customs.')
    sourevo_simulated = fields.Boolean(compute='_compute_sourevo_state')

    @api.depends('picking_type_code', 'move_ids.product_id', 'sourevo_dds_ids.product_id')
    def _compute_sourevo_eudr(self):
        for picking in self:
            products = picking.move_ids.filtered(lambda m: m.state != 'cancel').mapped('product_id').filtered('eudr_relevant')
            picking.sourevo_eudr_visible = picking.picking_type_code == 'incoming' and bool(products)
            picking.sourevo_eudr_pending = picking.sourevo_eudr_visible and bool(products - picking.sourevo_dds_ids.mapped('product_id'))

    @api.depends('sourevo_dds_ids.status', 'sourevo_dds_ids.reference_number', 'sourevo_dds_ids.verification_number')
    def _compute_sourevo_state(self):
        for picking in self:
            lines = picking.sourevo_dds_ids
            statuses = set(lines.mapped('status'))
            if not lines:
                state = 'none'
            elif statuses & {'REJECTED', 'CANCELLED', 'WITHDRAWN'}:
                state = 'problem'
            elif statuses & {'new', 'DRAFT'}:
                state = 'draft'
            elif all(line.reference_number for line in lines):
                state = 'done'
            else:
                state = 'submitted'
            picking.sourevo_state = state
            picking.sourevo_references = ', '.join(
                f'{line.reference_number} / {line.verification_number}' if line.verification_number else line.reference_number
                for line in lines if line.reference_number) or False
            picking.sourevo_simulated = any(lines.mapped('simulated'))

    def action_sourevo_prepare(self):
        """One statement per EUDR product, with the supplier's plots; nothing is sent to TRACES yet."""
        for picking in self:
            if not picking.sourevo_eudr_visible:
                raise UserError(_('%s is not a receipt of EUDR products.', picking.name))
            if not self.env['sourevo.dds']._sourevo_prepare(picking) and not picking.sourevo_dds_ids:
                raise UserError(_('%s has no EUDR products to declare.', picking.name))
        return True

    def action_sourevo_submit(self):
        """Creates the drafts in Sourevo, checks them and opens the confirmation with the warnings."""
        self.ensure_one()
        if self.sourevo_eudr_pending:
            self.action_sourevo_prepare()
        lines = self.sourevo_dds_ids.filtered(lambda l: l.status in ('new', 'DRAFT'))
        if not lines:
            raise UserError(_('The statements of %s are already submitted.', self.name))
        lines._sourevo_create_remote()
        lines._sourevo_check()
        wizard = self.env['sourevo.dds.submit'].create({'picking_id': self.id, 'line_ids': [(6, 0, lines.ids)]})
        return {
            'type': 'ir.actions.act_window', 'res_model': 'sourevo.dds.submit', 'res_id': wizard.id,
            'view_mode': 'form', 'target': 'new', 'name': _('Submit to TRACES'),
        }

    def action_sourevo_refresh(self):
        self.mapped('sourevo_dds_ids').action_sourevo_refresh()
        return True
