{
    'name': 'Sourevo EUDR Lite: free EUDR records for traders and downstream operators',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Purchase',
    'summary': 'Free EUDR records for traders and downstream operators: DDS reference numbers on receipts, lots, '
               'delivery slips and invoices, asked to your supplier and kept for five years in Sourevo',
    'description': """
Sourevo EUDR Lite
=================
What Article 5 of the EUDR (Regulation (EU) 2023/1115 as amended by Regulation
(EU) 2025/2650) asks of traders and downstream operators, from Odoo Inventory,
Purchase and Sales, kept for five years in the free trader plan of Sourevo.

* Receipts: the reference and verification numbers of the due diligence
  statements your supplier gives you, with a warning when an operator's number
  is missing. Recorded in Sourevo as purchases when the receipt is validated.
* Ask your supplier: Sourevo emails a one-time link where the supplier types
  the number, without an account. The answer arrives in Odoo as a proposal you
  accept or reject.
* Lots: each lot shows the numbers of the receipt that brought it in.
* Deliveries: the numbers come from the lots delivered (or the receipts you
  choose) and are recorded in Sourevo as a sale linked to those purchases.
* Delivery slips and customer invoices print the numbers for your customer.
* Contacts: supplier kind (operator, downstream operator, trader) and the data
  Article 5.3 asks for, with their history in Sourevo.

Free, with no end date: the trader plan of Sourevo (sourevo.com). Data sent to
Sourevo: nothing until you enter your API key. Then the EUDR receipts and
deliveries you validate (date, product description, CN code, quantity, the
numbers) and their suppliers and customers (name, address, email, website,
country, tax ID).

Importers who submit statements to TRACES: see the module Sourevo EUDR.
""",
    'author': 'Francodesystems',
    'website': 'https://sourevo.com',
    'support': 'juan.canton@sourevo.com',
    'license': 'LGPL-3',
    'depends': ['purchase_stock', 'sale_stock', 'account'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/ir.model.access.csv',
        'security/sourevo_security.xml',
        'data/ir_cron.xml',
        'views/res_config_settings_views.xml',
        'views/product_template_views.xml',
        'views/res_partner_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_lot_views.xml',
        'wizard/sourevo_trade_reject_views.xml',
        'report/report_delivery.xml',
        'report/report_invoice.xml',
    ],
    'installable': True,
    'application': False,
}
