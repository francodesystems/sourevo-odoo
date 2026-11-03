{
    'name': 'Sourevo EUDR',
    'version': '20.0.1.0.0',
    'category': 'Inventory/Purchase',
    'summary': 'EUDR compliance from Odoo: suppliers, plots, receipts and the due diligence statement submitted '
               'to TRACES, with its reference number back on the receipt',
    'description': """
Sourevo EUDR (sourevo.com)
==========================
Connects Odoo with Sourevo, the EUDR compliance service for importers
(Regulation (EU) 2023/1115): the due diligence statement (DDS) submitted to
TRACES before customs.

* Suppliers: send them to Sourevo, invite them to their portal to declare
  their plots, see their trust level and their plots.
* Plots: upload a GeoJSON file as proposals the supplier confirms in its
  portal; rejections and satellite flags arrive as activities.
* Products: EUDR flag, CN code and, for wood, pulp and paper, the scientific
  and common name.
* Receipts: one click prepares the statement of each EUDR product (batch with
  its net weight and plots), checks it and submits it to TRACES; the
  reference and verification numbers come back to the receipt and its report.
* Stays up to date: signed Sourevo webhooks, and a scheduled action every
  15 minutes for databases that are not reachable from the internet.

Data sent to Sourevo: nothing until you enter your own API key. Then, the
suppliers, products, plots and receipts you send (names, country, tax ID,
address, email and phone of the supplier; description and CN code of the
product; net weight and plots of the receipt).

Requires a Sourevo account: the API is included in the Pro, Forwarder and
Enterprise plans and, in the 14-day trial, works in simulated mode.
""",
    'author': 'Francodesystems',
    'website': 'https://sourevo.com',
    'support': 'juan.canton@francodesystems.com',
    'images': ['static/description/cover.png'],
    'license': 'OPL-1',
    'depends': ['purchase', 'stock', 'contacts'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/ir.access.csv',
        'data/ir_cron.xml',
        'views/res_config_settings_views.xml',
        'views/sourevo_dds_views.xml',
        'views/res_partner_views.xml',
        'views/product_template_views.xml',
        'views/stock_picking_views.xml',
        'wizard/sourevo_wizard_views.xml',
        'report/report_picking.xml',
    ],
    'installable': True,
    'application': False,
}
