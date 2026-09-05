#!/usr/bin/env bash
# setup_cloudshell.sh — preparación del taller en AWS CloudShell (us-east-1).
#
# Uso (desde la raíz del repo, dentro de CloudShell):
#   bash scripts/setup_cloudshell.sh                 # verifica, instala Pillow (opcional) y corre 00_check.py
#   bash scripts/setup_cloudshell.sh --sin-pillow    # no intenta instalar Pillow
#   bash scripts/setup_cloudshell.sh --solo-verificar # solo imprime versiones, no instala ni ejecuta labs
#
# CloudShell ya trae Python 3, pip, boto3 y git; hereda las credenciales de tu sesión de consola.
# Este script NO configura credenciales ni instala nada obligatorio: boto3 es la única dependencia.
set -u

INSTALAR_PILLOW=1
SOLO_VERIFICAR=0
for arg in "$@"; do
  case "$arg" in
    --sin-pillow) INSTALAR_PILLOW=0 ;;
    --solo-verificar) SOLO_VERIFICAR=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *) echo "argumento desconocido: $arg (usa --sin-pillow o --solo-verificar)"; exit 1 ;;
  esac
done

# Colores (respetan NO_COLOR)
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  VERDE=$'\033[32m'; AMARILLO=$'\033[33m'; ROJO=$'\033[31m'; RESET=$'\033[0m'
else
  VERDE=""; AMARILLO=""; ROJO=""; RESET=""
fi
ok()    { printf '%s✔ %s%s\n' "$VERDE" "$1" "$RESET"; }
aviso() { printf '%s! %s%s\n' "$AMARILLO" "$1" "$RESET"; }
error() { printf '%s✘ %s%s\n' "$ROJO" "$1" "$RESET"; }

# Nos movemos a la raíz del repo (el directorio padre de scripts/)
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ" || { error "no pude entrar a $RAIZ"; exit 1; }
echo "Raíz del repo: $RAIZ"

FALLOS=0

# 1. Python >= 3.10
if command -v python3 >/dev/null 2>&1; then
  VERSION_PY="$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
  if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    ok "python3 $VERSION_PY"
  else
    error "python3 $VERSION_PY es menor que 3.10 (boto3 ya no soporta 3.9). Prueba python3.11 o usa otra máquina."
    FALLOS=$((FALLOS + 1))
  fi
else
  error "python3 no está en el PATH"
  FALLOS=$((FALLOS + 1))
fi

# 2. boto3 (obligatorio en modo online; en offline el helper lo tolera ausente)
if python3 -c 'import boto3' >/dev/null 2>&1; then
  ok "boto3 $(python3 -c 'import boto3; print(boto3.__version__)')"
else
  aviso "boto3 no está instalado. En CloudShell debería venir preinstalado; puedes instalarlo con: python3 -m pip install --user boto3"
  aviso "Sin boto3 solo funciona el modo offline (python3 00_check.py --offline)."
fi

# 3. git (solo informativo: si estás leyendo esto ya clonaste el repo)
if command -v git >/dev/null 2>&1; then
  ok "git $(git --version | awk '{print $3}')"
else
  aviso "git no está en el PATH (no es necesario si ya tienes el repo descomprimido)"
fi

# 4. Región y credenciales (solo informativo; boto3 decide)
echo "AWS_REGION=${AWS_REGION:-<no definida>}  AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-<no definida>}  AWS_PROFILE=${AWS_PROFILE:-<no definido>}"
echo "El laboratorio siempre llama a Textract en us-east-1 (LAB_REGION para cambiarla); tu región de CloudShell no importa."

if [ "$SOLO_VERIFICAR" -eq 1 ]; then
  [ "$FALLOS" -eq 0 ] && ok "verificación terminada" || error "verificación con $FALLOS problema(s)"
  exit "$FALLOS"
fi

# 5. Pillow opcional (solo para el overlay del Lab 1). Con timeout de 60 s para no colgar el checkpoint 0.
if [ "$INSTALAR_PILLOW" -eq 1 ]; then
  if python3 -c 'import PIL' >/dev/null 2>&1; then
    ok "Pillow ya está instalado ($(python3 -c 'import PIL; print(PIL.__version__)'))"
  else
    echo "Instalando Pillow en ~/.local (opcional, máximo 60 s)..."
    if command -v timeout >/dev/null 2>&1; then
      timeout 60 python3 -m pip install --user --quiet pillow
    else
      python3 -m pip install --user --quiet pillow
    fi
    if python3 -c 'import PIL' >/dev/null 2>&1; then
      ok "Pillow instalado"
    else
      aviso "Pillow no se instaló (wifi lento o sin pip). No pasa nada: el overlay se omite y puedes mirar docs/salidas/."
    fi
  fi
fi

if [ "$FALLOS" -gt 0 ]; then
  error "hay $FALLOS problema(s) arriba; corrígelos o usa: python3 00_check.py --offline"
  exit "$FALLOS"
fi

# 6. Checkpoint 0
echo
echo "== python3 00_check.py =="
python3 00_check.py
CODIGO=$?
echo
case "$CODIGO" in
  0) ok "LISTO: levanta la mano verde" ;;
  2) error "error de AWS (ver arriba). Para continuar sin AWS: python3 00_check.py --offline" ;;
  *) error "00_check.py terminó con código $CODIGO. Pide ayuda a un helper o prueba: python3 00_check.py --offline" ;;
esac
exit "$CODIGO"
