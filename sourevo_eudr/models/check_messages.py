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
    'OPERATOR_NO_CREDENTIALS': _lt('The company has no TRACES credentials.'),
    'OPERATOR_NO_ADDRESS': _lt('The represented operator has no address.'),
    'PRODUCT_NOT_IN_ANNEX': _lt('HS heading {hsHeading} is not in EUDR Annex I.'),
    'PRODUCT_NOT_YET_APPLICABLE': _lt('This heading only applies from {appliesFrom}.'),
    'BATCH_NO_PLOT': _lt('The batch has no origin plots.'),
    'BATCH_NET_MASS_REQUIRED': _lt('The net weight in kg is required.'),
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
    'OPERATOR_NO_EORI': _lt('The company has no EORI number in Sourevo. TRACES refuses an import or export when the operator’s TRACES profile lacks it: add it in Settings and check it is in TRACES too.'),
    'OPERATOR_NO_TEST_CREDENTIALS': _lt("To submit during the trial, add this company's TRACES test username and key in Settings."),
    'ROLE_NOT_SUBMITTABLE': _lt('Since Regulation (EU) 2025/2650 traders no longer submit DDS in TRACES: only the operator or its authorised representative does. Change the role to Operator or Authorised representative of an operator.'),
    'PLOT_SATELLITE_OUTDATED': _lt("This plot's satellite check is more than 30 days old or was made with older data than the current one. It will be kept as it is in the record: update it before submitting if you can."),
    'PLOT_PLANTATION_HARVEST_NO_CONCESSION': _lt('Harvest in a planted forest: {natural} natural forest in 2020. For wood this is neither deforestation nor degradation.'),
    'PLOT_NATURAL_FOREST_LOSS': _lt('Loss or alerts on a plot with {natural} natural forest in 2020: possible forest degradation.'),
    'PLOT_PLANTATION_HARVEST': _lt('Harvest in a planted forest: {natural} natural forest in 2020 (concession: {concession}). For wood this is neither deforestation nor degradation.'),
    'PLOT_INDIGENOUS_LAND': _lt('The plot lies inside an indigenous territory ({name}). The EUDR requires respect for their rights and their free, prior and informed consent.'),
    'PLOT_PROTECTED_AREA': _lt('The plot lies inside a protected area ({name}). Producing there may be forbidden or need a permit.'),
    'PLOT_OFFICIAL_DEFORESTATION': _lt('The country’s official map shows deforestation on the plot after 2020 ({source}). It is a signal like the satellite’s: it has to be cleared up.'),
    'SUPPLIER_DOCUMENT_EXPIRED': _lt("The supplier's legality documents have expired ({n})."),
    'SUPPLIER_NO_LEGALITY_EVIDENCE': _lt('No legality document from the supplier (FLEGT licence, legality verification, certificate or its declaration).'),
    'PLOTS_FROM_SUPPLIER_DOCUMENT': _lt('{n} plots taken from a supplier document, with the proof of origin kept.'),
    'RISK_CONCLUSION_OUTDATED': _lt('The assessment concluded "negligible risk", but the data shows {n} unresolved legal gaps. Conclude the risk again.'),
    'ASSOCIATED_INVALID': _lt('The supplier DDS gave {result} when verified in TRACES: you cannot rely on it.'),
    'ASSOCIATED_NOT_VERIFIED': _lt('Supplier DDS not verified in TRACES. Verify it with its reference and verification numbers.'),
    'ORIGIN_SANCTIONED': _lt('Wood from {country}: EU sanctions ban imports of wood products of that origin (Regulation (EU) 833/2014 for Russia, Regulation (EC) 765/2006 for Belarus). No DDS can fix it: remove those plots or change the origin.'),
    'RISK_ACCEPTED_GAPS': _lt('You submit with the risk conclusion sealed under your own responsibility: Sourevo still sees {n} legal gap(s). By submitting you declare that you carried out due diligence and that the risk is nil or negligible (EUDR Art. 4(2)).'),
    'TRIAL_SHARED_ACCOUNT': _lt("It will be submitted with Sourevo's test account and you will not see it in your TRACES. To see it in your TRACES test environment, add your test credentials in Settings."),
}


def issue_text(issue, plot_names=None, lang=None):
    """The text of a CheckIssue ({key, code, level, entityId, data}), with the plot name when there is one."""
    code = issue.get('code') or ''
    data = defaultdict(lambda: '?', {k: v for k, v in (issue.get('data') or {}).items() if v is not None})
    if code == 'PLOT_PLANTATION_HARVEST' and 'concession' not in data:
        code = 'PLOT_PLANTATION_HARVEST_NO_CONCESSION'
    template = CHECK_MESSAGES.get(code)
    text = template._translate(lang or '').format_map(data) if template else code.replace('_', ' ').capitalize()
    if issue.get('level') == 'plot' and plot_names and issue.get('entityId') in plot_names:
        text = f'{plot_names[issue["entityId"]]}: {text}'
    return text
