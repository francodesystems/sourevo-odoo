import json

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SourevoDdsSubmit(models.TransientModel):
    """The check of the statements of a receipt and their submission to TRACES (or of an amendment)."""

    _name = 'sourevo.dds.submit'
    _description = 'Submit EUDR statements to TRACES'

    picking_id = fields.Many2one('stock.picking', required=True, readonly=True)
    line_ids = fields.Many2many('sourevo.dds', string='Statements', readonly=True)
    amend = fields.Boolean('Amendment', readonly=True, help='The plot changes of a statement already in TRACES.')
    summary = fields.Html(compute='_compute_summary', sanitize=False)
    has_blocking = fields.Boolean(compute='_compute_summary')
    has_warnings = fields.Boolean(compute='_compute_summary')
    simulated = fields.Boolean(compute='_compute_summary')
    needs_credentials = fields.Boolean(compute='_compute_summary')
    acknowledge = fields.Boolean('I acknowledge the warnings and submit under my responsibility')

    @api.depends('line_ids.check_blocking', 'line_ids.check_warnings', 'line_ids.check_ready')
    def _compute_summary(self):
        for wizard in self:
            parts = []
            for line in wizard.line_ids:
                items = [Markup('<li class="text-danger">%s</li>') % t for t in (line.check_blocking or '').splitlines()]
                items += [Markup('<li class="text-warning">%s</li>') % t for t in (line.check_warnings or '').splitlines()]
                if not items:
                    items = [Markup('<li class="text-success">%s</li>') % _('No issues.')]
                parts.append(Markup('<p class="mb-1"><strong>%s</strong> · %s</p><ul>%s</ul>') % (
                    line.name, line.product_id.display_name, Markup('').join(items)))
            wizard.summary = Markup('').join(parts)
            wizard.has_blocking = any(line.check_blocking or not line.check_ready for line in wizard.line_ids)
            wizard.has_warnings = any(wizard.line_ids.mapped('check_warnings'))
            wizard.simulated = wizard.picking_id.company_id.sourevo_mode in ('simulated', 'test')
            wizard.needs_credentials = any('OPERATOR_NO_CREDENTIALS' in (line.check_blocking_codes or '')
                                           for line in wizard.line_ids)

    def action_open_operators(self):
        """The TRACES companies of Sourevo, where the TRACES credentials are entered."""
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'target': 'new',
                'url': self.picking_id.company_id._sourevo_web_url('/dds/operators')}

    def _reopen(self):
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'new', 'name': _('Amend in TRACES') if self.amend else _('Submit to TRACES')}

    def action_check_again(self):
        self.ensure_one()
        self.line_ids._sourevo_check()
        return self._reopen()

    def action_submit(self):
        self.ensure_one()
        if self.has_blocking:
            raise UserError(_('Fix the blocking issues first (in Sourevo or in the receipt) and check again.'))
        if self.has_warnings and not self.acknowledge:
            raise UserError(_('Tick that you acknowledge the warnings to submit.'))
        if self.amend:
            for line in self.line_ids:
                keys = json.loads(line.check_warning_keys or '[]')
                if not line._sourevo_amend(keys):
                    # New warnings appeared with the staged plots: they have to be acknowledged too.
                    self.acknowledge = False
                    return self._reopen()
            return {'type': 'ir.actions.act_window_close'}
        self.line_ids._sourevo_submit()
        return {'type': 'ir.actions.act_window_close'}
