# textract-ec — Construye un sistema inteligente de OCR con Amazon Textract y Python

**AWS Community Day Ecuador 2026 · Cuenca, sábado 5 de septiembre · 15:00–16:10 · Auditorio Luis Alberto Luna**

En 70 minutos vas a construir, en Python y con `boto3` como única dependencia, un sistema que toma la imagen de una factura ecuatoriana (o de un formulario), la envía a Amazon Textract, recorre la respuesta como un grafo de bloques (`PAGE → LINE → WORD`, pares clave-valor, tablas, checkboxes, queries), convierte cada dato en un `Campo{valor, confianza, origen}`, lo valida con reglas de negocio ecuatorianas deterministas (módulo 11 del RUC, dígito verificador de la clave de acceso de 49 dígitos, IVA 15 %, suma de ítems = subtotal) y produce un JSON con estado `OK` o `REVISAR` y alertas explicables. Al final lo corres en lote sobre una carpeta entera y ves cómo se convierte en un pipeline. Funciona **con tu cuenta AWS** (modo online) o **sin ninguna cuenta** (modo offline, con respuestas grabadas): el código de parseo es el mismo en ambos casos.

> URL corta del taller: `github.com/jossuema/textract-ec` · Repo: `https://github.com/jossuema/textract-ec`

---

## 1. Empieza aquí: los 3 comandos del checkpoint 0

```bash
git clone --depth 1 https://github.com/jossuema/textract-ec.git && cd textract-ec
python3 00_check.py
python3 -m pip install --user pillow   # opcional: solo para dibujar el overlay de cajas
```

`00_check.py` imprime tu versión de Python y de boto3, el perfil y la fuente de credenciales que boto3 encontró, tu account id y ARN (vía `sts:GetCallerIdentity`, que no requiere permisos IAM), la región (`us-east-1`), el modo (ONLINE u OFFLINE) y termina con la palabra **LISTO**.

- En **ONLINE** hace una única llamada `DetectDocumentText` sobre `docs/mini.png` (~40 KB, 4 líneas con tildes y ñ, US$ 0.0015) y la guarda en `cache/`.
- En **OFFLINE** no llama a nada: verifica `fixtures/MANIFEST.sha256` (integridad de las respuestas grabadas: 20 archivos, 16 de Textract + 4 de Bedrock) y muestra `fixtures/META.json`.
- Si ves una línea **roja** con una excepción de AWS (`AccessDeniedException`, `EndpointConnectionError`, etc.), el mensaje te dice exactamente qué pasó y cómo seguir sin AWS: `python3 00_check.py --offline`.

Reglas del taller: si no tienes laptop, siéntate con alguien que sí; si no tienes cuenta AWS, el repo funciona igual en modo offline; en cada checkpoint levanta la mano (verde = listo, rojo = ayuda).

---

## 2. Cuatro caminos, el mismo repo, el mismo código

| Camino | Para quién | Qué necesitas | Cómo empezar |
|---|---|---|---|
| **A · CloudShell** (recomendado) | Tienes cuenta AWS propia | Nada que instalar: CloudShell trae Python 3, pip, boto3 y git; hereda las credenciales de tu sesión de consola | Consola AWS → región **us-east-1** (N. Virginia) → icono de CloudShell → los 3 comandos de arriba (o `bash scripts/setup_cloudshell.sh`) |
| **B · Laptop propia** | Tienes cuenta AWS y prefieres tu editor | Python **>= 3.10**, `pip install boto3`, credenciales en un perfil (`AWS_PROFILE=<nombre>`) o en variables de entorno | `bash scripts/setup_local.sh && source .venv/bin/activate && export AWS_PROFILE=<perfil> && python3 00_check.py` (macOS/Linux; el `source` es obligatorio: boto3 se instala dentro de `.venv`) o `scripts\setup_local.ps1` y luego `.venv\Scripts\Activate.ps1` (Windows) |
| **C · Sin cuenta o sin red** | No tienes cuenta AWS, o el wifi no coopera | Cualquier Python >= 3.10; boto3 ni siquiera es obligatorio en offline | `python3 00_check.py --offline` (o una sola vez `export LAB_MODO=offline` y sin flag) y sigue todos los labs igual |
| **D · Notebook** | Prefieres Jupyter, VS Code o Google Colab | Jupyter o Colab; en Colab la primera celda clona el repo sola | Abre `notebooks/taller.ipynb` y ejecuta las celdas en orden. Trae los 4 labs y **muestra el overlay en línea** |

Detalles por camino:

- **A.** Abre la consola, cambia la región a `us-east-1` (arriba a la derecha) y pulsa el icono de terminal de CloudShell. Tarda 1–2 minutos en arrancar: hazlo antes de que empiece el contenido. Tu `$HOME` (1 GB) persiste entre sesiones, así que el clone y `python3 -m pip install --user pillow` sobreviven. CloudShell no muestra imágenes: el overlay del Lab 1 se descarga con **Actions → Download file** o se mira en `docs/salidas/`. Si aparece `Timed out while opening the session`, el proxy bloquea WebSockets: pasa al camino B o C.
- **B.** boto3 dejó de soportar Python 3.9 en abril de 2026: necesitas 3.10 o superior. Las credenciales nunca van en el código: boto3 lee `~/.aws/credentials` y `~/.aws/config` solo; `AWS_PROFILE` elige qué perfil. `00_check.py` te dice qué perfil y qué fuente usó. Tras `scripts/setup_local.sh`, activa el entorno en cada terminal nueva (`source .venv/bin/activate`) antes de correr los labs en online. Copia `.env.example` a `.env` si quieres documentar tu perfil (el archivo está en `.gitignore`).
- **C.** Sin credenciales, el helper `textract_lab/cliente.py` cae solo a OFFLINE con un aviso amarillo; no es un error, es el estado esperado de quien no tiene cuenta. Todo lo que hacen los scripts en offline sale de `fixtures/` (ver §4).
- **D.** `notebooks/taller.ipynb` hace lo mismo que los scripts `00`–`05` importando el mismo paquete `textract_lab`, así que no hay lógica duplicada. Va **en modo offline por defecto**: no pide credenciales ni gasta un centavo. Su ventaja sobre la terminal es que enseña el **overlay de cajas de confianza en línea**, que es justo lo que CloudShell no puede mostrar. Si lo abres en **Google Colab**, no pegues ahí tus claves de AWS: es un entorno de terceros y el modo offline te deja hacer el taller completo sin ellas. Para leerlo desde el celular sin ejecutar nada, `docs/salidas/taller-ejecutado.html` tiene una copia ya corrida con todas las salidas.

Región: el laboratorio usa **us-east-1** fijo porque Textract no existe en `sa-east-1` (São Paulo). Solo cámbiala con `LAB_REGION=us-east-2` si hay un incidente regional.

---

## 3. Los labs

Todos los scripts se ejecutan desde la raíz del repo. Flags comunes: `--offline` / `--online` (mutuamente excluyentes; sin flag, el helper decide según tus credenciales). Códigos de salida: `0` éxito, `2` error de AWS (impreso en rojo con la causa), `1` cualquier otro error. La **primera línea** de cada script es el banner de modo, por ejemplo `[ONLINE us-east-1 · perfil personal]` o `[OFFLINE · fixtures reales grabados 2026-09-04]`.

| Paso | Comando | API de Textract | Qué debes ver | Costo online (aprox.) |
|---|---|---|---|---|
| **0 · Checkpoint** | `python3 00_check.py` | `DetectDocumentText` sobre `docs/mini.png` | Python, boto3, perfil, cuenta, ARN, región, modo, 4 líneas de `mini.png` leídas con tildes y ñ, costo de sesión y **LISTO** | US$ 0.0015 |
| **1 · Texto y confianza** | `python3 01_texto.py docs/factura_limpia.png` y luego `python3 01_texto.py docs/factura_foto.jpg --overlay` | `DetectDocumentText` | Cada línea con su `Confidence` en semáforo (verde >= 90, amarillo 70–90, rojo < 70), confianza media y número de palabras < 90. Con los fixtures reales: limpia **LINE 98.9 · WORD 98.7** con 5 palabras < 90 de 172; foto **LINE 97.3 · WORD 96.2** con 20 de 173. La caída existe pero es pequeña: Textract aguanta bien la foto de celular. Con `--overlay` y Pillow: `salida/<doc>.overlay.png` (sin Pillow: aviso y sigue) | US$ 0.003 |
| **2 · Formularios, checkboxes y tablas** | `python3 02_formulario_tabla.py docs/factura_limpia.png --csv` y `python3 02_formulario_tabla.py docs/formulario_inscripcion.png` | `AnalyzeDocument` con `FORMS`+`TABLES`+`LAYOUT` | Dict clave → valor (`RUC` → `1790456129001`, `VALOR TOTAL` → `944.84`), la tabla de 3 ítems y `salida/factura_limpia.detalle.csv`; en el formulario, checkboxes como `[X]`/`[ ]` (`Intermedio` → `[X]`). Aquí está el **único TODO** del taller (`mi_pares_clave_valor`) con autoverificación: `✔ tu implementación coincide` | US$ 0.065 por documento |
| **3 · Capa inteligente** | `python3 03_inteligente.py docs/factura_limpia.png` y `python3 03_inteligente.py docs/factura_trampa.png` | `AnalyzeDocument` con `QUERIES` (7 preguntas en inglés ASCII); reutiliza FORMS/TABLES del Lab 2 desde `cache/` (fixture en offline) | Tabla de campos con `origen` (QUERIES / FORMS / TABLES) y confianza, la competencia por campo, alertas y estado. `factura_limpia` → **OK**, sin alertas; QUERIES gana casi todos los campos, pero en `CLAVE_ACCESO` (49 dígitos) baja a 83.0 y **gana FORMS con 95.0**: por eso se combinan fuentes. `factura_trampa` → **REVISAR** con dos alertas: *clave de acceso con dígito verificador inválido (esperado 3, leído 4)* e *ítems no suman el subtotal: ítems 831.60 vs SUBTOTAL 821.60* (los errores están en el documento, no en el OCR) | US$ 0.015 por documento (+ US$ 0.065 si el Lab 2 no dejó cache) |
| **4 · Esto es un sistema** | `python3 04_sistema.py docs/` | Ninguna nueva: solo `cache/` y `fixtures/` (llama a AWS únicamente con `--online`) | Tabla `documento · tipo · estado · nº alertas · páginas · US$` con 6 filas (orden alfabético): `factura_foto factura OK 0`, `factura_limpia factura OK 0`, `factura_trampa factura REVISAR 2`, `formulario_inscripcion formulario OK 0`, `mini desconocido REVISAR 1` (4 líneas sin RUC ni checkbox: así se ve un documento sin patrón) y `orden_compra_prosa desconocido REVISAR 1`; resumen `3 OK · 3 REVISAR · 0 SIN DATOS`; `salida/resumen.json` y `salida/<doc>.validado.json`. Documentos sin fixture aparecen como `SIN DATOS` sin romper nada | US$ 0.00 (con `--online` y `cache/` vacío ≈ US$ 0.45 por los 6 documentos; el script lo estima antes de llamar) |
| **Bonus (demo del ponente)** | `python3 05_bonus_bedrock.py docs/orden_compra_prosa.png --offline` | Bedrock Converse (Claude Haiku 4.5 o Amazon Nova Lite) sobre el texto que extrajo Textract | (a) Las 3 queries sobre la carta en prosa frente al JSON del LLM: `PROVEEDOR` responde `Gerente de Compras` (60.0) — es el cargo de quien firma, no el proveedor —, `TOTAL_COMPRA` no responde y `CANT_MONITORES` responde `27` **con 99.0 de confianza** cuando la cantidad es 3 (27 son las pulgadas). El LLM devuelve los tres bien; (b) sobre `docs/factura_foto.jpg`, normalización y explicación de alertas; la salida del LLM vuelve a pasar por los validadores ("el LLM propone, el módulo 11 dispone"); `usage` y costo aproximado | < US$ 0.005 por documento con Haiku 4.5 |

Si te quedas atrás en cualquier lab: `cp checkpoints/lab1/01_texto.py .` (o `lab2/`, `lab3/`) y sigue con el siguiente comando. Lab 4 usa las soluciones de la librería, así que siempre puedes correrlo.

Guía paso a paso (pensada para leer desde el celular en pareja): **[GUIA_ASISTENTE.md](GUIA_ASISTENTE.md)**. Resumen de una página: **[CHEATSHEET.md](CHEATSHEET.md)**.

---

## 4. Modo offline: qué es un fixture y por qué es tan válido como online

Un **fixture** es la respuesta cruda de Textract (`json.dump` del dict que devuelve boto3, con todos los `Blocks`) guardada en `fixtures/<documento>/<operacion>[__<features>][__<hash>].json`. `textract_lab/cliente.py` usa exactamente la misma clave para `cache/` (respuestas que tú grabas en online) y para `fixtures/` (respuestas que vienen con el repo): el resto del código no sabe ni le importa de dónde salió el JSON.

Orden de decisión del helper (`resolver_modo()`):

1. `--offline` / `--online` o la variable `LAB_MODO` mandan.
2. Sin flag: si boto3 no encuentra credenciales (`NoCredentialsError`) → **OFFLINE automático** con aviso amarillo.
3. Con credenciales: si existe `cache/<clave>.json` lo usa (imprime `[CACHE]`, no toca AWS ni te cobra); si no, llama a Textract en `us-east-1` con reintentos `standard` (10 intentos) y guarda la respuesta en `cache/`.
4. Cualquier otro error de AWS (permisos, red, throttling agotado, documento inválido) **no** se oculta: se imprime en rojo con la causa y la línea `para continuar sin AWS: python3 <script> --offline`.

**Los fixtures de este repo son REALES.** Se grabaron el **2026-09-04** con `tools/grabar_fixtures.py` desde la cuenta del ponente en `us-east-1`: **16 llamadas a Textract por US$ 0.3955**. No son simulaciones ni respuestas editadas a mano. Lo compruebas en tres sitios:

- El banner de cada script dice `[OFFLINE · fixtures reales grabados 2026-09-04]`.
- `fixtures/META.json` tiene `"origen": "textract"`, `"generado": "2026-09-04"`, la región, los últimos 4 dígitos de la cuenta y la versión del modelo (`DetectDocumentTextModelVersion` y `AnalyzeDocumentModelVersion` 1.0). No hay errores inyectados: `"errores_inyectados": {}`.
- `python3 00_check.py --offline` valida el hash de los 20 archivos contra `fixtures/MANIFEST.sha256` e imprime `✔ MANIFEST OK`.

Consecuencia que conviene saber antes del Lab 3: sobre la foto de celular, Textract se comportó mejor de lo esperado (WORD 96.2 frente a 98.7 de la original) y `factura_foto` sale **OK, sin alertas**. El documento que enseña el estado `REVISAR` es `factura_trampa`, donde el OCR es perfecto y aun así el documento está mal.

**Única excepción:** los 4 archivos de `fixtures/bedrock/` siguen siendo sintéticos (`"sintetico": true`) porque el bonus depende de habilitar modelos de Anthropic; `05_bonus_bedrock.py` lo dice en pantalla cuando los usa.

En offline el set de queries es fijo (el del taller): si editas `textract_lab/queries.py`, el script avisa y usa el fixture del set original. Experimentar con queries propias requiere credenciales.

`docs/salidas/` contiene los overlays PNG, CSV y JSON que producen los labs, por si solo puedes mirar desde el celular o no tienes Pillow (se regeneran con `bash tools/gen_salidas.sh`, sin AWS).

---

## 5. Cuánto cuesta (tarifa de US West Oregón como aproximación; us-east-1 no confirmado en la página oficial)

| Operación / feature | US$ por página | Free tier (cuentas nuevas, 3 meses) |
|---|---|---|
| `DetectDocumentText` | 0.0015 | 1.000 páginas/mes |
| `AnalyzeDocument` FORMS | 0.05 | 100 páginas/mes (Forms, Tables, Layout, Queries y sus combinaciones) |
| `AnalyzeDocument` TABLES | 0.015 | idem |
| `AnalyzeDocument` QUERIES | 0.015 | idem |
| `AnalyzeDocument` LAYOUT | 0.004 (gratis si va con TABLES/FORMS/QUERIES) | idem |
| `AnalyzeDocument` SIGNATURES | 0.0035 | 1.000 páginas/mes solo Signatures |
| `AnalyzeExpense` | 0.01 | 100 páginas/mes |

Las features se **suman** dentro de una misma llamada: FORMS+TABLES+LAYOUT = US$ 0.065/página. Haciendo todo el taller en online desde tu cuenta gastas **≈ US$ 0.23** (3 `DetectDocumentText` + 3 `AnalyzeDocument` FORMS+TABLES+LAYOUT + 2 QUERIES). Con free tier vigente, US$ 0.00. El contador `python3 00_check.py --costo` te muestra páginas consumidas y costo estimado de tu sesión (acumulado en `cache/.costos.json`). El cache evita pagar dos veces la misma llamada.

Bonus Bedrock: Claude Haiku 4.5 ≈ US$ 1.00 / 5.00 por millón de tokens de entrada / salida; Amazon Nova Lite ≈ US$ 0.06 / 0.24. Una factura (≈ 2.000 tokens de entrada, ≈ 300 de salida) cuesta ≈ US$ 0.003 con Haiku y ≈ US$ 0.0002 con Nova. Precios de Bedrock tomados de fuentes secundarias, no confirmados en la página oficial de AWS.

---

## 6. Límites que importan hoy (verificados en la documentación oficial, septiembre 2026)

| Tema | Límite |
|---|---|
| Operaciones síncronas (`DetectDocumentText`, `AnalyzeDocument`, `AnalyzeExpense`) | JPEG/PNG/PDF/TIFF de **máximo 10 MB** y **1 sola página** (PDF/TIFF). La página `API_Document` aún dice 5 MB y solo PNG/JPEG: es una inconsistencia documental; la cifra operativa es 10 MB |
| Operaciones asíncronas | Solo desde S3 en la misma región; PDF/TIFF hasta 500 MB y 3.000 páginas (`extra/07_async_s3.py`) |
| Idioma: texto **impreso** | Español **soportado oficialmente** (á é í ó ú ñ Ñ ü ¿ ¡ €), junto con inglés, francés, alemán, italiano y portugués. Textract no devuelve el idioma detectado |
| Idioma: manuscrito, Queries, `AnalyzeExpense` | Documentados **solo para inglés**. En la grabación del 2026-09-04 las 7 queries en inglés **sí respondieron** sobre la factura en español (RUC 99.0, IVA 99.0, TOTAL 98.0…): funcionó, pero fuera del soporte oficial y sin garantía. Por eso el Lab 3 combina QUERIES con FORMS y registra el `origen` de cada campo — y de hecho en `CLAVE_ACCESO` gana FORMS (95.0) a QUERIES (83.0) |
| `AnalyzeID` | Solo pasaportes y licencias de EE. UU.: no sirve para cédulas ecuatorianas (usa FORMS/QUERIES) |
| Queries | Máximo **15 por página** en sync (30 en async); `Text` y `Alias` de hasta 200 caracteres y **solo ASCII**: una query con `¿`, `é` o `ñ` lanza `InvalidParameterException` |
| Región | `us-east-1` (no hay Textract en `sa-east-1`) |
| Cuotas por defecto (por cuenta y región) | `DetectDocumentText` 25 TPS, `AnalyzeDocument` 10 TPS, `AnalyzeExpense` 5 TPS. Al excederlas: `ProvisionedThroughputExceededException` / `ThrottlingException`; el helper reintenta en modo `standard` |
| Calidad de imagen | >= 150 DPI recomendado; altura mínima de texto 15 px; Textract tolera rotación en el plano pero no corrige perspectiva ni desenfoque |
| Human-in-the-loop | No uses `HumanLoopConfig` (Amazon A2I está en modo mantenimiento desde julio de 2026 y rechaza cuentas nuevas). El estado `REVISAR` de este taller es tu cola de revisión |

---

## 7. Seguridad

- **Nunca pegues claves en el código ni en notebooks.** boto3 las lee de CloudShell, de `AWS_PROFILE` / `~/.aws/credentials` o de variables de entorno. `.env` y `cache/` están en `.gitignore`.
- Si creas un usuario IAM para el taller, dale solo la política mínima de [`iam/textract-workshop-policy.json`](iam/textract-workshop-policy.json): `textract:DetectDocumentText`, `textract:AnalyzeDocument` y `textract:AnalyzeExpense` limitados a `us-east-1`/`us-east-2`, más `bedrock:InvokeModel` opcional para el bonus. `sts:GetCallerIdentity` no necesita permiso.
- Para el bonus en casa, la política ampliada está en [`iam/bedrock-workshop-policy.json`](iam/bedrock-workshop-policy.json) (ver [`bonus/README.md`](bonus/README.md)).
- **Rota o elimina** las claves de acceso que hayas creado para el taller al terminar (IAM → Usuarios → Credenciales de seguridad). Las claves temporales de CloudShell caducan solas.
- Crea un presupuesto en AWS Budgets (por ejemplo US$ 5 con alerta) si es tu primera cuenta: es gratis y te avisa por correo.
- Los documentos de `docs/` son **ficticios** (RUC, cédulas y claves de acceso con dígitos verificadores válidos pero inventados). No subas documentos reales con datos personales a un repo público.

---

## 8. Estructura del repo

```
00_check.py … 05_bonus_bedrock.py   los labs, en orden
textract_lab/                       la librería del taller (cliente, bloques, validadores, etapas, overlay, bedrock, costos, consola)
docs/                               documentos ficticios de 1 página (< 10 MB) + ground_truth/ + salidas/ pregeneradas
fixtures/                           respuestas de Textract y Bedrock para el modo offline + META.json + MANIFEST.sha256
notebooks/taller.ipynb              los 4 labs en Jupyter/Colab, con el overlay en línea
checkpoints/lab1|lab2|lab3/         versiones resueltas de cada lab
extra/                              tarea para casa: AnalyzeExpense, asíncrono con S3, textractor
bonus/README.md                     cómo habilitar Bedrock en tu cuenta
iam/                                políticas IAM mínimas
scripts/                            setup para CloudShell, macOS/Linux y Windows
tools/                              utilidades del ponente (grabar fixtures, evaluar, precalentar esquema, bedrock_check, gen_salidas.sh)
tests/                              pytest 100 % offline
slides/                             deck autocontenido y su fuente en Markdown
cache/  salida/                     generados por ti (ignorados por git)
```

---

## 9. Cómo seguir en casa

- `extra/06_expense.py`: `AnalyzeExpense` sobre un recibo (documentado solo para inglés; se presenta como experimento).
- `extra/07_async_s3.py`: `StartDocumentAnalysis` / `GetDocumentAnalysis` con un bucket en `us-east-1`, polling y `NextToken` (documentos de varias páginas).
- `extra/08_textractor.py`: la librería `amazon-textract-textractor` (`pip install -r requirements-extra.txt`) para exportar a pandas y Markdown.
- `bonus/README.md`: habilitar Bedrock (Claude Haiku 4.5 o Nova Lite) en tu cuenta y correr `05_bonus_bedrock.py --online`.
- `python3 -m pytest -q`: los tests corren sin red sobre los fixtures; úsalos para validar cualquier cambio que hagas en `textract_lab/`.
- `tools/evaluar.py`: compara `salida/<doc>.validado.json` con `docs/ground_truth/<doc>.json` y reporta campos correctos / total.
- Siguiente nivel: Bedrock Data Automation (blueprints por tipo de documento, ≈ US$ 0.01–0.04/página según fuentes secundarias; no está en `sa-east-1`) y Custom Queries de Textract (adaptadores entrenados en consola, 2–30 horas de entrenamiento).

---

## 10. Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `Timed out while opening the session` al abrir CloudShell | El proxy bloquea WebSockets | Camino B (laptop) o C (`--offline`) |
| Aviso amarillo `[OFFLINE] sin credenciales` | boto3 no encontró credenciales | Es normal sin cuenta. Con cuenta: `export AWS_PROFILE=<perfil>` y revisa `~/.aws/credentials` |
| Rojo `AccessDeniedException` | La política IAM no permite `textract:AnalyzeDocument` | Adjunta `iam/textract-workshop-policy.json`; mientras tanto `--offline` |
| Rojo `EndpointConnectionError` / `Could not connect` | Sin red hacia `us-east-1` | `--offline` |
| Rojo `InvalidParameterException` en el Lab 3 | Una query con tildes, `¿` o `ñ` | Queries en inglés y ASCII puro (máximo 15) |
| Rojo `DocumentTooLargeException` / `UnsupportedDocumentException` | > 10 MB o PDF de varias páginas | Redimensiona o usa 1 página; para lotes, `extra/07_async_s3.py` |
| `ThrottlingException` tras 10 intentos | Muchas llamadas seguidas en tu cuenta (10 TPS) | Espera unos segundos; la segunda ejecución sale de `cache/` |
| `overlay omitido: Pillow no está instalado` | Falta Pillow | `python3 -m pip install --user pillow` (el mismo intérprete que corre los labs), o mira `docs/salidas/` |
| `error: externally-managed-environment` al instalar Pillow | Python gestionado por el sistema (PEP 668: Homebrew python@3.12+, Debian/Ubuntu >= 23.04) | `python3 -m pip install --user --break-system-packages pillow`, o `bash scripts/setup_local.sh --extra` (venv), o simplemente mira `docs/salidas/` |
| `boto3 no instalado` en online después de `scripts/setup_local.sh` | El entorno `.venv` no está activado | `source .venv/bin/activate` (Windows: `.venv\Scripts\Activate.ps1`) y repite |
| `ModuleNotFoundError: boto3` en online | Python sin boto3 | `pip install boto3` (o `scripts/setup_local.sh`); en offline no hace falta |
| `python3` es 3.9 o menor | boto3 ya no lo soporta (solo importa en online) | En offline el kit funciona igual con 3.9; para online usa CloudShell, otro intérprete (`python3.11`) o pairing |
| `MANIFEST` con diferencias en `00_check.py --offline` | Clone corrupto o fixtures editados | `git checkout -- fixtures/` o vuelve a clonar |

---

## 11. Créditos y licencia

Taller diseñado y dictado por **Manuel Josue** para el AWS Community Day Ecuador 2026 (AWS User Group Ecuador, Universidad Politécnica Salesiana, Cuenca). Código y documentos bajo licencia **MIT** (ver [`LICENSE`](LICENSE)): úsalo, modifícalo y compártelo citando la fuente. Todos los documentos de ejemplo son ficticios; cualquier coincidencia con empresas o personas reales es casual. Amazon Textract, Amazon Bedrock y AWS son marcas de Amazon.com, Inc. o sus filiales; este material es comunitario y no está afiliado a AWS.

Fuentes principales: [Límites e idiomas de Textract](https://docs.aws.amazon.com/textract/latest/dg/limits-document.html) · [API Query](https://docs.aws.amazon.com/textract/latest/APIReference/API_Query.html) · [Precios de Textract](https://aws.amazon.com/textract/pricing/) · [Buenas prácticas](https://docs.aws.amazon.com/textract/latest/dg/textract-best-practices.html) · [Relationships](https://docs.aws.amazon.com/textract/latest/APIReference/API_Relationship.html) · [Cuotas y regiones](https://docs.aws.amazon.com/general/latest/gr/textract.html) · [CloudShell](https://docs.aws.amazon.com/cloudshell/latest/userguide/vm-specs.html) · [Acceso a modelos de Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html) · [Structured outputs](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html).
