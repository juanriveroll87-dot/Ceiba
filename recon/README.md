# Recon del portal RECA/RECAS (CONDUSEF)

**Paso 1 del proyecto**: descubrir el endpoint (XHR/fetch) que devuelve los
contratos, para luego replicarlo con `httpx` (vía rápida) o, si no hay endpoint
limpio, raspar con Playwright (fallback).

> ⚠️ Este script **debe correrse en una máquina con acceso de red a
> `registros.condusef.gob.mx`** (p. ej. tu laptop). El entorno de Claude Code en
> la web tiene una *allowlist* de egress que bloquea ese host (`Host not in
> allowlist`), por eso el reconocimiento en vivo no puede hacerse desde ahí.

## Instalación

```bash
cd recon
pip install -r requirements.txt
playwright install chromium
```

## Uso

```bash
python recon_reca.py
```

1. Se abre Chromium en el portal RECA.
2. En el navegador: selecciona el sistema **RECAS** → **Búsqueda Avanzada** →
   **Ramo = "Vida"** → dispara la búsqueda. Pagina 1–2 veces.
3. Vuelve a la terminal y presiona **ENTER**.
4. Se generan los archivos en `recon_out/`.

### Variantes

```bash
python recon_reca.py --auto          # intenta el flujo RECAS/Vida solo (best-effort)
python recon_reca.py --seconds 60    # graba 60s y termina (sin esperar ENTER)
python recon_reca.py --headless      # sin ventana
```

## Qué generar y mandarme

De la carpeta `recon_out/`, mándame especialmente:

- **`xhr_endpoints.json`** → los XHR/fetch y respuestas JSON detectadas (aquí
  debe estar el endpoint de contratos: método, URL, headers, payload, cuerpo).
- **`form_structure.json`** → los `<select>` y sus opciones (valores de
  `sistema`, `ramo`, instituciones, etc.) que el scraper necesitará mandar.

Con eso valido el enfoque y escribo el scraper completo (httpx + fallback
Playwright, CSV/JSON, match de términos y descarga de PDFs).
