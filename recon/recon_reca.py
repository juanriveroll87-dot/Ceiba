#!/usr/bin/env python3
"""
Reconocimiento del portal RECA/RECAS de CONDUSEF.

Objetivo: descubrir el/los endpoint(s) (XHR/fetch) que devuelven los contratos
para poder replicarlos luego con httpx. NO scrapea nada: solo abre el portal en
un navegador real (Playwright), graba TODO el tráfico de red y vuelca:

  recon_out/network_log.json   -> cada request/response (método, URL, headers,
                                   payload, status, content-type, cuerpo si es
                                   JSON/texto, truncado).
  recon_out/xhr_endpoints.json -> solo XHR/fetch y respuestas JSON (lo relevante).
  recon_out/form_structure.json-> selects/options/forms/botones de la página
                                   (para saber qué valores mandar: sistema, ramo…).
  recon_out/page.html          -> HTML renderizado.
  recon_out/screenshot.png     -> captura.

Uso típico (en tu máquina, con red hacia CONDUSEF):

    pip install playwright
    playwright install chromium
    python recon_reca.py                 # abre navegador visible y espera
                                         # a que hagas la búsqueda a mano

Flujo recomendado:
  1. Corre el script. Se abre Chromium en el portal.
  2. Selecciona el sistema "RECAS", entra a "Búsqueda Avanzada", pon Ramo = "Vida"
     y dispara la búsqueda. Pagina un par de veces.
  3. Vuelve a la terminal y presiona ENTER. Se vuelcan los archivos.
  4. Mándame el contenido de recon_out/xhr_endpoints.json y form_structure.json.

Flags útiles:
  --url URL        portal (default: https://registros.condusef.gob.mx/reca/)
  --headless       sin ventana (no recomendado para recon manual)
  --auto           intenta el flujo RECAS/Vida automáticamente (best-effort)
  --seconds N      en vez de esperar ENTER, graba N segundos y termina
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit(
        "Falta Playwright. Instala con:\n"
        "    pip install playwright\n"
        "    playwright install chromium\n"
    )

DEFAULT_URL = "https://registros.condusef.gob.mx/reca/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
OUT = Path("recon_out")
BODY_LIMIT = 200_000  # bytes máximos de cuerpo guardado por respuesta


def looks_interesting(entry: dict) -> bool:
    """¿Es un XHR/fetch o una respuesta JSON? Eso es lo que buscamos."""
    if entry.get("resource_type") in ("xhr", "fetch"):
        return True
    ct = (entry.get("response_content_type") or "").lower()
    return "json" in ct


def main() -> None:
    ap = argparse.ArgumentParser(description="Recon de endpoints del portal RECA/RECAS.")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--auto", action="store_true",
                    help="Intenta seleccionar RECAS / Ramo=Vida automáticamente (best-effort).")
    ap.add_argument("--seconds", type=int, default=0,
                    help="Graba N segundos y termina (en vez de esperar ENTER).")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    entries: list[dict] = []
    by_request: dict[int, dict] = {}

    def on_request(request):
        entry = {
            "ts": round(time.time(), 3),
            "method": request.method,
            "url": request.url,
            "resource_type": request.resource_type,
            "request_headers": dict(request.headers),
            "post_data": None,
            "status": None,
            "response_headers": None,
            "response_content_type": None,
            "response_body": None,
            "response_body_truncated": False,
            "error": None,
        }
        try:
            entry["post_data"] = request.post_data
        except Exception:
            pass
        entries.append(entry)
        by_request[id(request)] = entry

    def on_response(response):
        entry = by_request.get(id(response.request))
        if entry is None:
            return
        try:
            entry["status"] = response.status
            headers = dict(response.headers)
            entry["response_headers"] = headers
            ct = headers.get("content-type", "")
            entry["response_content_type"] = ct
            # Solo leemos cuerpo de cosas de texto/JSON; nada de binarios grandes.
            if any(t in ct.lower() for t in ("json", "text", "javascript", "xml", "html")):
                body = response.body()
                if len(body) > BODY_LIMIT:
                    entry["response_body_truncated"] = True
                    body = body[:BODY_LIMIT]
                entry["response_body"] = body.decode("utf-8", errors="replace")
        except Exception as exc:  # respuestas a redirects, abortadas, etc.
            entry["error"] = f"{type(exc).__name__}: {exc}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(
            user_agent=UA,
            locale="es-MX",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        print(f"[recon] Navegando a {args.url}")
        try:
            page.goto(args.url, wait_until="networkidle", timeout=60_000)
        except Exception as exc:
            print(f"[recon] Aviso al cargar (continuo igual): {exc}")

        # --- Volcado de estructura del formulario para saber qué mandar luego ---
        try:
            form_structure = page.evaluate(
                """() => {
                    const selects = [...document.querySelectorAll('select')].map(s => ({
                        name: s.name, id: s.id,
                        options: [...s.options].map(o => ({value: o.value, text: o.text.trim()}))
                    }));
                    const forms = [...document.querySelectorAll('form')].map(f => ({
                        action: f.action, method: f.method, id: f.id, name: f.name
                    }));
                    const buttons = [...document.querySelectorAll('button, input[type=submit], a.btn')]
                        .map(b => ({tag: b.tagName, text: (b.innerText||b.value||'').trim(),
                                    id: b.id, onclick: b.getAttribute('onclick')}))
                        .filter(b => b.text || b.onclick);
                    return {selects, forms, buttons};
                }"""
            )
            (OUT / "form_structure.json").write_text(
                json.dumps(form_structure, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"[recon] Estructura del formulario -> {OUT/'form_structure.json'} "
                  f"({len(form_structure['selects'])} selects, "
                  f"{len(form_structure['buttons'])} botones)")
        except Exception as exc:
            print(f"[recon] No pude volcar estructura del formulario: {exc}")

        # --- Volcado del JavaScript de la app (clave para las URLs de PDFs) ---
        try:
            _dump_scripts(page, context)
        except Exception as exc:
            print(f"[recon] No pude volcar el JS: {exc}")

        # --- Intento automático best-effort (opcional) ---
        if args.auto:
            try:
                _best_effort_recas_vida(page)
            except Exception as exc:
                print(f"[recon] --auto falló (haz la búsqueda a mano): {exc}")

        # --- Espera mientras graba ---
        if args.seconds > 0:
            print(f"[recon] Grabando {args.seconds}s...")
            page.wait_for_timeout(args.seconds * 1000)
        elif not args.headless:
            print("\n>>> Haz la búsqueda en el navegador (RECAS, Ramo=Vida, pagina).")
            print(">>> Cuando termines, vuelve aquí y presiona ENTER para volcar.\n")
            try:
                input()
            except EOFError:
                page.wait_for_timeout(30_000)
        else:
            page.wait_for_timeout(15_000)

        # --- Volcado final ---
        try:
            (OUT / "page.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(OUT / "screenshot.png"), full_page=True)
        except Exception as exc:
            print(f"[recon] No pude guardar page.html/screenshot: {exc}")

        context.close()
        browser.close()

    _dump_and_summarize(entries)


def _dump_scripts(page, context) -> None:
    """Descarga todos los <script src> del mismo origen + scripts inline.

    El JS de la app contiene cómo se construyen las URLs de los documentos
    (condiciones generales, carátula, etc.), así que es la vía más fiable para
    descubrir el patrón sin depender de clics.
    """
    js_dir = OUT / "js"
    js_dir.mkdir(exist_ok=True)
    info = page.evaluate(
        """() => {
            const ext = [...document.scripts].filter(s => s.src).map(s => s.src);
            const inline = [...document.scripts].filter(s => !s.src)
                .map(s => s.textContent).filter(t => t && t.trim());
            return {ext, inline};
        }"""
    )
    saved = 0
    for url in info["ext"]:
        # Solo same-origin (los CDNs externos no nos interesan y pueden fallar).
        if "condusef.gob.mx" not in url:
            continue
        try:
            resp = context.request.get(url, timeout=30_000)
            name = url.split("/")[-1].split("?")[0] or f"script_{saved}.js"
            (js_dir / name).write_bytes(resp.body())
            saved += 1
        except Exception as exc:
            print(f"[recon]   no pude bajar {url}: {exc}")
    for i, code in enumerate(info["inline"]):
        (js_dir / f"inline_{i}.js").write_text(code, encoding="utf-8")
    print(f"[recon] JS volcado -> {js_dir}/ ({saved} externos same-origin, "
          f"{len(info['inline'])} inline). Mándame estos archivos.")


def _best_effort_recas_vida(page) -> None:
    """Intento heurístico de seleccionar RECAS y Ramo=Vida. No garantizado."""
    print("[recon] --auto: intentando seleccionar RECAS / Ramo=Vida...")
    # Click en cualquier cosa que diga RECAS
    for txt in ("RECAS", "Recas", "recas"):
        loc = page.get_by_text(txt, exact=False)
        if loc.count():
            try:
                loc.first.click(timeout=3000)
                page.wait_for_timeout(1500)
                break
            except Exception:
                pass
    # Búsqueda avanzada
    for txt in ("Búsqueda Avanzada", "Busqueda Avanzada", "Avanzada"):
        loc = page.get_by_text(txt, exact=False)
        if loc.count():
            try:
                loc.first.click(timeout=3000)
                page.wait_for_timeout(1500)
                break
            except Exception:
                pass
    # Seleccionar Vida en cualquier <select> que tenga esa opción
    for sel in page.query_selector_all("select"):
        try:
            sel.select_option(label="Vida")
            page.wait_for_timeout(800)
            print("[recon] --auto: seleccioné 'Vida' en un select.")
            break
        except Exception:
            continue
    # Disparar búsqueda
    for txt in ("Buscar", "Consultar", "Búsqueda"):
        loc = page.get_by_role("button", name=txt)
        if loc.count():
            try:
                loc.first.click(timeout=3000)
                page.wait_for_timeout(3000)
                print("[recon] --auto: disparé la búsqueda.")
                break
            except Exception:
                pass


def _dump_and_summarize(entries: list[dict]) -> None:
    (OUT / "network_log.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    interesting = [e for e in entries if looks_interesting(e)]
    (OUT / "xhr_endpoints.json").write_text(
        json.dumps(interesting, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Recursos que NO son XHR/fetch/JSON pero pueden ser documentos/PDFs
    # (al hacer clic en un contrato el PDF puede abrirse como navegación).
    docs = [
        e for e in entries
        if "condusef.gob.mx" in e["url"]
        and not looks_interesting(e)
        and (
            "pdf" in (e.get("response_content_type") or "").lower()
            or e["url"].lower().endswith(".pdf")
            or e.get("resource_type") == "document"
            or any(k in e["url"].lower()
                   for k in ("detalle", "documento", "doc", "pdf", "archivo", "file"))
        )
    ]
    (OUT / "documentos_candidatos.json").write_text(
        json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if docs:
        print(f"[recon] Posibles documentos/detalle -> documentos_candidatos.json "
              f"({len(docs)})")

    print("\n" + "=" * 70)
    print(f"RECON COMPLETO. Requests totales: {len(entries)} | "
          f"XHR/fetch/JSON: {len(interesting)}")
    print("=" * 70)
    print(f"Archivos en ./{OUT}/  (network_log.json, xhr_endpoints.json, "
          f"form_structure.json, page.html, screenshot.png)\n")

    if not interesting:
        print("No se detectaron XHR/fetch ni respuestas JSON. Si no hiciste la "
              "búsqueda, vuelve a correr y dispárala (o usa --auto).")
        return

    print("Endpoints candidatos (revisa cuál trae los contratos):\n")
    for e in interesting:
        ct = e.get("response_content_type", "")
        body = e.get("response_body") or ""
        snippet = body[:140].replace("\n", " ")
        print(f"  [{e['method']}] {e['status']}  {e['url']}")
        print(f"       type={e['resource_type']}  content-type={ct}")
        if e.get("post_data"):
            print(f"       POST data: {str(e['post_data'])[:200]}")
        if snippet:
            print(f"       body: {snippet}")
        print()


if __name__ == "__main__":
    main()
