from collections import defaultdict

from odoo.tools import LazyTranslate

_lt = LazyTranslate(__name__)

# The pre-submission check of Sourevo (GET /dds/{id}/check): one text per issue code, as in Sourevo.
CHECK_MESSAGES = {
    'REFERENCE_TOO_LONG': _lt('The internal reference exceeds {max} characters.'),
    'COMMENT_TOO_LONG': _lt('The comment exceeds {max} characters.'),
    'TOO_MANY_ASSOCIATED': _lt('Too many associated statements (max {max}).'),
    'TOO_MANY_PRODUCERS': _lt('Too many producers (max {max}).'),
    'GEOJSON_TOO_LARGE': _lt('Geolocation is {bytes} bytes; the maximum is {max}.'),
    'NO_RISK_ASSESSMENT': _lt('The risk assessment is missing.'),
    'OPERATOR_NO_CREDENTIALS': _lt('The operator has no TRACES credentials.'),
    'OPERATOR_NO_ADDRESS': _lt('The represented operator has no address.'),
    'PRODUCT_NOT_IN_ANNEX': _lt('HS heading {hsHeading} is not in EUDR Annex I.'),
    'PRODUCT_NOT_YET_APPLICABLE': _lt('This heading only applies from {appliesFrom}.'),
    'BATCH_NO_PLOT': _lt('The batch has no origin plots.'),
    'BATCH_NET_MASS_REQUIRED': _lt('Import and export require the net weight.'),
    'PLOT_NOT_VISIBLE': _lt('A plot of the batch is no longer shared with you.'),
    'PLOT_NO_COUNTRY': _lt('Plot without country.'),
    'PLOT_NO_AREA': _lt('Plot without area.'),
    'PLOT_GEO_INVALID': _lt('Plot with invalid geolocation.'),
    'PLOT_POINT_OVER_THRESHOLD': _lt('{areaHa} ha plot given as a point: above {max} ha a polygon is required.'),
    'PLOT_CORRECTION_REQUESTED': _lt('You asked for this plot to be corrected.'),
    'PLOT_NOT_VERIFIED': _lt('Plot declared by the supplier, not yet verified by you.'),
    'PLOT_NO_SATELLITE_CHECK': _lt('Plot in a country that is not low risk ({country}) without a current satellite check.'),
    'PLOT_SATELLITE_LOSS': _lt('The satellite check found tree cover loss after 2020 on this plot. Review it before submitting.'),
    'PLOT_SATELLITE_INCONCLUSIVE': _lt('The satellite check of this plot was inconclusive. Review it on the map before submitting.'),
    'PLOT_SATELLITE_FAILED': _lt('The satellite check of this plot could not be completed. Run it again.'),
    'SUPPLIER_TRUST_BELOW_VALIDATED': _lt('Supplier without a validated tax identity (level {trustLevel}).'),
    'PLOT_UPLOADED_BY_IMPORTER': _lt('You uploaded this plot on behalf of the supplier and the supplier has not confirmed it yet.'),
    'SUPPLIER_NO_LEGAL_NAME': _lt("The supplier's legal name is missing (EUDR Art. 9)."),
    'SUPPLIER_NO_ADDRESS': _lt("The supplier's postal address is missing (EUDR Art. 9)."),
    'SUPPLIER_NO_EMAIL': _lt("The supplier's email address is missing (EUDR Art. 9)."),
    'PLOT_PROPOSAL_REJECTED': _lt('The supplier rejected this plot. Remove it from the batch.'),
}


def issue_text(issue, plot_names=None, lang=None):
    """The text of a CheckIssue ({key, code, level, entityId, data}), with the plot name when there is one."""
    code = issue.get('code') or ''
    data = defaultdict(lambda: '?', {k: v for k, v in (issue.get('data') or {}).items() if v is not None})
    template = CHECK_MESSAGES.get(code)
    text = template._translate(lang or '').format_map(data) if template else code.replace('_', ' ').capitalize()
    if issue.get('level') == 'plot' and plot_names and issue.get('entityId') in plot_names:
        text = f'{plot_names[issue["entityId"]]}: {text}'
    return text
