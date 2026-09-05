#!/usr/bin/env bash
# setup_local.sh — preparación del taller en tu laptop (macOS / Linux).
#
# Uso (desde la raíz del repo):
#   bash scripts/setup_local.sh                  # verifica Python >= 3.10, crea .venv, instala boto3, corre 00_check.py
#   bash scripts/setup_local.sh --extra          # además instala requirements-extra.txt (pillow, rich, textractor)
#   bash scripts/setup_local.sh --solo-verificar # solo comprueba Python, no crea .venv ni instala nada
#
# Credenciales: NUNCA van en el código. boto3 las lee de ~/.aws/credentials y ~/.aws/config;
# elige el perfil con:  export AWS_PROFILE=<nombre-del-perfil>
# Sin cuenta AWS:       export LAB_MODO=offline   (o agrega --offline a cada script)
set -u

CON_EXTRA=0
SOLO_VERIFICAR=0
for arg in "$@"; do
  case "$arg" in
    --extra) CON_EXTRA=1 ;;
    --solo-verificar) SOLO_VERIFICAR=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *) echo "argumento desconocido: $arg (usa --extra o --solo-verificar)"; exit 1 ;;
  esac
done

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  VERDE=$'\033[32m'; AMARILLO=$'\033[33m'; ROJO=$'\033[31m'; RESET=$'\033[0m'
else
  VERDE=""; AMARILLO=""; ROJO=""; RESET=""
fi
ok()    { printf '%s✔ %s%s\n' "$VERDE" "$1" "$RESET"; }
aviso() { printf '%s! %s%s\n' "$AMARILLO" "$1" "$RESET"; }
error() { printf '%s✘ %s%s\n' "$ROJO" "$1" "$RESET"; }

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ" || { error "no pude entrar a $RAIZ"; exit 1; }
echo "Raíz del repo: $RAIZ"

# 1. Buscar un intérprete >= 3.10 (primero los más nuevos, luego python3 genérico)
PY=""
for candidato in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$candidato" >/dev/null 2>&1 && "$candidato" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    PY="$candidato"
    break
  fi
done
if [ -z "$PY" ]; then
  error "no encontré un Python >= 3.10 (boto3 dejó de soportar 3.9 en abril de 2026)."
  echo "  Instala Python 3.10+ desde https://www.python.org/downloads/ (o con brew/apt/pyenv) y vuelve a ejecutar."
  echo "  Alternativas sin instalar nada: AWS CloudShell (con cuenta) o parear con alguien."
  exit 1
fi
ok "Python: $PY $("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"

if [ "$SOLO_VERIFICAR" -eq 1 ]; then
  if "$PY" -c 'import boto3' >/dev/null 2>&1; then
    ok "boto3 $("$PY" -c 'import boto3; print(boto3.__version__)') ya disponible en este intérprete"
  else
    aviso "boto3 no está en este intérprete; el script lo instalará en .venv cuando lo ejecutes sin --solo-verificar"
  fi
  ok "verificación terminada"
  exit 0
fi

# 2. Entorno virtual
if [ ! -d .venv ]; then
  echo "Creando .venv con $PY ..."
  "$PY" -m venv .venv || { error "no pude crear .venv (¿falta el módulo venv? en Debian/Ubuntu: apt install python3-venv)"; exit 1; }
  ok ".venv creado"
else
  ok ".venv ya existe"
fi
VENV_PY=".venv/bin/python"
[ -x "$VENV_PY" ] || { error "no encuentro $VENV_PY"; exit 1; }

# 3. Dependencias (boto3 es la única obligatoria)
echo "Instalando requirements.txt (boto3) ..."
"$VENV_PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
if "$VENV_PY" -m pip install --quiet -r requirements.txt; then
  ok "boto3 $("$VENV_PY" -c 'import boto3; print(boto3.__version__)')"
else
  error "pip install -r requirements.txt falló (¿sin red?). En modo offline no necesitas boto3: python3 00_check.py --offline"
fi

if [ "$CON_EXTRA" -eq 1 ]; then
  echo "Instalando requirements-extra.txt (pillow, rich, textractor) ..."
  if "$VENV_PY" -m pip install --quiet -r requirements-extra.txt; then
    ok "extras instalados"
  else
    aviso "los extras no se instalaron; el taller funciona igual sin ellos (el overlay se omite)"
  fi
fi

# 4. Recordatorio de credenciales
echo
if [ -n "${AWS_PROFILE:-}" ]; then
  ok "AWS_PROFILE=$AWS_PROFILE (boto3 usará ese perfil de ~/.aws/credentials)"
else
  aviso "AWS_PROFILE no está definido. Si tienes cuenta AWS:  export AWS_PROFILE=<nombre-del-perfil>"
  aviso "Si no tienes cuenta:  export LAB_MODO=offline   (o usa --offline en cada script)"
fi
echo "Activa el entorno en cada terminal nueva:  source .venv/bin/activate"

# 5. Checkpoint 0
echo
echo "== python3 00_check.py =="
"$VENV_PY" 00_check.py
CODIGO=$?
echo
case "$CODIGO" in
  0) ok "LISTO" ;;
  2) error "error de AWS (ver arriba). Para continuar sin AWS: python3 00_check.py --offline" ;;
  *) error "00_check.py terminó con código $CODIGO. Prueba: python3 00_check.py --offline" ;;
esac
exit "$CODIGO"
