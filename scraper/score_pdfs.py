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

# Términos de CONTENIDO (normalizados, sin acentos). Peso por relevancia para Ceiba.
DEFAULT_TERMS = {
    "orfandad": 5, "huerfan": 5, "renta educativa": 5, "beca": 3, "becari": 3,
    "colegiatura": 4, "continuidad de estudios": 5, "continuidad educativa": 5,
    "gastos de educacion": 4, "educac": 2, "escolar": 3, "estudiantil": 3,
    "supervivencia": 3, "menores": 1, "hijos": 1, "deudor": 1,
}


def normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", t)


def extract_text(path: Path, max_pages: int) -> str:
    try:
        from pypdf import PdfReader  # import perezoso: solo se necesita al leer PDFs
    except ImportError:
        raise SystemExit("Falta pypdf. Instala con:  pip install pypdf")
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        print(f"  ! no pude abrir {path.name}: {exc}")
        return ""
    parts = []
    for page in reader.pages[:max_pages]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


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

    if args.terms.strip():
        terms = {normalize(t): 1 for t in args.terms.split(",") if t.strip()}
    else:
        terms = {normalize(k): v for k, v in DEFAULT_TERMS.items()}

    files = sorted(pdfs_dir.glob("*/*/*.pdf"))
    print(f"PDFs a analizar: {len(files)}")

    rows = []
    for i, path in enumerate(files, 1):
        numreg = path.parent.name
        institucion = path.parent.parent.name
        text = normalize(extract_text(path, args.pages))
        score, hits, snippet = 0, [], ""
        for term, weight in terms.items():
            n = text.count(term)
            if n:
                score += n * weight
                hits.append(f"{term}({n})")
                if not snippet:
                    pos = text.find(term)
                    snippet = text[max(0, pos - 60): pos + 80].strip()
        rows.append({
            "institucion": institucion,
            "numero_registro": numreg,
            "archivo": path.name,
            "score": score,
            "terminos": "; ".join(hits),
            "fragmento": snippet,
            "_path": path,
        })
        if i % 25 == 0:
            print(f"  {i}/{len(files)}")

    rows.sort(key=lambda r: r["score"], reverse=True)
    with open(args.out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["institucion", "numero_registro", "archivo",
                                          "score", "terminos", "fragmento"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in w.fieldnames})

    con_score = [r for r in rows if r["score"] >= args.min_score]
    print(f"\nRanking -> {args.out_csv}")
    print(f"Con score >= {args.min_score}: {len(con_score)} PDFs")
    print("\nTop 15:")
    for r in rows[:15]:
        print(f"  {r['score']:4d}  {r['numero_registro']:20}  "
              f"{r['institucion'][:30]:30}  {r['terminos'][:60]}")

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
