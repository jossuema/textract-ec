# Textract EC · Workshop — fuente de las slides

Construye un sistema inteligente de OCR con Amazon Textract y Python.
AWS Community Day Ecuador 2026 · Sábado 5-sep-2026 · 15:00–16:10 · Auditorio Luis Alberto Luna, UPS Cuenca · Ponente: Manuel Josue.

Este Markdown es la fuente editable de `slides/index.html` (18 slides). Cada `## Slide N` lleva un bloque `> Notas:` para el ponente. Los precios son tarifa Oregón, aprox.; los hechos no verificados llevan "(confirmar)". Los marcadores `github.com/jossuema/textract-ec`, `https://github.com/jossuema/textract-ec.git`, `jossuema` y `github.com/jossuema` se reemplazan antes de proyectar.

---

## Slide 1 — Construye un sistema inteligente de OCR con Amazon Textract y Python

*min 0*

- QR gigante → `github.com/jossuema/textract-ec` · URL corta `github.com/jossuema/textract-ec` · "Abre esto ahora".
- **Sin laptop** → siéntate con alguien que sí tenga.
- **Sin cuenta AWS** → funciona igual (modo `offline`).
- **Con cuenta** → abre CloudShell en `us-east-1` YA (tarda ~1 min).
- Manuel Josue · AWS Community Day Ecuador 2026 · UPS Cuenca.
- Motivo visual: fragmento de factura (FACTURA No. 001-001-000001234, R.U.C. 1790456129001, VALOR TOTAL 944.84) con cajas de confianza verde/ámbar/roja.

> Notas: 3 min (min 0–3). Proyectada desde antes de las 15:00. Decir textualmente las tres reglas; no explicar nada más: el objetivo es que escaneen el QR y que CloudShell empiece a arrancar. Pedir dos conteos de manos (¿laptop? ¿cuenta AWS?) y anotar el número: decide el plan de recorte. Presentar a los helpers por nombre. Pendiente: reemplazar QR y `github.com/jossuema/textract-ec`.

## Slide 2 — Qué vas a construir hoy (y las 3 reglas)

*min 1*

- Flujo: imagen / foto → Amazon Textract → Python (estructura + valida) → JSON con estado OK / REVISAR.
- Agenda (70 min): demo (7) → checkpoint 0 (8) → Labs 1–4 (32) → bonus Bedrock (5, solo demo) → cierre (3).
- Reglas: pairing; semáforo de manos en cada checkpoint; `--offline` es tan válido como `--online`.
- **Inteligente** = mide confianza + combina fuentes + valida con reglas ecuatorianas. El LLM es opcional.

> Notas: 2 min (min 1–3). Hoy no se instala nada más que boto3 (ya viene en CloudShell) y el AWS CLI no se usa. El bonus Bedrock es solo demo: la mayoría no podrá ejecutarlo en vivo por el formulario de caso de uso de Anthropic. Honestidad desde el minuto 1. El JSON final es el mismo con o sin cuenta AWS.

## Slide 3 — [DEMO] De la foto al JSON validado

*min 3*

```bash
python3 01_texto.py docs/factura_foto_real.jpg --overlay
python3 03_inteligente.py docs/factura_foto_real.jpg   # OCR robusto
python3 03_inteligente.py docs/factura_trampa.png      # el momento wow
```

- Respaldo 1: overlay de cajas con las cifras reales de `factura_foto` (fixtures del 4-sep-2026). El overlay dibuja **líneas**: 65 verdes, 6 ámbar y **0 rojas** de 71. VALOR TOTAL `944.84` verde 99.9 %, CLAVE DE ACCESO verde 92.4 %; la peor línea es la etiqueta `NÚMERO DE AUTORIZACIÓN`, 75.4 %. A nivel de **palabra** sí bajan las etiquetas con tilde (`AUTORIZACIÓN` 63.1 %, `Dirección` 71.6 %). Media WORD 96.2.
- Respaldo 2: la comparación de los tres documentos, que es el mensaje de la slide:

| documento | estado | alertas | WORD |
|---|---|---|---|
| factura_limpia | OK | 0 | 98.7 |
| factura_foto | OK | 0 | 96.2 |
| factura_trampa | **REVISAR** | **2** | 98.7 |

- `salida/factura_trampa.validado.json` → `"estado": "REVISAR"` con las dos alertas: `clave de acceso con dígito verificador inválido (esperado 3, leído 4)` y `ítems no suman el subtotal: ítems 831.60 vs SUBTOTAL 821.60`.
- "La foto del celular se lee casi como el original. El sistema no salta por el OCR: salta porque el documento está mal."

> Notas: 7 min (min 3–10). Hotspot propio, terminal a 24 pt. (1) mostrar la factura impresa; (2) si la prueba de T-2h salió bien, fotografiar ahora y pasar por AirDrop a `docs/factura_foto_vivo.jpg`; si no, usar `docs/factura_foto_real.jpg` sin comentarlo (si tampoco existe: `docs/factura_foto.jpg`); (3) teclear los tres comandos; (4) abrir el overlay PNG y cerrar con el JSON de `factura_trampa` en REVISAR. Todo sale de `cache/`: como máximo una llamada real. Nunca depurar en escena: si algo falla, `--offline`. Sobre la foto real del sábado: con los fixtures reales `factura_foto` sale OK con 0 alertas, así que **no prometas alertas de la foto**; la que tomes en el auditorio puede salir OK igual o traer alertas de confianza baja. Sirve en ambos casos: si sale OK, "Textract es robusto"; si trae alertas, las señalas y sigues. El clímax siempre es `factura_trampa`.

## Slide 4 — Checkpoint 0: cuenta, región y modo

*min 10*

```bash
git clone --depth 1 https://github.com/jossuema/textract-ec.git && cd textract-ec
python3 00_check.py
python3 -m pip install --user pillow   # opcional: overlay de cajas
```

- ONLINE: `[ONLINE us-east-1 · perfil personal]` · Python 3.10 · boto3 1.43 · cuenta · DetectDocumentText mini.png: 4 líneas, ñ y tildes OK · `LISTO`.
- OFFLINE: `[OFFLINE · fixtures reales grabados 2026-09-04]` · `fixtures/MANIFEST.sha256: OK` · `LISTO`.
- "Timed out while opening the session" → CloudShell bloqueado: laptop propia o zip del USB.
- Rojo AccessDenied / EndpointConnection → `python3 00_check.py --offline` y sigues.

> Notas: 8 min (min 10–18). El bloque más importante: caminar por la sala con los helpers. `00_check.py` imprime el account id porque `sts:GetCallerIdentity` no requiere permisos, y la región porque Textract no existe en sa-east-1. Sin credenciales cae solo a OFFLINE (aviso amarillo): es lo esperado. Cualquier otro error sale en rojo con la línea `--offline`. Min 16: semáforo; con más del 30 % en rojo, Lab 3 pasa a demo y el bonus se elimina. Pendiente: reemplazar `https://github.com/jossuema/textract-ec.git`.

## Slide 5 — Cómo piensa Textract: la respuesta es un grafo

*min 18*

```text
PAGE
 ├─ CHILD → LINE ── CHILD → WORD  (Text, Confidence)
 ├─ CHILD → KEY_VALUE_SET [KEY] ── VALUE → [VALUE]
 ├─ CHILD → TABLE ── CHILD → CELL (RowIndex, ColumnIndex)
 └─ CHILD → QUERY ── ANSWER → QUERY_RESULT
Block = { Id, BlockType, Confidence 0-100, Geometry.BoundingBox 0-1, Relationships[{Type, Ids}] }
```

```python
# textract_lab/bloques.py — las 8 líneas
def indice(resp):
    return {b['Id']: b for b in resp['Blocks']}

def hijos(b, by_id, tipo='CHILD'):
    return [by_id[i] for r in b.get('Relationships', [])
            if r['Type'] == tipo for i in r['Ids']]

def texto(b, by_id):
    return ' '.join(w['Text'] for w in hijos(b, by_id)
                    if w['BlockType'] == 'WORD')
```

- **Los hijos no conocen a su padre:** se construye `by_id` y se navega de arriba hacia abajo con `hijos()`.

> Notas: 2 min (min 18–20). Abrir el fixture real `fixtures/factura_limpia/detect_document_text.json` y señalar un PAGE, un LINE con `Relationships CHILD` y un WORD con `Confidence` y `BoundingBox`. Luego las 8 líneas. Esta pieza resuelve el 90 % del parseo; el resto son variaciones de `hijos()`. La versión completa de `texto()` convierte SELECTION_ELEMENT en `[X]` / `[ ]`.

## Slide 6 — Límites que importan hoy (una sola tabla)

*min 20*

| Tema | Lo que aplica hoy |
|---|---|
| Síncrono | 1 página por llamada · < 10 MB · PNG / JPEG / PDF / TIFF (API_Document aún dice 5 MB: la cifra operativa es 10 MB) |
| Idiomas | Texto **impreso en español: SÍ** (á é í ó ú ñ ¿ ¡) · manuscrito: solo inglés · AnalyzeExpense: solo inglés · AnalyzeID: solo EE. UU. |
| Queries | Solo inglés y **ASCII puro** (sin tildes, ñ ni ¿) · máx. 15 por página en sync · texto ≤ 200 caracteres |
| Región | **us-east-1**: Textract no existe en sa-east-1 (São Paulo) |
| Cuotas | DetectDocumentText 25 TPS · AnalyzeDocument 10 TPS por cuenta (ajustables) |
| Asíncrono | Solo desde S3 (misma región) · hasta 3.000 páginas · hoy no lo usamos (`extra/07_async_s3.py`) |

> Notas: 2 min (min 20–22). Una frase por fila. Anticipar la pregunta de las cédulas: AnalyzeID no sirve (solo pasaportes y licencias de EE. UU.); usamos FORMS / QUERIES. Queries sobre español está fuera del soporte oficial: hoy lo probamos y por eso combinamos fuentes. Fuentes: limits-document.html, API_Query.html, FAQ de Textract, AWS General Reference (verificado el 2-sep-2026).

## Slide 7 — Lab 1: DetectDocumentText y confianza

*min 22*

```bash
python3 01_texto.py docs/factura_limpia.png --overlay
python3 01_texto.py docs/factura_foto.jpg --overlay      # o factura_foto_real.jpg
```

```python
# 01_texto.py (núcleo)
from textract_lab.cliente import llamar
from textract_lab.bloques import lineas, confianza_media
from textract_lab.consola import semaforo

resp = llamar('detect_document_text', documento)
for txt, conf in lineas(resp):
    print(semaforo(conf), f'{conf:5.1f}', txt)
print('confianza media WORD:', round(confianza_media(resp, 'WORD'), 1))
```

- Motivo visual: fragmento de factura_limpia (FECHA EMISION: 01/09/2026 · SUBTOTAL 15% 821.60 · IVA 15% 123.24) con cajas verdes ≥ 98.9 %.
- Salida: líneas con semáforo · confianza media · palabras < 90 · `salida/<doc>.overlay.png` (Pillow) o `docs/salidas/`.
- Cifras reales (fixtures del 4-sep-2026): **limpia** LINE 98.9 · WORD 98.7 · 5 de 172 palabras < 90 — **foto** LINE 97.3 · WORD 96.2 · 20 de 173 < 90.

> Notas: 10 min (min 22–32). Live coding LENTO (sin copy-paste) de `texto()` y del bucle sobre LINE (5 min). Ejecutar los dos comandos y comparar: WORD 98.7 en la limpia contra 96.2 en la foto (LINE 98.9 contra 97.3). La caída existe pero es pequeña — 2.5 puntos —, no el desplome que uno esperaría de una foto de celular; lo que cambia de verdad es el número de palabras dudosas: 5 de 172 contra 20 de 173. La media no decide nada; deciden los campos concretos que bajan. Overlay desde la Mac: CloudShell no muestra imágenes (Actions → Download file). DetectDocumentText es la operación barata (25 TPS, US$ 0.0015/pág, Oregón aprox.): por eso es el ejercicio masivo. Ejercicio de 2 min: listar solo palabras con Confidence < 90 y luego < 95.

## Slide 8 — Confianza: qué es y qué hacer con ella

*min 28*

- `Confidence` 0–100 por bloque; KEY y VALUE comparten la suya.
- Umbrales que sugiere AWS: ~50 para archivo, ≥ 90 para decisiones financieras.
- `BoundingBox` normalizado 0–1 → píxel = valor × ancho (o alto).
- Tolera rotación en el plano; no corrige perspectiva ni desenfoque.
- Semáforo: ≥ 90 verde · 70–90 ámbar · < 70 rojo.
- Cifras reales del 4-sep-2026 — media WORD: limpia **98.7** · foto **96.2**; media LINE: 98.9 · 97.3. Palabras < 90: **5 de 172** contra **20 de 173**.
- Motivo visual (foto, cifras reales): `2 Monitor 27" 4K` 99.6 % · `700.00` 99.9 % · `VALOR TOTAL 944.84` 99.9 % · y en rojo solo las etiquetas con tilde: `AUTORIZACIÓN` 63.1 % · `Dirección` 71.6 %.
- "La media casi no se mueve (98.7 → 96.2). Lo que decide no es la media: es **qué campos concretos bajan**."

> Notas: 4 min (min 28–32), dentro del Lab 1. Textract resultó mucho más robusto de lo esperado: la foto del celular pierde 2.5 puntos de media WORD, no 20. Lo que sí cambia es la cola: de 5 a 20 palabras por debajo de 90, y esas 20 son casi todas etiquetas con tilde y texto decorativo (AUTORIZACIÓN 63.1, PRODUCCIÓN 66.3, Dirección 71.6), no los montos: 944.84 sale con 99.9 y la clave de acceso con 92.4. Con ≥ 90 en montos e identificadores tomamos decisiones; por debajo, cola de revisión. Remate: un promedio alto no basta como criterio de aceptación — hay que mirar campo por campo, que es lo que hace el validador del Lab 3. Ejercicio de 2 min: listar las palabras por debajo de 95 en la foto y comentar cuáles importan (montos, clave de acceso) y cuáles no (dirección, etiquetas).

## Slide 9 — Lab 2: FORMS + TABLES + LAYOUT (tu único TODO)

*min 35*

```bash
python3 02_formulario_tabla.py docs/factura_limpia.png --csv
python3 02_formulario_tabla.py docs/formulario_inscripcion.png
```

```python
# TODO en 02_formulario_tabla.py (6-8 líneas)
def mi_pares_clave_valor(resp):
    by_id, pares = indice(resp), {}
    for b in resp['Blocks']:
        if (b['BlockType'] == 'KEY_VALUE_SET'
                and 'KEY' in b.get('EntityTypes', [])):
            valor = hijos(b, by_id, tipo='VALUE')[0]
            clave = texto(b, by_id).rstrip(':').strip()
            pares[clave] = texto(valor, by_id)
    return pares
```

- KEY ─VALUE→ VALUE; `EntityTypes` distingue cuál es cuál.
- SELECTION_ELEMENT dentro del VALUE → `[X]` / `[ ]`: "Nivel: Intermedio" → `[X]`.
- TABLE → CELL con `RowIndex` / `ColumnIndex` → `salida/factura_limpia.detalle.csv`.
- LAYOUT sale sin costo extra junto a TABLES.
- Autoverificación: "✔ tu implementación coincide". Si no llegas: `cp checkpoints/lab2/02_formulario_tabla.py .`

> Notas: 11 min (min 35–46). Único momento en que la sala escribe código: ir despacio. Explicar en 1 min KEY/VALUE (EntityTypes, relación VALUE) y CELL (RowIndex/ColumnIndex). Live coding del TODO. Ejecutar sobre factura_limpia: el script compara el TODO con `bloques.pares_clave_valor` e imprime "✔ tu implementación coincide" (si el TODO está vacío usa la librería y avisa). Luego formulario_inscripcion: Track "Workshop OCR" [X], cuenta AWS "Sí" [X], Nivel "Intermedio" [X]. Las claves vienen con ":" y tildes; por eso se normalizan. Llamada cara (US$ 0.065/pág, Oregón aprox.): ejecutar solo 2 veces; el cache evita repetirla.

## Slide 10 — Checkpoint 2: ¿tienes el dict y el CSV?

*min 46*

- Semáforo: verde = dict + CSV listos · ámbar = el TODO no coincide · rojo = nada corre.

```bash
# si no llegaste:
cp checkpoints/lab2/02_formulario_tabla.py .
python3 02_formulario_tabla.py docs/factura_limpia.png --csv
```

- Decisión A: Lab 3 en manos de todos (reloj en hora).
- Decisión B: Lab 3 como demo del ponente (más de 3 min de retraso) y sin bonus.

> Notas: 2 min exactos (min 46–48). Semáforo de manos; anunciar en voz alta la decisión A o B. Si el reloj va más de 3 minutos atrasado: Lab 3 pasa a demo con ejecución opcional y se elimina el bonus. Nunca tocar el Lab 4 corto ni los 3 minutos de cierre.

## Slide 11 — Lab 3: la capa inteligente sin LLM

*min 48*

```bash
python3 03_inteligente.py docs/factura_limpia.png     # → OK
python3 03_inteligente.py docs/factura_trampa.png     # → REVISAR
```

```python
# 03_inteligente.py (núcleo)
from textract_lab.queries import QUERIES_FACTURA   # 7, ASCII
resp_q = llamar('analyze_document', doc,
                feature_types=['QUERIES'], queries=QUERIES_FACTURA)
resp_f = llamar('analyze_document', doc,   # cache Lab 2
                feature_types=['FORMS', 'TABLES', 'LAYOUT'])
campos = respuestas_queries(resp_q)              # alias → Campo
forms = pares_clave_valor(resp_f)        # etiqueta → Campo
# por cada campo gana la fuente con mayor confianza (origen)
alertas = validar_factura(campos, tablas(resp_f))
print(estado_final(alertas), alertas)
```

- Queries en inglés y ASCII: `'What is the RUC of the issuer?'` → `RUC_EMISOR`; `'What is the CLAVE DE ACCESO?'` → `CLAVE_ACCESO` (7 en total).
- Las **7 queries en inglés SÍ respondieron** sobre la factura en español: RUC 99.0 · NUM_FACTURA 97.0 · FECHA_EMISION 98.0 · SUBTOTAL_15 96.0 · IVA_15 99.0 · VALOR_TOTAL 98.0. Funcionó, pero está **fuera del soporte oficial**: por eso no dependemos de una sola fuente.
- Llamada separada de US$ 0.015/pág (Oregón, aprox.); FORMS+TABLES se reutiliza del cache.
- `Campo(valor, confianza, origen)`: la fuente con mayor confianza gana. Competencia real en `factura_limpia`:

```text
# quién compitió por cada campo (gana la mayor confianza)
VALOR_TOTAL    QUERIES 98.0 · FORMS 95.2 · TABLES 91.0  → gana QUERIES
CLAVE_ACCESO   QUERIES 83.0 · FORMS 95.0               → gana FORMS
```

- Validadores: módulo 11 (RUC, clave de 49 dígitos), módulo 10 (cédula), regex `001-001-000001234`, fecha dd/mm/aaaa, ítems = subtotal, subtotal × 0.15 = IVA, suma = total, confianza ≥ 90.
- "En el campo más largo (49 dígitos) Queries baja y **gana FORMS**. Esa es la razón de combinar fuentes, no la teoría."

> Notas: 7 min (min 48–55). Mostrar `textract_lab/queries.py` (7 queries, alias en MAYÚSCULAS ASCII, "FECHA EMISION" sin tilde a propósito) y explicar en 30 s por qué inglés y ASCII (el patrón de `Query.Text` rechaza tildes y ¿). Dato real que es el oro de la slide: las 7 queries escritas en inglés respondieron todas sobre un documento en español — la documentación dice "solo inglés", así que funcionó pero fuera del soporte oficial. Y justo por eso no apostamos a una sola fuente: en `factura_limpia` Queries gana casi todo, pero en `CLAVE_ACCESO` (los 49 dígitos) Queries cae a 83.0 y FORMS lo lee con 95.0; gana FORMS. También `SUBTOTAL_SIN_IMPUESTOS` y `PROPINA` los aporta FORMS, porque Queries ni los pide. En la foto ese mismo campo cae a 73.0 en Queries: el campo largo es siempre el más frágil, y el `origen` del `Campo` deja rastro de quién ganó. En offline el set de queries es fijo (el script lo avisa). Ejercicio de 2 min: `fecha_no_futura(campos)` en `VALIDADORES_EXTRA`.

## Slide 12 — factura_trampa: validar el negocio, no solo el OCR

*min 52*

- Fragmento con todas las cajas verdes (confianzas reales): ítem 2 con Precio Total **95.60** a 99.8 % (debería ser 85.60) · SUBTOTAL 15% **821.60** a 99.9 % (los ítems suman 831.60) · clave de acceso terminada en **4** a 94.8 % (dv inválido). Media WORD 98.7 y **0 alertas de confianza**: el OCR no falló.

```json
// salida/factura_trampa.validado.json (fixture real 2026-09-04, en el orden en que las imprime el script)
{ "estado": "REVISAR",
  "alertas": [
    "clave de acceso con dígito verificador inválido (esperado 3, leído 4)",
    "ítems no suman el subtotal: ítems 831.60 vs SUBTOTAL 821.60" ] }
```

- "Confianza casi perfecta y el documento igual está mal. **Ninguna métrica del OCR habría atrapado esto**: lo atrapan las reglas de negocio."
- Ejercicio: agrega `fecha_no_futura()` a `VALIDADORES_EXTRA`. Human-in-the-loop = estado REVISAR + tu propia cola (A2I en mantenimiento desde julio 2026).

> Notas: 3 min (min 52–55), dentro del Lab 3. Este es el momento fuerte del taller. Transparencia: "estos dos errores los puse yo en el documento: el ítem 2 dice 95.60 en vez de 85.60 y la clave termina en 4 en vez de 3". Señalar que Textract leyó los dos errores *perfectamente* — 99.8 y 99.9 en los montos, 94.8 en la clave — y que ese es el punto: un OCR impecable no dice nada sobre si el documento es correcto. Mensaje: OCR + validación determinista = sistema inteligente sin LLM. Como contraste, `python3 03_inteligente.py docs/factura_foto.jpg` (o factura_foto_real.jpg): con los fixtures reales sale **OK con 0 alertas**. Si la foto del sábado trae alguna alerta de confianza baja, mejor todavía; si no, el contraste sigue funcionando: la foto pasa, la trampa no.

## Slide 13 — Lab 4: esto es un sistema

*min 55*

```bash
python3 04_sistema.py docs/        # solo cache/fixtures; --online para llamar
```

```python
# textract_lab/etapas.py
ETAPAS = [texto, estructura, consultas, clasificar_etapa, validar, salida]

def procesar_documento(documento, modo=None, con_queries=True):
    ctx = {'documento': documento, 'modo': modo, 'con_queries': con_queries}
    for etapa in ETAPAS:
        ctx = etapa(ctx)          # cada etapa recibe y devuelve ctx
    return ctx['resultado']       # Resultado(tipo, campos, alertas, estado)
```

| documento | tipo | estado | alertas | US$ |
|---|---|---|---|---|
| factura_limpia | factura | OK | 0 | 0.00 |
| factura_trampa | factura | REVISAR | 2 | 0.00 |
| factura_foto | factura | OK | 0 | 0.00 |
| formulario_inscripcion | formulario | OK | 0 | 0.00 |
| orden_compra_prosa | desconocido | REVISAR | 1 | 0.00 |
| mini | desconocido | REVISAR | 1 | 0.00 |

- Resumen real (fixtures reales grabados el 4-sep-2026): `✔ 3 OK · 3 REVISAR · 0 SIN DATOS`. `mini.png` (4 líneas sin RUC ni checkbox) sale `desconocido → REVISAR`: así se ve un documento sin patrón conocido.

- Dataclasses `Campo(valor, confianza, origen)` y `Resultado`. Puntos de extensión: cola de revisión (REVISAR), base de datos, LLM o BDA en `clasificar` o en una etapa nueva.

> Notas: 4 min (min 55–59): ejecutar y señalar. Un pipeline es una lista de funciones ctx → ctx. `clasificar.py` es trivial a propósito (SELECTION_ELEMENT → formulario, "CLAVE DE ACCESO" → factura, nada → desconocido); el valor está en que el resto no cambia al reemplazarlo. Anticipar "¿por qué mini sale REVISAR?": no es factura ni formulario, y un tipo desconocido siempre va a revisión. Cómo leer la tabla: 3 OK · 3 REVISAR — las dos facturas bien formadas pasan, incluida la foto del celular con 0 alertas, y a revisión van solo la trampa (errores reales del documento) y los dos documentos de tipo desconocido; ese reparto es el que uno quiere en producción. Señalar la última línea: "Costo estimado de esta corrida: US$ 0.00 (todo desde cache/fixtures)". Mostrar `salida/resumen.json`. Quien va atrasado igual puede correrlo: usa la librería.

## Slide 14 — Bonus: Textract extrae, Bedrock razona

*min 59*

```python
# textract_lab/bedrock.py — Converse con salida estructurada (Claude Haiku 4.5)
MODELO = 'us.anthropic.claude-haiku-4-5-20251001-v1:0'   # nunca el ID base en us-east-1
resp = client.converse(
    modelId=MODELO,
    system=[{'text': SYSTEM_PROMPT_ES}],                  # "no inventes; vacío + alerta"
    messages=[{'role': 'user', 'content': [{'text': texto_y_campos}]}],
    inferenceConfig={'temperature': 0, 'maxTokens': 1024},
    outputConfig={'textFormat': {'type': 'json_schema', 'structure': {
        'jsonSchema': {'name': 'documento', 'schema': json.dumps(SCHEMA_DOCUMENTO)}}}})
salida = json.loads(resp['output']['message']['content'][0]['text'])
alertas += validar_factura(salida_como_campos, tablas)   # el LLM propone, el módulo 11 dispone
```

- Fallback: `amazon.nova-lite-v1:0` con `toolConfig` + `toolChoice` forzado (Nova no soporta structured outputs).
- Costo por factura ≈ US$ 0.003 con Haiku 4.5 (`usage` en pantalla; precios de Bedrock aprox., confirmar).

> Notas: 5 min (min 59–64). Primera candidata a recorte. Teclear `python3 05_bonus_bedrock.py docs/orden_compra_prosa.png` y luego `python3 05_bonus_bedrock.py docs/factura_foto.jpg` (o factura_foto_real.jpg). Si tarda > 20 s o falla: `--modelo nova`; si falla: `--offline`. Nunca depurar en escena. Los asistentes necesitan el formulario de caso de uso de Anthropic y una suscripción de Marketplace de hasta 15 min: `bonus/README.md` para casa. El esquema se precalienta con `tools/precalentar_esquema.py`. Vía de escape: bedrock-mantle no exige el formulario pero requiere el SDK anthropic; no lo usamos.

## Slide 15 — Sobre prosa, Queries se equivoca con seguridad

*min 61*

```text
# orden_compra_prosa.png (prosa) — fixture real
Queries → PROVEEDOR      'Gerente de Compras'  60.0 ✗
          CANT_MONITORES '27'                  99.0 ✗
          TOTAL_COMPRA   sin respuesta              ✓
# ✗ 'Gerente de Compras' = el cargo del firmante
# ✗ 27 son las pulgadas; la cantidad es 3
# ✓ el total 1221.20 no está escrito: hay que sumarlo
LLM → {"emisor": "Tecnología Andina Ejemplo S.A.",
       "items": [{"descripcion": "monitor 27", "cantidad": 3, "precio_unitario": 350.00}, …],
       "total": 1221.20, "moneda": "USD", "alertas": []}
# y aun así: el total del LLM pasa por validar_factura antes de creerle
```

| Necesidad | Herramienta | US$/pág |
|---|---|---|
| Campo con etiqueta conocida | Queries / FORMS | 0.015 / 0.05 |
| Tabla | TABLES | 0.015 |
| Checkbox | SELECTION_ELEMENT (FORMS) | 0.05 |
| Prosa, pregunta en español, normalizar, explicar | LLM sobre texto linealizado | ≈ 0.003 (confirmar) |
| Muchos tipos con esquema propio, sin código | Bedrock Data Automation | ≈ 0.01–0.04 (confirmar) |

- Una respuesta **incorrecta con 99 % de confianza** es peor que no responder. OCR determinista primero; LLM solo donde aporta; **el LLM tampoco decide solo**. Tarifa Oregón, aprox.

> Notas: 2 min (min 61–63). Dato real, no lo suavices: esperábamos que sobre una carta en prosa las tres queries se quedaran vacías, y no pasó eso. `PROVEEDOR` devolvió "Gerente de Compras" con 60 % — es el cargo de quien firma la carta, María José Cabrera, y encima del lado del comprador, no del proveedor (Tecnología Andina Ejemplo S.A.). `CANT_MONITORES` devolvió "27" con **99 %** — 27 son las pulgadas del monitor; la cantidad es 3. Solo `TOTAL_COMPRA` se abstuvo, y correctamente, porque el total 1221.20 no está escrito: hay que calcularlo. Titular: sobre prosa Queries no dice "no sé"; responde con seguridad y se equivoca. Esa combinación — incorrecto y 99 % de confianza — es el mejor argumento del taller para (a) cuándo hace falta un LLM y (b) por qué el LLM tampoco decide solo y todo pasa por los validadores. Advertir además que una "corrección" del LLM puede pasar módulo 11 y aun así ser falsa: por eso toda corrección se etiqueta como alerta para un revisor humano. Mostrar `fixtures/orden_compra_prosa/analyze_document__QUERIES__*.json` (las respuestas con su confianza) y `fixtures/bedrock/orden_compra_prosa__haiku.json` (request, respuesta y usage).

## Slide 16 — Textract hoy (sep-2026) frente a BDA y LLM multimodal

*min 63*

| | Textract | Bedrock Data Automation | LLM multimodal |
|---|---|---|---|
| US$/pág | 0.0015 texto · 0.065 forms+tables | ≈ 0.01 estándar · 0.04 custom (confirmar) | ≈ 0.003–0.01 según tokens (confirmar) |
| Determinista | sí | parcial | no |
| Geometría + confianza por palabra | sí | por campo (confirmar) | no |
| Español impreso / manuscrito | sí / solo inglés | sí / sí (confirmar) | sí / sí |
| Alucinación | no | posible | posible |
| Cuándo | campos etiquetados, tablas, checkboxes | muchos tipos, esquema propio, sin código | prosa, ambigüedad, explicación |

- Textract: sin anuncio de mantenimiento al 2-sep-2026 (confirmar); última mejora del modelo jun-2025 (0 vs O, texto rotado). A2I sí está en mantenimiento. AWS recomienda BDA "para la mayoría de casos" de IDP y Textract + LLM para lógica propia. Ni Textract ni BDA están en sa-east-1. Tarifa Oregón, aprox.

> Notas: máximo 2 min (min 63–64); no abrir debate. Respuesta preparada a "¿por qué me enseñas Textract y no un LLM multimodal?": OCR barato (US$ 0.0015/pág texto), determinista, con geometría y confianza por palabra, español impreso soportado; y la capa propia que construimos hoy (Campo, validadores, ETAPAS) se alimenta igual de BDA o de un LLM mañana sin reescribir nada.

## Slide 17 — Cierre: costo real, seguridad y tarea para casa

*min 64*

```bash
python3 00_check.py   # costo acumulado de la sesión
cat cache/.costos.json   # {"llamadas": 8, "usd": 0.23}
```

- ≈ US$ 0.23 por persona en online · US$ 0 en offline (tarifa Oregón, aprox.).
- Dato real: grabar los fixtures de los 6 documentos costó **US$ 0.3955 en 16 llamadas** (us-east-1, 4-sep-2026). Todo el taller corre sobre esas respuestas, sin gastar un centavo más.
- **Borra ahora** las claves temporales que hayas creado. Free tier: 100 págs/mes de AnalyzeDocument en cuentas nuevas.
- Tarea para casa: `extra/06_expense.py` (AnalyzeExpense, solo inglés oficial) · `extra/07_async_s3.py` (Start/Get con S3 en us-east-1 y NextToken) · `extra/08_textractor.py` (textractor 1.10: to_pandas, to_markdown) · `bonus/README.md` (habilitar Bedrock) · `pytest tests/` corre 100 % offline.

> Notas: 3 min (min 64–67). Insistir en borrar claves y en el presupuesto (AWS Budgets se actualiza cada 8-12 h: no frena gasto en tiempo real). Recordar los límites honestos en una frase: sync 1 pág / 10 MB; queries, manuscrito y expense solo inglés; AnalyzeID no sirve para cédulas. Mostrar el costo real de la sesión; última llamada al QR; repartir el cheat sheet impreso. Ojo con tu propio `cache/.costos.json`: en tu laptop acumula lo del ensayo, así que puede imprimir `$0.3955 (aprox.)` con 16 llamadas — es exactamente lo que costó grabar los fixtures reales. No lo escondas: dilo como dato, "el taller entero costó menos de 40 centavos".

## Slide 18 — Gracias — preguntas

*min 67*

- QR gigante otra vez → `github.com/jossuema/textract-ec` · `github.com/jossuema/textract-ec`.
- Manuel Josue · AWS User Group Ecuador · `github.com/jossuema`.
- "Las preguntas largas, en el pasillo." El auditorio se necesita a las 16:10.

> Notas: 3 min (min 67–70): 2-3 preguntas cortas. Invitar a continuar en el pasillo y en el canal del AWS User Group Ecuador. Recoger la factura impresa y los cheat sheets sobrantes. Cerrar CloudShell. Pendiente: reemplazar QR, `github.com/jossuema/textract-ec` y `github.com/jossuema`.
