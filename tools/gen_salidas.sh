#!/usr/bin/env bash
# Regenera docs/salidas/ (overlays PNG, CSV y JSON validados) corriendo los labs en modo OFFLINE
# y copiando lo que dejan en salida/. No llama a AWS. Funciona desde cualquier cwd.
#
#   bash tools/gen_salidas.sh
#
# Vuelve a correrlo después de grabar fixtures reales (tools/grabar_fixtures.py) para que las salidas
# de ejemplo reflejen respuestas reales de Textract y no los fixtures sintéticos.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"
export LAB_MODO=offline NO_COLOR=1
DESTINO="docs/salidas"

rm -rf salida
echo "Lab 1 (overlays)..."
python3 01_texto.py docs/factura_limpia.png --overlay --offline > /dev/null
python3 01_texto.py docs/factura_foto.jpg --overlay --offline > /dev/null
echo "Lab 2 (CSV de tablas)..."
python3 02_formulario_tabla.py docs/factura_limpia.png --csv --offline > /dev/null
echo "Lab 4 (resumen.json + <doc>.validado.json de todos los documentos)..."
python3 04_sistema.py docs/ --offline > /dev/null
echo "Lab 3 (validado.json de las tres facturas, tal como los ve el asistente)..."
python3 03_inteligente.py docs/factura_limpia.png --offline > /dev/null
python3 03_inteligente.py docs/factura_trampa.png --offline > /dev/null
python3 03_inteligente.py docs/factura_foto.jpg --offline > /dev/null
echo "Bonus (JSON del LLM desde fixtures/bedrock)..."
python3 05_bonus_bedrock.py docs/orden_compra_prosa.png --offline --modelo haiku > /dev/null
python3 05_bonus_bedrock.py docs/factura_foto.jpg --offline --modelo nova > /dev/null

mkdir -p "$DESTINO"
find "$DESTINO" -type f ! -name README.md -delete
cp salida/*.overlay.png salida/*.csv salida/*.validado.json salida/resumen.json salida/*.bedrock.json "$DESTINO"/
echo "✔ $DESTINO regenerado:"
ls -la "$DESTINO"
