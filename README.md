# Sourevo para Odoo

Módulo de Odoo para cumplir el EUDR (Reglamento (UE) 2023/1115) con [Sourevo](https://sourevo.com): la
declaración de diligencia debida (DDS) que se presenta en TRACES antes de la aduana, hecha desde las
recepciones de Odoo, con el número de referencia de vuelta en el albarán.

| Módulo | Nombre en la tienda | Qué hace |
|---|---|---|
| `sourevo_eudr` | Sourevo EUDR | Ajustes (clave `svk_`, probar conexión, operador de TRACES, avisos firmados); proveedores a Sourevo con invitación a su portal, nivel de confianza y parcelas; parcelas desde un GeoJSON; productos EUDR con código NC; en la recepción, una DDS por producto EUDR (lote con peso neto y parcelas), comprobación con bloqueos y avisos, presentación en TRACES y números de referencia y verificación en el albarán y su informe. |

Una rama por versión de Odoo: `20.0`, `19.0`, `18.0`, `17.0`. Necesita una cuenta de Sourevo con la API
(planes Pro, Transitario y Empresa; en la prueba de 14 días, en modo simulado con referencias SIM); el
módulo es gratis. API: https://sourevo.com/es/desarrolladores (OpenAPI en `/api/v1/openapi.json`).

Textos en inglés con traducciones en `i18n/` (es, fr, pt, de, it, nl, pl). La ficha de la tienda
(`static/description/index.html`) y la portada salen de `fds-odoo-apps/scripts/store_page.py` y
`store_cover.py` con `scripts/store_pages/sourevo_eudr.py`.

## Probar en local

```bash
docker compose -p sourevo-odoo-18 -f dev/docker-compose.yml up -d     # Odoo de esta rama en http://localhost:8179
dev/odoo.sh -d prueba -i sourevo_eudr --stop-after-init
dev/odoo.sh -d prueba -u sourevo_eudr --test-tags /sourevo_eudr --stop-after-init
```

Las pruebas no llaman a Sourevo: simulan la API con las respuestas de su OpenAPI. Para probar de verdad,
una clave `svk_` de una organización de prueba en Ajustes > Sourevo (y la dirección
`http://host.docker.internal:3200/api/v1` para un Sourevo local).

Autor: Francodesystems. Licencia OPL-1.
