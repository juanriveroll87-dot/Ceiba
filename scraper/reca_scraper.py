#!/usr/bin/env python3
"""
Scraper del RECAS (Registro de Contratos de Adhesión de Seguros) de CONDUSEF.

Usa la API JSON descubierta en el reconocimiento (ver ../recon):

  GET /reca/get_options.php?sector=recas&type=ramos
  GET /reca/get_options.php?sector=recas&type=instituciones
  GET /reca/busqueda.php?sector=recas&search_type=advanced&ramo=<RAMO>&page=<N>&limit=<L>

Estrategia (vía httpx, la preferida): en vez de filtrar por "Vida" (que no existe
como ramo único), enumera TODOS los ramos que contengan "vida" (sin distinguir
mayúsculas/acentos) y pagina cada uno. Une y deduplica por número de registro.

Salidas en ./output:
  vida_contratos.json   -> todos los contratos de Vida con sus campos
  vida_contratos.csv    -> idem en CSV
  vida_match.csv        -> solo los que hicieron match con los términos objetivo
  scraper.log           -> log de ejecución

Términos objetivo (orfandad / continuidad educativa / deudores): se marcan en la
columna booleana `match` y se listan en `matched_terms`.

NOTA sobre PDFs: el listado NO incluye las URLs de documentos (condiciones
generales, carátula, etc.). Eso vive en un endpoint de detalle que aún hay que
capturar (clic en un contrato durante el recon). Cuando lo tengamos, se conecta
en download_documents().

Uso:
  pip install -r requirements.txt
  python reca_scraper.py                 # todo Vida + CSV/JSON + match + resumen
  python reca_scraper.py --limit 100     # tamaño de página (default 100)
  python reca_scraper.py --delay 1.5     # segundos entre requests (default 1.5)
  python reca_scraper.py --out salida    # carpeta de salida
"""

import argparse
import csv
import json
import logging
import random
import sys
import time
import unicodedata
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("Falta httpx. Instala con:  pip install -r requirements.txt")

BASE = "https://registros.condusef.gob.mx/reca"
SECTOR = "recas"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Referer": f"{BASE}/",
    "X-Requested-With": "XMLHttpRequest",
}

# Términos a marcar (orfandad / continuidad educativa / Vida Grupo Deudores).
TARGET_TERMS = [
    "orfandad", "escolar", "educativ", "beca",
    "colegiatura", "estudia", "deudores", "continuidad",
]

# Posiciones de columnas en cada fila de busqueda.php -> data[]
C_IDX, C_SISTEMA, C_INSTITUCION, C_RAMO, C_NOMBRE, C_REGISTRO, C_EXTRA = range(7)

MAX_RETRIES = 4

log = logging.getLogger("reca")


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def normalize(text: str) -> str:
    """minúsculas + sin acentos, para comparar términos de forma robusta."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    return sin_acentos.lower()


def match_terms(*fields: str) -> list[str]:
    """Devuelve la lista de términos objetivo presentes en los campos dados."""
    blob = normalize(" ".join(f for f in fields if f))
    return [t for t in TARGET_TERMS if t in blob]


def setup_logging(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(out_dir / "scraper.log", encoding="utf-8"),
        ],
    )


# --------------------------------------------------------------------------- #
# Acceso HTTP con reintentos y backoff exponencial
# --------------------------------------------------------------------------- #
def get_json(client: httpx.Client, path: str, params: dict, delay: float) -> dict | None:
    """GET con reintentos (backoff 2,4,8,16s) y pausa cortés entre llamadas."""
    url = f"{BASE}/{path}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = client.get(url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            # pausa cortés con jitter
            time.sleep(delay + random.uniform(0, 0.5))
            return data
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            wait = 2 ** attempt
            log.warning("Intento %d/%d falló para %s %s: %s (espero %ds)",
                        attempt, MAX_RETRIES, path, params, exc, wait)
            if attempt < MAX_RETRIES:
                time.sleep(wait)
    log.error("Agoté reintentos para %s %s", path, params)
    return None


# --------------------------------------------------------------------------- #
# Catálogos
# --------------------------------------------------------------------------- #
def fetch_options(client: httpx.Client, tipo: str, delay: float) -> list[str]:
    """Lista de valores (id) de un catálogo: 'ramos' o 'instituciones'."""
    data = get_json(client, "get_options.php",
                    {"sector": SECTOR, "type": tipo}, delay)
    if not data or not data.get("success"):
        log.error("No pude obtener el catálogo '%s'", tipo)
        return []
    return [item["id"] for item in data.get("data", [])]


def vida_ramos(all_ramos: list[str]) -> list[str]:
    """Ramos que contienen 'vida' (sin distinguir mayúsculas/acentos)."""
    return [r for r in all_ramos if "vida" in normalize(r)]


# --------------------------------------------------------------------------- #
# Contratos
# --------------------------------------------------------------------------- #
def row_to_contract(row: list, ramo_consulta: str) -> dict:
    """Convierte una fila posicional de busqueda.php en un dict con campos."""
    def g(i):
        return row[i] if i < len(row) else None

    ramo_completo = g(C_RAMO) or ""
    nombre = g(C_NOMBRE) or ""
    # "Vida-Grupo - Deudores y Cuenta-ahorradores" -> ramo / tipo de producto
    if " - " in ramo_completo:
        ramo_base, producto = ramo_completo.split(" - ", 1)
    else:
        ramo_base, producto = ramo_completo, ""

    hits = match_terms(ramo_completo, nombre)
    return {
        "sistema": g(C_SISTEMA),
        "institucion": g(C_INSTITUCION),
        "ramo": ramo_base.strip(),
        "producto": producto.strip(),
        "ramo_completo": ramo_completo,
        "nombre_comercial": nombre,
        "numero_registro": g(C_REGISTRO),
        "vigencia": g(C_EXTRA),          # suele venir null en el listado
        "ramo_consulta": ramo_consulta,  # con qué filtro de ramo se obtuvo
        "match": bool(hits),
        "matched_terms": ";".join(hits),
        # documentos: pendiente del endpoint de detalle (ver download_documents)
        "doc_condiciones_generales": "",
        "doc_caratula": "",
        "doc_solicitud": "",
        "doc_endosos": "",
    }


def fetch_ramo(client: httpx.Client, ramo: str, limit: int, delay: float) -> list[dict]:
    """Pagina todos los contratos de un ramo concreto."""
    out: list[dict] = []
    page = 1
    while True:
        data = get_json(client, "busqueda.php", {
            "sector": SECTOR,
            "search_type": "advanced",
            "ramo": ramo,
            "page": page,
            "limit": limit,
        }, delay)
        if not data or not data.get("success"):
            log.warning("Ramo '%s' pág %d sin datos; corto este ramo.", ramo, page)
            break

        rows = data.get("data", []) or []
        for row in rows:
            out.append(row_to_contract(row, ramo))

        total_pages = data.get("total_pages") or 1
        total = data.get("total")
        if page == 1:
            log.info("Ramo '%s': total=%s, páginas=%s", ramo, total, total_pages)
        if page >= total_pages or not rows:
            break
        page += 1
    return out


def scrape_vida(client: httpx.Client, limit: int, delay: float) -> list[dict]:
    """Recorre todos los ramos de Vida y deduplica por número de registro."""
    ramos = fetch_options(client, "ramos", delay)
    objetivo = vida_ramos(ramos)
    log.info("Ramos totales: %d | ramos de Vida a consultar: %d",
             len(ramos), len(objetivo))
    for r in objetivo:
        log.info("  - %s", r)

    contratos: dict[str, dict] = {}  # clave: numero_registro
    sin_registro = 0
    for ramo in objetivo:
        for c in fetch_ramo(client, ramo, limit, delay):
            key = c["numero_registro"] or f"__sin_reg_{sin_registro}"
            if not c["numero_registro"]:
                sin_registro += 1
            # Si ya existe, conservamos el primero (mismo contrato).
            contratos.setdefault(key, c)
    return list(contratos.values())


# --------------------------------------------------------------------------- #
# Descarga de documentos (PENDIENTE del endpoint de detalle)
# --------------------------------------------------------------------------- #
def download_documents(client: httpx.Client, contratos: list[dict],
                       out_dir: Path, delay: float) -> None:
    """
    Descarga los PDFs de condiciones generales de los contratos con match,
    organizados en ./pdfs/<Institución>/.

    PENDIENTE: requiere el endpoint de detalle que devuelve las URLs de los
    documentos (se captura haciendo clic en un contrato durante el recon).
    En cuanto lo tengamos:
      1. Llenar doc_* en row_to_contract a partir del detalle.
      2. Descargar aquí con reintentos/backoff hacia ./pdfs/<institucion>/.
    Por ahora es un no-op que avisa.
    """
    log.info("download_documents: pendiente del endpoint de detalle "
             "(URLs de PDFs aún no capturadas). Omitido.")


# --------------------------------------------------------------------------- #
# Escritura de salidas
# --------------------------------------------------------------------------- #
CSV_FIELDS = [
    "sistema", "institucion", "ramo", "producto", "ramo_completo",
    "nombre_comercial", "numero_registro", "vigencia", "ramo_consulta",
    "match", "matched_terms",
    "doc_condiciones_generales", "doc_caratula", "doc_solicitud", "doc_endosos",
]


def write_outputs(contratos: list[dict], out_dir: Path) -> None:
    (out_dir / "vida_contratos.json").write_text(
        json.dumps(contratos, ensure_ascii=False, indent=2), encoding="utf-8")

    def dump_csv(path: Path, rows: list[dict]) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    dump_csv(out_dir / "vida_contratos.csv", contratos)
    matched = [c for c in contratos if c["match"]]
    dump_csv(out_dir / "vida_match.csv", matched)
    log.info("Escritos: vida_contratos.json, vida_contratos.csv (%d), "
             "vida_match.csv (%d)", len(contratos), len(matched))


def print_summary(contratos: list[dict]) -> None:
    matched = [c for c in contratos if c["match"]]
    por_inst: dict[str, int] = {}
    for c in contratos:
        por_inst[c["institucion"]] = por_inst.get(c["institucion"], 0) + 1

    print("\n" + "=" * 70)
    print("RESUMEN — RECAS / Ramo Vida")
    print("=" * 70)
    print(f"Total de contratos de Vida : {len(contratos)}")
    print(f"Con match (target)         : {len(matched)}")
    if matched:
        term_count: dict[str, int] = {}
        for c in matched:
            for t in c["matched_terms"].split(";"):
                if t:
                    term_count[t] = term_count.get(t, 0) + 1
        desg = ", ".join(f"{t}={n}" for t, n in
                         sorted(term_count.items(), key=lambda x: -x[1]))
        print(f"Términos con match         : {desg}")
    print("\nDesglose por institución (top 25):")
    for inst, n in sorted(por_inst.items(), key=lambda x: -x[1])[:25]:
        print(f"  {n:4d}  {inst}")
    print("=" * 70)


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Scraper RECAS / Vida (CONDUSEF).")
    ap.add_argument("--limit", type=int, default=100, help="Tamaño de página (<=100).")
    ap.add_argument("--delay", type=float, default=1.5, help="Segundos entre requests.")
    ap.add_argument("--out", default="output", help="Carpeta de salida.")
    ap.add_argument("--pdfs", action="store_true",
                    help="Intentar descargar PDFs (requiere endpoint de detalle).")
    args = ap.parse_args()

    out_dir = Path(args.out)
    setup_logging(out_dir)
    log.info("Iniciando scraper RECAS/Vida | limit=%d delay=%.1fs",
             args.limit, args.delay)

    with httpx.Client(headers=HEADERS, follow_redirects=True) as client:
        contratos = scrape_vida(client, args.limit, args.delay)
        if not contratos:
            log.error("No se obtuvieron contratos. Revisa el log.")
            sys.exit(1)
        write_outputs(contratos, out_dir)
        if args.pdfs:
            download_documents(client, [c for c in contratos if c["match"]],
                               Path("pdfs"), args.delay)

    print_summary(contratos)
    log.info("Listo.")


if __name__ == "__main__":
    main()
