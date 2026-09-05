#!/usr/bin/env bash
# Graba el video de respaldo de la demo inicial (ponente/demo.mp4) con la grabación de pantalla de macOS.
#
# Qué se graba (misma secuencia que ponente/DEMO_SCRIPT.md, ~2-3 min):
#   1. 00_check.py                     → banner de modo y costo acumulado
#   2. 01_texto.py $FOTO --overlay     → líneas con confianza y overlay de cajas (verde/amarillo/rojo)
#   3. open salida/<foto>.overlay.png  → la imagen con las cajas (Preview) ~6 s en pantalla
#   4. 03_inteligente.py $FOTO         → tabla de campos por origen + alertas → REVISAR
#   5. 03_inteligente.py docs/factura_limpia.png → mismo código, documento limpio → OK
#   6. 03_inteligente.py docs/factura_trampa.png → las 2 alertas de la trampa (se recorta si sobra)
#
# Antes de grabar (viernes, ver ponente/CHECKLIST.md):
#   - Terminal a 24 pt, ventana a pantalla completa, tema claro u oscuro fijo, notificaciones en "No molestar".
#   - Permitir a Terminal la "Grabación de pantalla" en Ajustes → Privacidad y seguridad (si no, screencapture graba negro).
#   - Cerrar pestañas/ventanas ajenas; solo Terminal y Preview.
#   - Por defecto TODO se ejecuta en --offline (no gasta y sale siempre igual). Para grabar con llamadas reales
#     (desde cache/ tras haber grabado fixtures): MODO=--online bash tools/grabar_demo.sh
#
# Uso:
#   bash tools/grabar_demo.sh                      # graba → ponente/demo.mp4 (o .mov si no hay ffmpeg)
#   bash tools/grabar_demo.sh --sin-grabar         # ensayo: ejecuta la secuencia con pausas, sin grabar
#   bash tools/grabar_demo.sh --solo-comandos      # imprime la secuencia y termina (para copiar/pegar)
#   PAUSA=6 bash tools/grabar_demo.sh              # segundos de pausa entre comandos (default 4)
#   SIN_ABRIR=1 PAUSA=0 bash tools/grabar_demo.sh --sin-grabar   # prueba rápida sin abrir Preview
#   bash tools/grabar_demo.sh --salida /ruta/demo.mp4
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
MODO="${MODO:---offline}"
PAUSA="${PAUSA:-4}"
DURACION_MAX="${DURACION_MAX:-240}"        # tope de la grabación en segundos (screencapture -V)
SALIDA="$RAIZ/../ponente/demo.mp4"
GRABAR=1
SOLO_COMANDOS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --sin-grabar) GRABAR=0 ;;
    --solo-comandos) SOLO_COMANDOS=1; GRABAR=0 ;;
    --salida) shift; SALIDA="$1" ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "argumento desconocido: $1 (ver --help)" >&2; exit 1 ;;
  esac
  shift
done

# Foto real si existe (la toma el ponente el sábado a T-2h); si no, la foto sintética con fixtures.
FOTO=docs/factura_foto_real.jpg
[ -f "$FOTO" ] || FOTO=docs/factura_foto.jpg
if [ "$MODO" = "--offline" ] && [ "$FOTO" = "docs/factura_foto_real.jpg" ] && [ ! -f fixtures/factura_foto_real/detect_document_text.json ]; then
  FOTO=docs/factura_foto.jpg   # en offline solo sirve la foto con fixtures grabados
fi
STEM="$(basename "${FOTO%.*}")"

# Secuencia de la demo (una línea por comando; los 'open' se saltan en --solo-comandos y en CI).
COMANDOS=(
  "python3 00_check.py $MODO"
  "python3 01_texto.py $FOTO $MODO --overlay"
  "open salida/$STEM.overlay.png"
  "python3 03_inteligente.py $FOTO $MODO"
  "python3 03_inteligente.py docs/factura_limpia.png $MODO"
  "python3 03_inteligente.py docs/factura_trampa.png $MODO"
)

if [ "$SOLO_COMANDOS" = 1 ]; then
  echo "# Secuencia de la demo (modo $MODO, foto $FOTO):"
  printf '%s\n' "${COMANDOS[@]}"
  exit 0
fi

if ! command -v python3 >/dev/null; then echo "falta python3" >&2; exit 1; fi

MOV=""
PID_GRAB=""
if [ "$GRABAR" = 1 ]; then
  if ! command -v screencapture >/dev/null; then
    echo "screencapture no está disponible (solo macOS). Graba con QuickTime → Archivo → Nueva grabación de pantalla y ejecuta: bash $0 --sin-grabar" >&2
    exit 1
  fi
  mkdir -p "$(dirname "$SALIDA")"
  MOV="${SALIDA%.*}.mov"
  rm -f "$MOV"
  echo ">> Grabando la pantalla en $MOV (máx. ${DURACION_MAX}s). Ctrl-C detiene todo."
  # -v video, -V duración máxima en segundos, -x sin sonido de obturador
  screencapture -x -v -V "$DURACION_MAX" "$MOV" &
  PID_GRAB=$!
  sleep 2
  clear
fi

detener_grabacion() {
  if [ -n "$PID_GRAB" ] && kill -0 "$PID_GRAB" 2>/dev/null; then
    kill -INT "$PID_GRAB" 2>/dev/null || true
    wait "$PID_GRAB" 2>/dev/null || true
  fi
}
trap detener_grabacion EXIT

ESTADO=0
for CMD in "${COMANDOS[@]}"; do
  printf '\n$ %s\n' "$CMD"           # simula el prompt para que se lea en el video
  sleep 1
  case "$CMD" in
    open\ *)
      ARCHIVO="${CMD#open }"
      if [ "${SIN_ABRIR:-0}" = 1 ]; then
        echo "(SIN_ABRIR=1: no se abre $ARCHIVO)"
      elif [ -f "$ARCHIVO" ] && command -v open >/dev/null; then
        open "$ARCHIVO"; sleep "$((PAUSA + 2))"
        # Volver a la terminal para seguir grabando la consola.
        osascript -e 'tell application "Terminal" to activate' >/dev/null 2>&1 || true
      else
        echo "(overlay no disponible: $ARCHIVO; ver docs/salidas/)"
      fi
      ;;
    *)
      if ! eval "$CMD"; then
        echo "!! el comando terminó con error; en la demo real: repetir con --offline"
        ESTADO=1
      fi
      ;;
  esac
  sleep "$PAUSA"
done

printf '\n$ # fin de la demo\n'
sleep 2

if [ "$GRABAR" = 1 ]; then
  detener_grabacion
  trap - EXIT
  sleep 1
  if [ ! -s "$MOV" ]; then
    echo "!! $MOV está vacío: revisa el permiso de Grabación de pantalla para Terminal" >&2
    exit 1
  fi
  if command -v ffmpeg >/dev/null; then
    ffmpeg -y -loglevel error -i "$MOV" -an -vcodec libx264 -pix_fmt yuv420p -crf 23 -movflags +faststart "$SALIDA"
    rm -f "$MOV"
    echo ">> Video listo: $SALIDA ($(du -h "$SALIDA" | cut -f1)). Verifica que reproduce y cópialo al USB."
  else
    echo ">> Sin ffmpeg: el video quedó en $MOV (QuickTime lo reproduce; exporta a .mp4 si quieres)."
  fi
fi
exit "$ESTADO"
