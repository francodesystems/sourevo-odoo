{
    'name': 'Sourevo EUDR: Due Diligence Statements to TRACES',
    'version': '17.0.1.0.0',
    'category': 'Inventory/Purchase',
    'summary': 'EUDR compliance for importers: submit due diligence statements (DDS) to EU TRACES from your goods '
               'receipts, with suppliers, plots, satellite checks and the reference number back in Odoo',
    'description': """
Sourevo EUDR
============
EUDR compliance (Regulation (EU) 2023/1115) from Odoo Inventory and Purchase.
Connects Odoo with Sourevo (sourevo.com), the service that submits due
diligence statements (DDS) to the EU TRACES system through its official API.

* Settings: your Sourevo API key, a connection test, signed webhooks and the
  company, role and activity that submit in TRACES.
* Products: EUDR flag, 8-digit CN code and, for wood, pulp and paper, the
  scientific and common name.
* Suppliers: send them to Sourevo, invite them to their portal, see their
  trust level, their plots and the satellite check of each plot.
* Plots: upload a GeoJSON file as proposals the supplier confirms; rejections
  and satellite flags arrive as activities.
* Receipts: one statement per EUDR product with its net weight and plots,
  checked before submitting, submitted to TRACES; the reference and
  verification numbers come back to the receipt and its report.
* Kept in sync: webhooks, or a scheduled action every 15 minutes for
  databases that are not reachable from the internet. Amend the plots of a
  statement already in TRACES.

Data sent to Sourevo: nothing until you enter your own API key. Then, the
suppliers, products, plots and receipts you send (names, country, tax ID,
address, email and phone of the supplier; description and CN code of the
product; net weight and plots of the receipt).

Requires a Sourevo account. The API is included from the Pro plan (also
Forwarder and Enterprise). In the 14-day free trial it submits to the TRACES
test environment (or a simulated TRACES), with numbers that have no legal
value. Developer documentation: https://sourevo.com/en/developers
""",
    'author': 'Francodesystems',
    'website': 'https://sourevo.com',
    'support': 'juan.canton@francodesystems.com',
    'images': ['static/description/cover.png', 'static/description/receipt.png', 'static/description/submit.png',
               'static/description/supplier.png', 'static/description/settings.png'],
    'license': 'OPL-1',
    'depends': ['purchase', 'stock', 'contacts'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/ir.model.access.csv',
        'security/sourevo_security.xml',
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
