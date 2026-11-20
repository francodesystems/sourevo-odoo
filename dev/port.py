"""Ports the module one Odoo version down, in place: python3 dev/port.py 19 (run on a copy of the 20.0 branch),
then 18 on the 19.0 branch and 17 on the 18.0 branch. What changes is what changed in decafirma-odoo.
The Lite module: python3 dev/port.py 19 sourevo_eudr_lite (same steps, its own files)."""
import csv
import io
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MOD = ROOT / (sys.argv[2] if len(sys.argv) > 2 else 'sourevo_eudr')
LITE = MOD.name == 'sourevo_eudr_lite'


def edit(path, *pairs, regex=False):
    p = MOD / path if not str(path).startswith('/') else pathlib.Path(path)
    s = p.read_text()
    for old, new in pairs:
        s2 = re.sub(old, new, s) if regex else s.replace(old, new)
        if s2 == s:
            raise SystemExit(f'{p}: nothing to replace for {old!r}')
        s = s2
    p.write_text(s)


def to_19():
    edit('__manifest__.py', ("'version': '20.0.", "'version': '19.0."),
         ("'security/ir.access.csv',", "'security/ir.model.access.csv',\n        'security/sourevo_security.xml',"))
    edit('views/res_config_settings_views.xml', ('utm_campaign=odoo20', 'utm_campaign=odoo19'))
    # ir.access.csv (Odoo 20) -> ir.model.access.csv and the multi-company rules as ir.rule records.
    src = MOD / 'security' / 'ir.access.csv'
    rows = list(csv.DictReader(io.StringIO(src.read_text())))
    out = io.StringIO()
    w = csv.writer(out, lineterminator='\n')
    w.writerow(['id', 'name', 'model_id:id', 'group_id:id', 'perm_read', 'perm_write', 'perm_create', 'perm_unlink'])
    rules = []
    for r in rows:
        model = 'model_' + r['model_id'].replace('.', '_')
        if r['id'].startswith('rule_'):
            rules.append((r['id'], r['name'], model, r['domain']))
            continue
        op = r['operation']
        # operation: r(ead), u(pdate) = write, c(reate), d(elete) = unlink
        w.writerow([r['id'], r['name'], model, r['group_id/id'], *('1' if c in op else '0' for c in 'rucd')])
    (MOD / 'security' / 'ir.model.access.csv').write_text(out.getvalue())
    src.unlink()
    xml = ['<?xml version="1.0" encoding="utf-8"?>', '<odoo>']
    for rid, name, model, domain in rules:
        xml += [f'    <record id="{rid}" model="ir.rule">', f'        <field name="name">{name}</field>',
                f'        <field name="model_id" ref="{model}"/>',
                f'        <field name="domain_force">{domain}</field>', '    </record>']
    xml.append('</odoo>\n')
    (MOD / 'security' / 'sourevo_security.xml').write_text('\n'.join(xml))
    for f in ('views/res_config_settings_views.xml', 'views/res_partner_views.xml', 'views/stock_picking_views.xml'):
        p = MOD / f
        p.write_text(p.read_text().replace('icon="arrow_forward"', 'icon="fa-arrow-right"')
                     .replace('icon="forest"', 'icon="fa-tree"').replace('icon="delete"', 'icon="fa-trash"'))
    if not LITE:
        edit(ROOT / 'dev' / 'docker-compose.yml', ('odoo:20.0', 'odoo:19.0'))


def to_18():
    edit('__manifest__.py', ("'version': '19.0.", "'version': '18.0."))
    edit('views/res_config_settings_views.xml', ('utm_campaign=odoo19', 'utm_campaign=odoo18'))
    for f in MOD.glob('models/*.py'):
        s = f.read_text()
        s2 = re.sub(r"    _(\w+) = models\.Constraint\('([^']*)', '([^']*)'\)",
                    lambda m: f"    _sql_constraints = [('{m[1]}', '{m[2]}', '{m[3]}')]", s)
        if s2 != s:
            f.write_text(s2)
    if not LITE:
        edit('views/res_partner_views.xml', ('<field name="group_ids"', '<field name="groups_id"'))
        edit(ROOT / 'dev' / 'docker-compose.yml', ('odoo:19.0', 'odoo:18.0'))


def to_17():
    edit('__manifest__.py', ("'version': '18.0.", "'version': '17.0."))
    edit('views/res_config_settings_views.xml', ('utm_campaign=odoo18', 'utm_campaign=odoo17'))
    for f in list(MOD.glob('views/*.xml')) + list(MOD.glob('wizard/*.xml')):
        s = f.read_text()
        s2 = (s.replace('<list', '<tree').replace('</list>', '</tree>')
              .replace('<field name="view_mode">list,form</field>', '<field name="view_mode">tree,form</field>'))
        if s2 != s:
            f.write_text(s2)
    for f in MOD.glob('models/*.py'):
        s = f.read_text()
        s2 = s.replace("'view_mode': 'list,form'", "'view_mode': 'tree,form'")
        if s2 != s:
            f.write_text(s2)
    if LITE:
        return
    # No LazyTranslate in 17: odoo._lt, translated by str() with the language of a local "context".
    edit('models/check_messages.py',
         ('from odoo.tools import LazyTranslate\n\n_lt = LazyTranslate(__name__)\n', 'from odoo import _lt\n'),
         ("    template = CHECK_MESSAGES.get(code)\n    text = template._translate(lang or '').format_map(data)",
          "    template = CHECK_MESSAGES.get(code)\n    # _lt reads the language from this local, as _() does.\n"
          "    context = {'lang': lang or 'en_US'}  # noqa: F841\n    text = str(template).format_map(data)"))
    edit(ROOT / 'dev' / 'docker-compose.yml', ('odoo:18.0', 'odoo:17.0'))


if __name__ == '__main__':
    {'19': to_19, '18': to_18, '17': to_17}[sys.argv[1]]()
