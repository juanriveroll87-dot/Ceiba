#!/usr/bin/env python3
"""
Scraper del RECAS (Registro de Contratos de Adhesión de Seguros) de CONDUSEF.

Usa la API JSON + las "tarjetas" HTML descubiertas en el reconocimiento
(ver ../recon):

  GET  get_options.php?sector=recas&type=ramos|instituciones      -> catálogos
  GET  busqueda.php?sector=recas&search_type=advanced&ramo=<R>&page=&limit=
                                                                   -> contratos (JSON)
  GET  tarjeta_recas.php?numreg=<NUMREG>                          -> detalle (HTML):
                                                                      estatus, CNSF,
                                                                      documentos
  POST openfilesecure.php  (file=<token>)                         -> PDF del documento

No existe un ramo "Vida" único: el scraper enumera TODOS los ramos que contienen
"vida" (sin acentos/mayúsculas: Vida-Grupo, Vida-Individual y combinaciones),
pagina cada uno y deduplica por número de registro.

Salidas en ./output:
  vida_contratos.json   -> todos los contratos de Vida con sus campos (+documentos)
  vida_contratos.csv    -> idem en CSV
  vida_match.csv        -> solo los que hicieron match con los términos objetivo
  scraper.log           -> log de ejecución

Términos objetivo (orfandad / continuidad educativa / deudores): se marcan en la
columna booleana `match` y se listan en `matched_terms`.

Documentos / PDFs (opcional):
  Los PDFs se sirven por POST a openfilesecure.php con un token cifrado que vive en
  la tarjeta. Para obtenerlos hay que pedir la tarjeta de cada contrato (1 request
  por contrato), por eso el enriquecimiento es opt-in:

    --enrich none   (default) solo listado, rápido
    --enrich match            pide la tarjeta solo de los contratos con match
    --enrich all              pide la tarjeta de todos (lento: 1 req/contrato)

    --pdfs                    descarga PDFs de los contratos con match a
                              ./pdfs/<Institución>/<numreg>/  (implica enrich=match)
    --pdf-types "condiciones generales"   tipos a bajar (coma) o "all"

Uso:
  pip install -r requirements.txt
  python reca_scraper.py
  python reca_scraper.py --pdfs
  python reca_scraper.py --enrich all
"""

import argparse
import csv
import json
import logging
import random
import re
import sys
import time
import unicodedata
from pathlib import Path

try:
    import httpx
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Faltan dependencias. Instala con:  pip install -r requirements.txt")

BASE = "https://registros.condusef.gob.mx/reca"
SECTOR = "recas"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/json,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
    "Referer": f"{BASE}/",
}

# Términos a marcar (orfandad / continuidad educativa / Vida Grupo Deudores).
TARGET_TERMS = [
    "orfandad", "escolar", "educativ", "beca",
    "colegiatura", "estudia", "deudores", "continuidad",
]

# Posiciones de columnas en cada fila de busqueda.php -> data[]
# [idx, sistema, institucion, ramo-modalidad, nombre_comercial, num_registro, id_actualizacion]
C_IDX, C_SISTEMA, C_INSTITUCION, C_RAMO, C_NOMBRE, C_REGISTRO, C_IDACT = range(7)

# Tipos de documento -> columna doc_* (por palabra clave normalizada)
DOC_COL_KEYS = {
    "condiciones_generales": ("condiciones generales",),
    "caratula": ("caratula",),
    "solicitud": ("solicitud",),
    "endosos": ("endoso",),
}

MAX_RETRIES = 4
log = logging.getLogger("reca")


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def normalize(text: str) -> str:
    """minúsculas + sin acentos, para comparar de forma robusta."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def match_terms(*fields: str) -> list[str]:
    blob = normalize(" ".join(f for f in fields if f))
    return [t for t in TARGET_TERMS if t in blob]


def doc_key(tipo: str) -> str | None:
    """Clasifica el nombre de un documento en una de las columnas doc_*."""
    n = normalize(tipo)
    for key, needles in DOC_COL_KEYS.items():
        if any(needle in n for needle in needles):
            return key
    return None


def safe_name(text: str, maxlen: int = 120) -> str:
    """Nombre de archivo/carpeta seguro."""
    text = (text or "").strip()
    text = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text or "sin_nombre")[:maxlen]


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
# HTTP con reintentos y backoff exponencial
# --------------------------------------------------------------------------- #
def request(client: httpx.Client, method: str, url: str,
            delay: float, **kwargs) -> httpx.Response | None:
    """Request con reintentos (backoff 2,4,8,16s) y pausa cortés con jitter."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = client.request(method, url, timeout=45, **kwargs)
            r.raise_for_status()
            time.sleep(delay + random.uniform(0, 0.5))
            return r
        except httpx.HTTPError as exc:
            wait = 2 ** attempt
            log.warning("Intento %d/%d falló %s %s: %s (espero %ds)",
                        attempt, MAX_RETRIES, method, url, exc, wait)
            if attempt < MAX_RETRIES:
                time.sleep(wait)
    log.error("Agoté reintentos para %s %s", method, url)
    return None


def get_json(client, path, params, delay) -> dict | None:
    r = request(client, "GET", f"{BASE}/{path}", delay, params=params)
    if r is None:
        return None
    try:
        return r.json()
    except json.JSONDecodeError as exc:
        log.error("JSON inválido en %s %s: %s", path, params, exc)
        return None


# --------------------------------------------------------------------------- #
# Catálogos y listado
# --------------------------------------------------------------------------- #
def fetch_options(client, tipo, delay) -> list[str]:
    data = get_json(client, "get_options.php", {"sector": SECTOR, "type": tipo}, delay)
    if not data or not data.get("success"):
        log.error("No pude obtener el catálogo '%s'", tipo)
        return []
    return [item["id"] for item in data.get("data", [])]


def vida_ramos(all_ramos: list[str]) -> list[str]:
    return [r for r in all_ramos if "vida" in normalize(r)]


def row_to_contract(row: list, ramo_consulta: str) -> dict:
    def g(i):
        return row[i] if i < len(row) else None

    ramo_completo = g(C_RAMO) or ""
    nombre = g(C_NOMBRE) or ""
    ramo_base, _, producto = ramo_completo.partition(" - ")
    hits = match_terms(ramo_completo, nombre)
    return {
        "sistema": g(C_SISTEMA),
        "institucion": g(C_INSTITUCION),
        "ramo": ramo_base.strip(),
        "producto": producto.strip(),
        "ramo_completo": ramo_completo,
        "nombre_comercial": nombre,
        "numero_registro": g(C_REGISTRO),
        "ramo_consulta": ramo_consulta,
        "match": bool(hits),
        "matched_terms": ";".join(hits),
        # Se llenan al enriquecer con la tarjeta:
        "estatus": "",
        "cnsf": "",
        "documentos": [],
        "doc_condiciones_generales": "",
        "doc_caratula": "",
        "doc_solicitud": "",
        "doc_endosos": "",
    }


def fetch_ramo(client, ramo, limit, delay) -> list[dict]:
    out, page = [], 1
    while True:
        data = get_json(client, "busqueda.php", {
            "sector": SECTOR, "search_type": "advanced",
            "ramo": ramo, "page": page, "limit": limit,
        }, delay)
        if not data or not data.get("success"):
            log.warning("Ramo '%s' pág %d sin datos; corto.", ramo, page)
            break
        rows = data.get("data") or []
        out.extend(row_to_contract(r, ramo) for r in rows)
        total_pages = data.get("total_pages") or 1
        if page == 1:
            log.info("Ramo '%s': total=%s, páginas=%s",
                     ramo, data.get("total"), total_pages)
        if page >= total_pages or not rows:
            break
        page += 1
    return out


def scrape_vida(client, limit, delay) -> list[dict]:
    objetivo = vida_ramos(fetch_options(client, "ramos", delay))
    log.info("Ramos de Vida a consultar: %d", len(objetivo))
    contratos: dict[str, dict] = {}
    anon = 0
    for ramo in objetivo:
        for c in fetch_ramo(client, ramo, limit, delay):
            key = c["numero_registro"]
            if not key:
                key, anon = f"__anon_{anon}", anon + 1
            contratos.setdefault(key, c)
    return list(contratos.values())


# --------------------------------------------------------------------------- #
# Tarjeta (detalle): estatus, CNSF y documentos
# --------------------------------------------------------------------------- #
def parse_tarjeta(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    info = {"estatus": "", "cnsf": "", "documentos": []}

    # Estatus (p. ej. "Vigente")
    for h5 in soup.find_all("h5"):
        if normalize(h5.get_text()) == "estatus":
            p = h5.find_next("p")
            if p:
                info["estatus"] = p.get_text(strip=True)
            break

    m = re.search(r"CNSF:\s*<strong>([^<]+)</strong>", html)
    if m:
        info["cnsf"] = m.group(1).strip()

    table = soup.find("table", class_="documents-table")
    if table:
        for tr in table.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            inp = tr.find("input", attrs={"name": "file"})
            if not inp or not inp.get("value"):
                continue
            btn = tr.find("button")
            info["documentos"].append({
                "tipo": tds[1].get_text(strip=True),
                "archivo": (btn.get("title") if btn else "").strip(),
                "token": inp["value"],
            })
    return info


def enrich_contract(client, c, delay) -> None:
    """Pide la tarjeta del contrato y rellena estatus/cnsf/documentos."""
    numreg = c["numero_registro"]
    if not numreg:
        return
    r = request(client, "GET", f"{BASE}/tarjeta_recas.php",
                delay, params={"numreg": numreg})
    if r is None:
        return
    info = parse_tarjeta(r.text)
    c["estatus"] = info["estatus"]
    c["cnsf"] = info["cnsf"]
    c["documentos"] = info["documentos"]
    for d in info["documentos"]:
        key = doc_key(d["tipo"])
        if key and not c[f"doc_{key}"]:
            c[f"doc_{key}"] = d["token"]


# --------------------------------------------------------------------------- #
# Descarga de PDFs (POST openfilesecure.php con el token)
# --------------------------------------------------------------------------- #
def download_documents(client, contratos, pdf_types, delay,
                       pdf_dir=Path("pdfs")) -> int:
    """Descarga los PDFs solicitados a ./pdfs/<Institución>/<numreg>/."""
    want_all = "all" in pdf_types
    bajados = 0
    for c in contratos:
        if not c["documentos"]:
            continue
        numreg = c["numero_registro"] or "sin_registro"
        dest = pdf_dir / safe_name(c["institucion"] or "SIN_INSTITUCION") / safe_name(numreg)
        referer = f"{BASE}/tarjeta_recas.php?numreg={numreg}"
        for i, d in enumerate(c["documentos"], 1):
            key = doc_key(d["tipo"])
            if not want_all and (key is None or key not in pdf_types):
                continue
            r = request(client, "POST", f"{BASE}/openfilesecure.php", delay,
                        data={"file": d["token"]},
                        headers={"Referer": referer,
                                 "Content-Type": "application/x-www-form-urlencoded"})
            if r is None:
                continue
            body = r.content
            ctype = r.headers.get("content-type", "").lower()
            if "pdf" not in ctype and not body[:5].startswith(b"%PDF"):
                log.warning("No es PDF (%s) para %s / %s; omito.",
                            ctype, numreg, d["tipo"])
                continue
            dest.mkdir(parents=True, exist_ok=True)
            fname = safe_name(d["archivo"] or f"{i}_{key or 'documento'}.pdf")
            if not fname.lower().endswith(".pdf"):
                fname += ".pdf"
            (dest / fname).write_bytes(body)
            bajados += 1
            log.info("PDF guardado: %s", dest / fname)
    log.info("Descarga de PDFs completa: %d archivos.", bajados)
    return bajados


# --------------------------------------------------------------------------- #
# Salidas
# --------------------------------------------------------------------------- #
CSV_FIELDS = [
    "sistema", "institucion", "ramo", "producto", "ramo_completo",
    "nombre_comercial", "numero_registro", "cnsf", "estatus", "ramo_consulta",
    "match", "matched_terms",
    "doc_condiciones_generales", "doc_caratula", "doc_solicitud", "doc_endosos",
]


def write_outputs(contratos, out_dir: Path) -> None:
    (out_dir / "vida_contratos.json").write_text(
        json.dumps(contratos, ensure_ascii=False, indent=2), encoding="utf-8")

    def dump_csv(path, rows):
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    dump_csv(out_dir / "vida_contratos.csv", contratos)
    matched = [c for c in contratos if c["match"]]
    dump_csv(out_dir / "vida_match.csv", matched)
    log.info("Escritos: vida_contratos.json/csv (%d) y vida_match.csv (%d)",
             len(contratos), len(matched))


def print_summary(contratos) -> None:
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
        tc: dict[str, int] = {}
        for c in matched:
            for t in filter(None, c["matched_terms"].split(";")):
                tc[t] = tc.get(t, 0) + 1
        print("Términos con match         : " +
              ", ".join(f"{t}={n}" for t, n in sorted(tc.items(), key=lambda x: -x[1])))
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
    ap.add_argument("--enrich", choices=["none", "match", "all"], default="none",
                    help="Pedir la tarjeta para añadir estatus/CNSF/documentos.")
    ap.add_argument("--pdfs", action="store_true",
                    help="Descargar PDFs de los contratos con match (implica enrich=match).")
    ap.add_argument("--pdf-types", default="condiciones generales",
                    help='Tipos de documento a bajar (coma) o "all". '
                         'Claves: condiciones generales, caratula, solicitud, endosos.')
    args = ap.parse_args()

    out_dir = Path(args.out)
    setup_logging(out_dir)

    enrich = args.enrich
    if args.pdfs and enrich == "none":
        enrich = "match"
    log.info("Scraper RECAS/Vida | limit=%d delay=%.1fs enrich=%s pdfs=%s",
             args.limit, args.delay, enrich, args.pdfs)

    with httpx.Client(headers=HEADERS, follow_redirects=True) as client:
        contratos = scrape_vida(client, args.limit, args.delay)
        if not contratos:
            log.error("No se obtuvieron contratos. Revisa el log.")
            sys.exit(1)

        if enrich != "none":
            objetivo = [c for c in contratos if enrich == "all" or c["match"]]
            log.info("Enriqueciendo %d contratos con su tarjeta...", len(objetivo))
            for i, c in enumerate(objetivo, 1):
                enrich_contract(client, c, args.delay)
                if i % 25 == 0:
                    log.info("  tarjetas: %d/%d", i, len(objetivo))

        write_outputs(contratos, out_dir)

        if args.pdfs:
            pdf_types = {normalize(t).strip().replace(" ", "_")
                         for t in args.pdf_types.split(",")}
            # normaliza "condiciones generales" -> "condiciones_generales"
            pdf_types = {"all"} if "all" in pdf_types else pdf_types
            objetivo = [c for c in contratos if c["match"]]
            log.info("Descargando PDFs (%s) de %d contratos con match...",
                     args.pdf_types, len(objetivo))
            download_documents(client, objetivo, pdf_types, args.delay)

    print_summary(contratos)
    log.info("Listo.")


if __name__ == "__main__":
    main()
