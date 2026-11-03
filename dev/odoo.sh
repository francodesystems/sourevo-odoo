#!/bin/sh
# Runs odoo in the dev container with the database of docker-compose.yml: dev/odoo.sh -d prueba -i sourevo_eudr --stop-after-init
exec docker compose -p sourevo-odoo-17 -f "$(dirname "$0")/docker-compose.yml" exec -T odoo \
    odoo --db_host db --db_user odoo --db_password odoo --addons-path /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons \
    --http-port 8170 "$@"
