#!/usr/bin/env python3
"""
Copia a ./pdfs_match/ solo los PDFs cuyos contratos hicieron match por nombre
(los de output/vida_match.csv) y arma un zip listo para compartir.

Los PDFs deben estar en ./pdfs/<Institución>/<numero_registro>/  (los que bajó
reca_scraper.py --pdfs). El match se determina por la columna numero_registro
de vida_match.csv.

Uso:
  python select_match_pdfs.py
  python select_match_pdfs.py --csv output/vida_match.csv --pdfs pdfs --out pdfs_match
"""
from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Copia los PDFs de los contratos con match.")
    ap.add_argument("--csv", default="output/vida_match.csv")
    ap.add_argument("--pdfs", default="pdfs")
    ap.add_argument("--out", default="pdfs_match")
    ap.add_argument("--no-zip", action="store_true", help="No crear el .zip.")
    args = ap.parse_args()

    csv_path, pdfs_dir, out_dir = Path(args.csv), Path(args.pdfs), Path(args.out)
    if not csv_path.exists():
        raise SystemExit(f"No encuentro {csv_path}. Corre primero el scraper.")
    if not pdfs_dir.exists():
        raise SystemExit(f"No encuentro {pdfs_dir}. Corre el scraper con --pdfs.")

    with csv_path.open(encoding="utf-8-sig") as f:
        registros = {row["numero_registro"].strip()
                     for row in csv.DictReader(f) if row.get("numero_registro")}
    print(f"Contratos con match en el CSV: {len(registros)}")

    out_dir.mkdir(parents=True, exist_ok=True)
    copiados, archivos, total = 0, 0, 0
    faltan = set(registros)
    # pdfs/<institucion>/<numreg>/
    for reg_dir in pdfs_dir.glob("*/*"):
        if not reg_dir.is_dir() or reg_dir.name not in registros:
            continue
        dest = out_dir / reg_dir.parent.name / reg_dir.name
        shutil.copytree(reg_dir, dest, dirs_exist_ok=True)
        copiados += 1
        faltan.discard(reg_dir.name)
        for p in dest.rglob("*"):
            if p.is_file():
                archivos += 1
                total += p.stat().st_size

    print(f"Carpetas copiadas: {copiados} | archivos: {archivos} | "
          f"tamaño: {total/1e6:.1f} MB")
    if faltan:
        print(f"Sin PDF descargado ({len(faltan)}): "
              f"{', '.join(sorted(faltan)[:10])}{' ...' if len(faltan) > 10 else ''}")

    if not args.no_zip and copiados:
        zip_path = shutil.make_archive(str(out_dir), "zip", root_dir=out_dir)
        print(f"\nZip listo para compartir: {zip_path} "
              f"({Path(zip_path).stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
