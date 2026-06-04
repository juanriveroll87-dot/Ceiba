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
| `GET /reca/busqueda.php?sector=recas&search_type=advanced&ramo=<RAMO>&page=<N>&limit=<L>` | contratos paginados (JSON) |
| `GET /reca/tarjeta_recas.php?numreg=<NUMREG>` | detalle del contrato (HTML): estatus, CNSF, documentos |
| `POST /reca/openfilesecure.php` (`file=<token>`) | descarga el PDF de un documento |

**No existe un ramo "Vida" único.** El scraper enumera todos los ramos que
contienen "vida" (sin acentos/mayúsculas: `Vida-Grupo`, `Vida-Individual` y
combinaciones) y une los resultados deduplicando por número de registro.

## Uso

```bash
pip install -r requirements.txt

python reca_scraper.py                 # listado: CSV/JSON + match + resumen (rápido)
python reca_scraper.py --pdfs          # + descarga Condiciones Generales de los match
python reca_scraper.py --pdfs --pdf-scope all   # CG de TODO Vida (para análisis de contenido)
python reca_scraper.py --enrich all    # + estatus/CNSF/documentos de TODO Vida (lento)
python reca_scraper.py --pdfs --pdf-types "condiciones generales,caratula"
python reca_scraper.py --terms "orfandad,huerfan,educac,beca,renta"   # ajusta el match
```

## Salidas (`./output`)

- `vida_contratos.json` / `vida_contratos.csv` — todos los contratos de Vida.
- `vida_match.csv` — solo los que hacen match con los términos objetivo
  (`orfandad, escolar, educativ, beca, colegiatura, estudia, deudores,
  continuidad`), comparando contra ramo y nombre comercial sin acentos.
- `scraper.log` — log de ejecución.
- `./pdfs/<Institución>/<numreg>/` — PDFs descargados (con `--pdfs`).

Campos por contrato: `sistema, institucion, ramo, producto, ramo_completo,
nombre_comercial, numero_registro, cnsf, estatus, ramo_consulta, match,
matched_terms`, columnas `doc_*` (token de cada documento) y, en el JSON, la
lista `documentos` con `tipo/archivo/token`.

## Enriquecimiento y documentos

El listado (`busqueda.php`) **no** trae estatus ni documentos: eso vive en la
tarjeta (`tarjeta_recas.php?numreg=...`), una por contrato. Por eso es opt-in:

- `--enrich none` (default): solo listado, rápido.
- `--enrich match`: pide la tarjeta solo de los contratos con match.
- `--enrich all`: pide la tarjeta de todos (1 request por contrato → lento).

Los PDFs se sirven por **POST** a `openfilesecure.php` con un token cifrado que se
extrae de la tarjeta (no hay URL directa con GET). `--pdfs` implica
`--enrich match` y descarga, por defecto, las **Condiciones Generales** de los
contratos con match a `./pdfs/<Institución>/<numreg>/`.

## Robustez

UA realista, pausa de ~1.5 s (con jitter) entre requests, reintentos con backoff
exponencial (2/4/8/16 s), manejo de timeouts sin abortar, logging a archivo y
resumen final (total Vida, cuántos match, desglose por institución).
