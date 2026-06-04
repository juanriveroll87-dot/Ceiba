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

# Ceiba = PROTECCIÓN PURA de continuidad de colegiatura / orfandad (vida a término;
# si el padre que paga fallece, se paga la colegiatura a la ESCUELA). Por eso:
#   - categoría 'competidor' = orfandad / colegiatura / continuidad / escuela-beneficiaria.
#   - categoría 'ahorro_edu' = seguros educativos de AHORRO/dotal -> NO compiten con Ceiba.
#   - 'deudor'/'generic' = contexto.
# term -> (peso, categoría).
DEFAULT_TERMS = {
    # --- competidor directo: orfandad / continuidad de colegiatura (protección) ---
    "orfandad": (6, "competidor"), "huerfan": (6, "competidor"),
    "continuidad de estudios": (6, "competidor"),
    "continuidad educativa": (6, "competidor"),
    "colegiatura": (5, "competidor"), "colegiaturas": (5, "competidor"),
    "institucion educativa": (5, "competidor"), "plantel": (4, "competidor"),
    "ciclo escolar": (4, "competidor"), "matricula": (3, "competidor"),
    "ayuda para educacion": (4, "competidor"), "ayuda educativa": (4, "competidor"),
    "gastos educativos": (3, "competidor"), "beca": (3, "competidor"),
    "becari": (3, "competidor"), "escuela": (3, "competidor"),
    "colegio": (3, "competidor"), "escolar": (2, "competidor"),
    "estudiantil": (2, "competidor"), "inscripcion": (1, "competidor"),
    # --- seguro educativo de AHORRO (NO compite con Ceiba) -> bandera ---
    "dotal": (2, "ahorro_edu"), "meta educacional": (2, "ahorro_edu"),
    "valor en efectivo": (1, "ahorro_edu"), "primas programadas": (1, "ahorro_edu"),
    "supervivencia": (1, "ahorro_edu"), "ahorro": (1, "ahorro_edu"),
    "educacion profesional": (1, "ahorro_edu"),
    # --- contexto ---
    "deudor": (1, "deudor"),
    "educac": (1, "generic"), "menores": (1, "generic"), "hijos": (1, "generic"),
}
CATS = ("competidor", "ahorro_edu", "deudor", "generic")


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
                    help="competidor_score mínimo para el shortlist (default 1).")
    ap.add_argument("--pages", type=int, default=60, help="Páginas a leer por PDF.")
    ap.add_argument("--terms", default="", help="Override de términos (coma).")
    ap.add_argument("--no-zip", action="store_true")
    args = ap.parse_args()

    pdfs_dir = Path(args.pdfs)
    if not pdfs_dir.exists():
        raise SystemExit(f"No encuentro {pdfs_dir}.")

    # term -> (peso, categoria). Con --terms, todos entran como 'competidor'.
    if args.terms.strip():
        terms = {normalize(t): (1, "competidor") for t in args.terms.split(",") if t.strip()}
    else:
        terms = {normalize(k): v for k, v in DEFAULT_TERMS.items()}

    files = sorted(pdfs_dir.glob("*/*/*.pdf"))
    print(f"PDFs a analizar: {len(files)}")

    rows = []
    for i, path in enumerate(files, 1):
        numreg = path.parent.name
        institucion = path.parent.parent.name
        text = normalize(extract_text(path, args.pages))
        cat_score = {c: 0 for c in CATS}
        comp_hits, otros_hits, snippet = [], [], ""
        for term, (weight, cat) in terms.items():
            n = text.count(term)
            if not n:
                continue
            cat_score[cat] += n * weight
            (comp_hits if cat == "competidor" else otros_hits).append(f"{term}({n})")
            if cat == "competidor" and not snippet:
                pos = text.find(term)
                snippet = text[max(0, pos - 70): pos + 100].strip()
        rows.append({
            "institucion": institucion,
            "numero_registro": numreg,
            "archivo": path.name,
            "competidor_score": cat_score["competidor"],
            "ahorro_edu_score": cat_score["ahorro_edu"],
            "deudor_score": cat_score["deudor"],
            "terminos_competidor": "; ".join(comp_hits),
            "terminos_otros": "; ".join(otros_hits),
            "fragmento": snippet,
            "_path": path,
        })
        if i % 25 == 0:
            print(f"  {i}/{len(files)}")

    # Ordena por señal de COMPETIDOR (orfandad/colegiatura); a igualdad, menos ahorro.
    rows.sort(key=lambda r: (r["competidor_score"], -r["ahorro_edu_score"]), reverse=True)
    fields = ["institucion", "numero_registro", "archivo", "competidor_score",
              "ahorro_edu_score", "deudor_score", "terminos_competidor",
              "terminos_otros", "fragmento"]
    with open(args.out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in fields})

    con_score = [r for r in rows if r["competidor_score"] >= args.min_score]
    print(f"\nRanking -> {args.out_csv}")
    print(f"Con competidor_score >= {args.min_score}: {len(con_score)} PDFs")
    print("\nTop 20 por señal de competidor (orfandad/colegiatura, protección):")
    for r in rows[:20]:
        if r["competidor_score"] == 0:
            break
        flag = "  (¿AHORRO?)" if r["ahorro_edu_score"] >= r["competidor_score"] else ""
        print(f"  comp={r['competidor_score']:3d} ahorro={r['ahorro_edu_score']:3d}  "
              f"{r['numero_registro']:18}  {r['institucion'][:24]:24}  "
              f"{r['terminos_competidor'][:45]}{flag}")

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
