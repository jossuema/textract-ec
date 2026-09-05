<#
.SYNOPSIS
  setup_local.ps1 - preparacion del taller en Windows (PowerShell 5.1 o 7+).

.DESCRIPTION
  Verifica Python >= 3.10, crea .venv, instala boto3 (requirements.txt) y ejecuta 00_check.py.
  Credenciales: NUNCA van en el codigo. boto3 las lee de %USERPROFILE%\.aws\credentials;
  elige el perfil con:  $env:AWS_PROFILE = "<nombre-del-perfil>"
  Sin cuenta AWS:       $env:LAB_MODO = "offline"   (o agrega --offline a cada script)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup_local.ps1
  powershell -ExecutionPolicy Bypass -File scripts\setup_local.ps1 -Extra
  powershell -ExecutionPolicy Bypass -File scripts\setup_local.ps1 -SoloVerificar
#>
param(
    [switch]$Extra,
    [switch]$SoloVerificar
)

$ErrorActionPreference = "Continue"

function Ok($msg)    { Write-Host ("OK  " + $msg) -ForegroundColor Green }
function Aviso($msg) { Write-Host ("!   " + $msg) -ForegroundColor Yellow }
function Falla($msg) { Write-Host ("X   " + $msg) -ForegroundColor Red }

# Raiz del repo = directorio padre de scripts\
$Raiz = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Raiz
Write-Host "Raiz del repo: $Raiz"

# 1. Buscar un interprete >= 3.10 (py launcher primero, luego python)
$Candidatos = @(
    @{ Exe = "py";     Args = @("-3") },
    @{ Exe = "python"; Args = @() },
    @{ Exe = "python3"; Args = @() }
)
$Py = $null
$PyArgs = @()
foreach ($c in $Candidatos) {
    if (Get-Command $c.Exe -ErrorAction SilentlyContinue) {
        & $c.Exe @($c.Args) -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Py = $c.Exe
            $PyArgs = $c.Args
            break
        }
    }
}
if (-not $Py) {
    Falla "No encontre un Python >= 3.10 (boto3 dejo de soportar 3.9 en abril de 2026)."
    Write-Host "  Instala Python 3.10+ desde https://www.python.org/downloads/ (marca 'Add python.exe to PATH') y vuelve a ejecutar."
    Write-Host "  Alternativas sin instalar nada: AWS CloudShell (con cuenta) o parear con alguien."
    exit 1
}
$Version = & $Py @PyArgs -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
Ok "Python: $Py $($PyArgs -join ' ') $Version"

if ($SoloVerificar) {
    & $Py @PyArgs -c "import boto3" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $VersionBoto = & $Py @PyArgs -c "import boto3; print(boto3.__version__)"
        Ok "boto3 $VersionBoto ya disponible en este interprete"
    } else {
        Aviso "boto3 no esta en este interprete; el script lo instalara en .venv cuando lo ejecutes sin -SoloVerificar"
    }
    Ok "Verificacion terminada"
    exit 0
}

# 2. Entorno virtual
if (-not (Test-Path ".venv")) {
    Write-Host "Creando .venv ..."
    & $Py @PyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { Falla "No pude crear .venv"; exit 1 }
    Ok ".venv creado"
} else {
    Ok ".venv ya existe"
}
$VenvPy = Join-Path $Raiz ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { Falla "No encuentro $VenvPy"; exit 1 }

# 3. Dependencias (boto3 es la unica obligatoria)
Write-Host "Instalando requirements.txt (boto3) ..."
& $VenvPy -m pip install --quiet --upgrade pip 2>$null | Out-Null
& $VenvPy -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -eq 0) {
    $VersionBoto = & $VenvPy -c "import boto3; print(boto3.__version__)"
    Ok "boto3 $VersionBoto"
} else {
    Falla "pip install -r requirements.txt fallo (sin red?). En modo offline no necesitas boto3: python 00_check.py --offline"
}

if ($Extra) {
    Write-Host "Instalando requirements-extra.txt (pillow, rich, textractor) ..."
    & $VenvPy -m pip install --quiet -r requirements-extra.txt
    if ($LASTEXITCODE -eq 0) { Ok "Extras instalados" } else { Aviso "Los extras no se instalaron; el taller funciona igual sin ellos (el overlay se omite)" }
}

# 4. Recordatorio de credenciales
Write-Host ""
if ($env:AWS_PROFILE) {
    Ok "AWS_PROFILE=$($env:AWS_PROFILE) (boto3 usara ese perfil de $env:USERPROFILE\.aws\credentials)"
} else {
    Aviso "AWS_PROFILE no esta definido. Si tienes cuenta AWS:  `$env:AWS_PROFILE = `"<nombre-del-perfil>`""
    Aviso "Si no tienes cuenta:  `$env:LAB_MODO = `"offline`"   (o usa --offline en cada script)"
}
Write-Host "Activa el entorno en cada terminal nueva:  .venv\Scripts\Activate.ps1"
Write-Host "Si PowerShell bloquea la activacion:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned"

# 5. Checkpoint 0
Write-Host ""
Write-Host "== python 00_check.py =="
& $VenvPy 00_check.py
$Codigo = $LASTEXITCODE
Write-Host ""
switch ($Codigo) {
    0 { Ok "LISTO" }
    2 { Falla "Error de AWS (ver arriba). Para continuar sin AWS: python 00_check.py --offline" }
    default { Falla "00_check.py termino con codigo $Codigo. Prueba: python 00_check.py --offline" }
}
exit $Codigo
