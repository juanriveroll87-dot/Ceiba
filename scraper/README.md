# Scraper RECAS / Vida (CONDUSEF)

Extrae los contratos del **RECAS** (sistema de seguros) en el **ramo Vida** desde
la API JSON del portal `registros.condusef.gob.mx/reca/`, descubierta en el
reconocimiento (ver [`../recon`](../recon)).

> Debe correrse en una máquina con acceso de red a CONDUSEF (no el sandbox web,
> que bloquea el host por allowlist de egress).

## Endpoints usados (hallados en el recon)

| Endpoint | Para qué |
|---|---|
| `GET /reca/get_options.php?sector=recas&type=ramos` | catálogo de ramos |
| `GET /reca/get_options.php?sector=recas&type=instituciones` | catálogo de aseguradoras |
| `GET /reca/busqueda.php?sector=recas&search_type=advanced&ramo=<RAMO>&page=<N>&limit=<L>` | contratos paginados |

**No existe un ramo "Vida" único.** El scraper enumera todos los ramos que
contienen "vida" (sin acentos/mayúsculas: `Vida-Grupo`, `Vida-Individual` y
combinaciones) y une los resultados deduplicando por número de registro.

## Uso

```bash
pip install -r requirements.txt
python reca_scraper.py                 # todo Vida -> CSV/JSON + match + resumen
python reca_scraper.py --limit 100 --delay 1.5
python reca_scraper.py --out salida
```

## Salidas (`./output`)

- `vida_contratos.json` / `vida_contratos.csv` — todos los contratos de Vida.
- `vida_match.csv` — solo los que hacen match con los términos objetivo
  (`orfandad, escolar, educativ, beca, colegiatura, estudia, deudores,
  continuidad`), comparando contra ramo y nombre comercial sin acentos.
- `scraper.log` — log de ejecución.

Campos por contrato: `sistema, institucion, ramo, producto, ramo_completo,
nombre_comercial, numero_registro, vigencia, ramo_consulta, match,
matched_terms` y columnas `doc_*` (ver abajo).

## Robustez

UA realista, pausa de ~1.5 s (con jitter) entre requests, reintentos con backoff
exponencial (2/4/8/16 s), manejo de timeouts sin abortar, logging a archivo y
resumen final (total Vida, cuántos match, desglose por institución).

## Pendiente: descarga de PDFs

El listado **no trae las URLs de documentos** (condiciones generales, carátula,
solicitud, endosos); la última columna viene `null`. Esas URLs salen de un
**endpoint de detalle** que se dispara al hacer clic en un contrato y que aún
no se ha capturado.

**Para capturarlo (30 seg):**

```bash
cd ../recon
python recon_reca.py
# en el navegador: RECAS -> Búsqueda Avanzada -> Ramo=Vida-Grupo -> Buscar
# ahora HAZ CLIC en una fila/contrato para abrir su detalle/documentos
# vuelve a la terminal y presiona ENTER
```

Manda `recon_out/xhr_endpoints.json`: ahí aparecerá el endpoint de detalle
(p. ej. `detalle.php?...` o `get_documentos.php?...`) con las URLs de los PDFs.
Con eso se completa `row_to_contract()` (campos `doc_*`) y `download_documents()`
para bajar los PDFs a `./pdfs/<Institución>/`.
