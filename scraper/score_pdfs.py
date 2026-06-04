#!/usr/bin/env python3
"""
Lee TODOS los PDFs en ./pdfs/, extrae su texto y puntúa cada documento por
señales de contenido relacionadas con orfandad / continuidad educativa (lo que
compite con Ceiba). Sirve para cazar competidores que el NOMBRE no delata.

Salidas:
  pdf_scores.csv   -> ranking: institucion, numero_registro, archivo, score,
                      terminos (con conteos), fragmento de contexto
  ./pdfs_shortlist/ -> copia de los PDFs con score >= --min-score (+ zip)

Uso:
  pip install pypdf
  python score_pdfs.py
  python score_pdfs.py --min-score 2 --pages 25
  python score_pdfs.py --terms "orfandad,huerfano,beca,colegiatura,continuidad de estudios"

Nota: la extracción de texto de PDFs no es perfecta (PDFs escaneados como imagen
no traen texto). Esos saldrán con score 0; conviene revisarlos aparte si su
nombre/ramo es sospechoso.
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import unicodedata
from pathlib import Path

# Términos de CONTENIDO con (peso, categoría). La categoría 'edu' es la que de
# verdad indica competencia con Ceiba (orfandad / continuidad educativa); las
# otras ('deudor', 'ahorro', 'generic') se reportan pero NO inflan el edu_score.
DEFAULT_TERMS = {
    # --- orfandad / continuidad educativa (lo central para Ceiba) ---
    "orfandad": (6, "edu"), "huerfan": (6, "edu"),
    "renta educativa": (6, "edu"), "continuidad de estudios": (6, "edu"),
    "continuidad educativa": (6, "edu"), "ayuda para educacion": (5, "edu"),
    "ayuda educativa": (5, "edu"), "meta educacional": (5, "edu"),
    "educacion profesional": (4, "edu"), "plazo de pago educativo": (4, "edu"),
    "gastos educativos": (4, "edu"), "gasto educativo": (4, "edu"),
    "colegiatura": (4, "edu"), "beca": (4, "edu"), "becari": (4, "edu"),
    "seguro educativo": (4, "edu"), "escolar": (3, "edu"),
    "estudiantil": (3, "edu"), "educativ": (2, "edu"), "dotal": (2, "edu"),
    "educac": (1, "edu"),   # peso bajo: aparece en "Secretaría de Educación Pública"
    # --- contexto: otros segmentos (no son competencia de orfandad) ---
    "deudor": (1, "deudor"),
    "supervivencia": (1, "ahorro"), "ahorro": (1, "ahorro"),
    "menores": (1, "generic"), "hijos": (1, "generic"),
}


def normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", t)


def extract_text(path: Path, max_pages: int) -> str:
    try:
        from pypdf import PdfReader  # import perezoso: solo se necesita al leer PDFs
    except ImportError:
        raise SystemExit(
            "Falta pypdf. Instala con:  pip install pypdf cryptography")
    try:
        reader = PdfReader(str(path))
        # Los PDFs de CONDUSEF suelen venir cifrados (AES) con contraseña vacía.
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                print(f"  ! cifrado, no pude descifrar {path.name}: {exc} "
                      f"(¿falta 'pip install cryptography'?)")
                return ""
        parts = []
        for page in reader.pages[:max_pages]:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(parts)
    except Exception as exc:
        print(f"  ! no pude leer {path.name}: {exc}")
        return ""


def main() -> None:
    ap = argparse.ArgumentParser(description="Puntúa PDFs por contenido (orfandad/educación).")
    ap.add_argument("--pdfs", default="pdfs")
    ap.add_argument("--out-csv", default="pdf_scores.csv")
    ap.add_argument("--shortlist", default="pdfs_shortlist")
    ap.add_argument("--min-score", type=int, default=1,
                    help="Score mínimo para entrar al shortlist (default 1).")
    ap.add_argument("--pages", type=int, default=30, help="Páginas a leer por PDF.")
    ap.add_argument("--terms", default="", help="Override de términos (coma).")
    ap.add_argument("--no-zip", action="store_true")
    args = ap.parse_args()

    pdfs_dir = Path(args.pdfs)
    if not pdfs_dir.exists():
        raise SystemExit(f"No encuentro {pdfs_dir}.")

    # term -> (peso, categoria). Con --terms, todos entran como categoría 'edu'.
    if args.terms.strip():
        terms = {normalize(t): (1, "edu") for t in args.terms.split(",") if t.strip()}
    else:
        terms = {normalize(k): v for k, v in DEFAULT_TERMS.items()}

    files = sorted(pdfs_dir.glob("*/*/*.pdf"))
    print(f"PDFs a analizar: {len(files)}")

    rows = []
    for i, path in enumerate(files, 1):
        numreg = path.parent.name
        institucion = path.parent.parent.name
        text = normalize(extract_text(path, args.pages))
        # Ruido: "educación pública" / "secretaría de educación" no es cobertura educativa.
        noise = sum(text.count(p) for p in (
            "educacion publica", "secretaria de educacion",
            "direccion general de profesiones"))
        cat_score = {"edu": 0, "deudor": 0, "ahorro": 0, "generic": 0}
        edu_hits, ctx_hits, snippet = [], [], ""
        for term, (weight, cat) in terms.items():
            n = text.count(term)
            if term == "educac":
                n = max(0, n - noise)   # descuenta menciones a la SEP
            if not n:
                continue
            cat_score[cat] += n * weight
            (edu_hits if cat == "edu" else ctx_hits).append(f"{term}({n})")
            if cat == "edu" and not snippet:
                pos = text.find(term)
                snippet = text[max(0, pos - 60): pos + 90].strip()
        rows.append({
            "institucion": institucion,
            "numero_registro": numreg,
            "archivo": path.name,
            "edu_score": cat_score["edu"],
            "deudor_score": cat_score["deudor"],
            "ahorro_score": cat_score["ahorro"],
            "terminos_edu": "; ".join(edu_hits),
            "terminos_contexto": "; ".join(ctx_hits),
            "fragmento": snippet,
            "_path": path,
        })
        if i % 25 == 0:
            print(f"  {i}/{len(files)}")

    # Ordena por relevancia educativa (lo que compite con Ceiba), luego deudor.
    rows.sort(key=lambda r: (r["edu_score"], r["deudor_score"]), reverse=True)
    fields = ["institucion", "numero_registro", "archivo", "edu_score",
              "deudor_score", "ahorro_score", "terminos_edu",
              "terminos_contexto", "fragmento"]
    with open(args.out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in fields})

    con_score = [r for r in rows if r["edu_score"] >= args.min_score]
    print(f"\nRanking -> {args.out_csv}")
    print(f"Con edu_score >= {args.min_score}: {len(con_score)} PDFs")
    print("\nTop 20 por relevancia educativa:")
    for r in rows[:20]:
        if r["edu_score"] == 0:
            break
        print(f"  edu={r['edu_score']:3d}  {r['numero_registro']:20}  "
              f"{r['institucion'][:28]:28}  {r['terminos_edu'][:55]}")

    # Copia el shortlist + zip
    short = Path(args.shortlist)
    short.mkdir(parents=True, exist_ok=True)
    for r in con_score:
        dest = short / r["institucion"] / r["numero_registro"]
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(r["_path"], dest / r["archivo"])
    if con_score:
        print(f"\nShortlist copiado a ./{short}/ ({len(con_score)} PDFs)")
        if not args.no_zip:
            zip_path = shutil.make_archive(str(short), "zip", root_dir=short)
            print(f"Zip listo para compartir: {zip_path} "
                  f"({Path(zip_path).stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
