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

- **`recon_out/js/`** → todo el JavaScript de la app (lo descarga solo). **Aquí
  está cómo se construyen las URLs de los PDFs / el endpoint de detalle.** Es lo
  más importante para habilitar la descarga de documentos.
- **`documentos_candidatos.json`** → recursos no-XHR que parecen documentos/PDFs
  o detalle (por si al hacer clic en un contrato se abre un PDF).
- `xhr_endpoints.json` → XHR/fetch y respuestas JSON (endpoint de contratos).
- `form_structure.json` → `<select>` y sus opciones.

### Para cazar las URLs de documentos

Al correr el recon, además de la búsqueda, **haz clic en un contrato** para abrir
su detalle y, si aparecen, **haz clic en un documento** (condiciones generales).
El JS volcado en `recon_out/js/` normalmente ya revela el patrón aunque no hagas
clic, pero el clic ayuda a confirmarlo.
