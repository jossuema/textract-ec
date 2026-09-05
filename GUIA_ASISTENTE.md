# Guía del asistente — paso a paso

> **¿Prefieres un notebook?** `notebooks/taller.ipynb` trae estos mismos 4 labs en celdas, con el overlay de confianza **en línea**. Funciona en Jupyter, VS Code y Google Colab, y va en modo offline por defecto: no necesita credenciales. Los pasos de esta guía valen igual para el notebook; solo cambia que ahí ejecutas celdas en vez de scripts.

Pensada para leerla desde el celular mientras tu pareja teclea. Cada lab tiene: el comando, qué mirar en la salida, una pregunta guía y cómo recuperarte si algo falla. Todos los comandos se ejecutan desde la raíz del repo (`cd textract-ec`).

Regla de oro: **si ves rojo, agrega `--offline` y sigue**. El código de parseo es el mismo; solo cambia de dónde sale el JSON. Si no tienes cuenta AWS, ejecuta una vez `export LAB_MODO=offline` y olvídate del flag.

Las salidas de ejemplo de cada paso (PNG, CSV, JSON) están en `docs/salidas/` por si no puedes ejecutar nada.

---

## Checkpoint 0 (minuto 10) — ¿cuenta, región y modo?

```bash
git clone --depth 1 https://github.com/jossuema/textract-ec.git && cd textract-ec
python3 00_check.py
```

**Qué mirar:**

1. Primera línea: el banner. `[ONLINE us-east-1 · perfil personal]` (o el nombre de tu perfil) si tienes credenciales; `[OFFLINE · fixtures reales grabados 2026-09-04]` si no. Esos fixtures son respuestas reales de Textract (16 llamadas grabadas el 4-sep-2026 en us-east-1): en offline ves exactamente lo mismo que vería tu cuenta.
2. `Python 3.10+` y `boto3 1.43.x`.
3. En ONLINE: `cuenta: 123456789012`, `identidad: arn:aws:…`, `region: us-east-1`, y las 4 líneas de `docs/mini.png` leídas con tildes y ñ (`¿Funciona el español? Sí: ñ, á, é, í, ó, ú`).
4. En OFFLINE: `✔ MANIFEST OK: 20 archivos con el hash esperado` y el contenido de `fixtures/META.json` (`origen: reales (textract)`, `generados: 2026-09-04`).
5. La última palabra: **LISTO**. Levanta la mano verde.

**Si algo falla:**

- Aviso amarillo "sin credenciales" → no es un error; sigue en offline.
- Línea roja con `AccessDeniedException`, `EndpointConnectionError` u otra excepción → `python3 00_check.py --offline`. Después del taller, revisa `iam/textract-workshop-policy.json` o tu red.
- CloudShell no abre (`Timed out while opening the session`) → laptop propia (`bash scripts/setup_local.sh && source .venv/bin/activate && export AWS_PROFILE=<perfil> && python3 00_check.py`; el `source` es obligatorio: boto3 queda instalado dentro de `.venv`) o pairing.

**Pregunta guía:** ¿por qué el script puede imprimir tu account id aunque tu usuario no tenga ningún permiso de IAM? (Pista: `sts:GetCallerIdentity`.)

Opcional, solo si quieres el overlay del Lab 1: `python3 -m pip install --user pillow` (el mismo intérprete que corre los labs; unos 20 s; si el wifi no coopera, sáltalo). Si responde `error: externally-managed-environment` (Homebrew python@3.12+, Debian/Ubuntu recientes): `python3 -m pip install --user --break-system-packages pillow`, o `bash scripts/setup_local.sh --extra` (instala en `.venv`), o simplemente mira los overlays ya generados en `docs/salidas/`.

---

## Lab 1 (minuto 22) — texto y confianza

```bash
python3 01_texto.py docs/factura_limpia.png
python3 01_texto.py docs/factura_foto.jpg --overlay
```

**Qué mirar:**

1. Cada línea del documento con su `Confidence` y un punto de color: verde >= 90, amarillo 70–90, rojo < 70.
2. `confianza media` al final: limpia `LINE 98.9 · WORD 98.7`; foto `LINE 97.3 · WORD 96.2`. La foto baja, pero **mucho menos de lo que uno esperaría**: Textract es robusto con una foto de celular.
3. `palabras < 90: n`: limpia **5 de 172** (la peor, el teléfono `07 283 4567` con 75.9); foto **20 de 173** (la peor, una `I` suelta con 29.1, y varias palabras con tilde: `AUTORIZACIÓN` 63.1, `PRODUCCIÓN` 66.3). Ahí sí se ve la degradación: no en la media, sino en la cola.
4. Con `--overlay` y Pillow instalado: `salida/factura_foto.overlay.png` con cajas de colores. En CloudShell descárgalo con **Actions → Download file**; si no tienes Pillow verás `overlay omitido` y puedes mirar `docs/salidas/factura_foto.overlay.png`.
5. Prueba `--json`: guarda la respuesta cruda en `salida/factura_limpia.texto.json` y te muestra un bloque `LINE` con `Relationships` → `CHILD` y su primer `WORD` con `Confidence` y `Geometry.BoundingBox`. Eso es todo el modelo mental del taller: **los hijos no conocen a su padre**, así que se construye un índice `by_id` y se navega de arriba hacia abajo.

**Ejercicio (2 min):** con la salida de la foto, lista solo las palabras con confianza < 90. ¿Cuáles son? ¿Son dígitos de montos o de la clave de acceso? Si tu proceso fuera financiero, AWS sugiere no aceptar nada por debajo de 90 sin revisión humana.

**Pregunta guía:** ¿qué cambió entre la factura limpia y la foto para que la confianza caiga? (Resolución, desenfoque, brillo desigual: Textract corrige rotación pero no perspectiva ni blur.)

**Si te atrasas:** `cp checkpoints/lab1/01_texto.py .` y ejecuta igual.

---

## Lab 2 (minuto 35) — formularios, checkboxes y tablas: tu único TODO

```bash
python3 02_formulario_tabla.py docs/factura_limpia.png --csv
python3 02_formulario_tabla.py docs/formulario_inscripcion.png
```

Antes de ejecutar, abre `02_formulario_tabla.py` (en CloudShell: `nano 02_formulario_tabla.py` o el editor integrado) y busca `def mi_pares_clave_valor(resp):  # TODO`. Tienes que devolver un diccionario `clave → valor` a partir de la respuesta cruda. El script se autoverifica: si tu función lanza `NotImplementedError` o devuelve vacío, usa la versión de la librería y te avisa; si devuelve algo, lo compara con `textract_lab.bloques.pares_clave_valor` e imprime `✔ tu implementación coincide` o las diferencias.

**Pista (6–8 líneas):**

1. Construye el índice: `by_id = bloques.indice(resp)`.
2. Recorre `resp['Blocks']` y quédate con los `BlockType == 'KEY_VALUE_SET'` cuyo `EntityTypes` contenga `'KEY'`.
3. Para cada KEY, su VALUE está en `bloques.hijos(key, by_id, 'VALUE')` (relación de tipo `VALUE`; toma el primero).
4. El texto de cada bloque sale de `bloques.texto(bloque, by_id)` (une los `WORD` hijos; los `SELECTION_ELEMENT` salen como `[X]` / `[ ]`).
5. Guarda `kv[texto_clave] = texto_valor` y devuelve `kv`. Limpia la clave con `.strip()` y quítale el `:` final para que coincida con la librería.

**Qué mirar:**

1. `✔ tu implementación coincide` (o el aviso de que se usó la librería).
2. El dict impreso: `RUC` → `1790456129001`, `No.` → `001-001-000001234` (la palabra `FACTURA` es un título aparte: sale como `LAYOUT_TITLE`, no como clave), `FECHA EMISION` → `01/09/2026`, `VALOR TOTAL` → `944.84`. Fíjate en que las claves del documento traen `:` y tildes: por eso se normalizan.
3. La tabla de detalle con sus 3 ítems (Monitor 27" 4K Ejemplo · Teclado mecánico ES · Cable HDMI 2.1 2m) y el archivo `salida/factura_limpia.detalle.csv` (ábrelo con `cat`).
4. El conteo de bloques por tipo (`resumen_bloques`): LAYOUT_* aparece sin costo extra porque pedimos TABLES.
5. En `formulario_inscripcion.png` cada casilla es un par propio (16 pares en total): `Intermedio` → `[X]`, `Principiante` → `[ ]`, `Avanzado` → `[ ]`, `Sí` → `[X]`; debajo, la sección `Checkboxes (SELECTION_ELEMENT: 8, marcados 3)`. Las cabeceras `Nivel:` y `¿Tienes cuenta AWS?:` no son claves: aparecen como `LAYOUT_TITLE`. Los checkboxes son bloques `SELECTION_ELEMENT` con `SelectionStatus` dentro del VALUE.

**Pregunta guía:** ¿por qué KEY y VALUE comparten la misma `Confidence`? ¿Qué pasa con la clave `Firma:` que no tiene valor escrito?

**Si te atrasas:** `cp checkpoints/lab2/02_formulario_tabla.py .` (TODO resuelto) y ejecuta igual: el mensaje `✔` te confirma que la solución coincide. Esta es la llamada cara en online (US$ 0.065/página): ejecútala una vez por documento; la segunda vez sale de `cache/`.

---

## Lab 3 (minuto 48) — la capa inteligente sin LLM

```bash
python3 03_inteligente.py docs/factura_limpia.png
python3 03_inteligente.py docs/factura_trampa.png
```

**Qué mirar:**

1. Abre `textract_lab/queries.py`: 7 queries en inglés y ASCII puro (`What is the CLAVE DE ACCESO?`, `What is the FECHA EMISION date?` sin tilde a propósito) con alias en MAYÚSCULAS. Textract rechaza `¿`, tildes y `ñ` en las queries, y Queries está documentado solo para inglés: por eso incluimos la etiqueta literal del documento y combinamos con FORMS. Dato real del 4-sep-2026: sobre esta factura **en español las 7 respondieron**. Funcionó, pero sigue estando fuera del soporte oficial: no es una garantía, es un motivo más para no depender de una sola fuente.
2. El script pide solo `QUERIES` (US$ 0.015/página) y reutiliza FORMS+TABLES+LAYOUT del Lab 2 desde `cache/` (en offline, desde `fixtures/`). En online, si no corriste el Lab 2 sobre ese documento, avisa en amarillo (`no está en cache/: se pedirá UNA sola vez a Textract`) y lo pide una vez (US$ 0.065/página) sin preguntar; queda en `cache/` y no se repite.
3. La tabla de campos: cada uno con `valor`, `confianza` y `origen` (`QUERIES`, `FORMS` o `TABLES`), y debajo **quién compitió por cada campo**. Con los fixtures reales, sobre `factura_limpia` las 7 queries respondieron (aunque Queries está documentado solo para inglés) y ganan casi todos los campos… salvo el más largo: `CLAVE_ACCESO  QUERIES 83.0 · FORMS 95.0 → gana FORMS`. Ese es el motivo real de combinar fuentes. `SUBTOTAL_SIN_IMPUESTOS` y `PROPINA` también los aporta FORMS, porque ninguna query los pide. Eso es `Campo{valor, confianza, origen}`.
4. `factura_limpia` → estado **OK**, `alertas: []`.
5. `factura_trampa` → estado **REVISAR** con exactamente dos alertas, literalmente: `clave de acceso con dígito verificador inválido (esperado 3, leído 4)` e `ítems no suman el subtotal: ítems 831.60 vs SUBTOTAL 821.60` (el ítem 2 dice 95.60 en vez de 85.60). El OCR leyó perfecto — de hecho leyó el dígito equivocado con toda claridad; el error está en el documento. Validar el negocio, no solo el OCR.
6. `salida/<doc>.validado.json` con `estado`, `campos` y `alertas`.

Validadores que corren (`textract_lab/validadores.py`, todo con `Decimal`): RUC de 13 dígitos con módulo 11; número de factura `^\d{3}-\d{3}-\d{9}$`; clave de acceso de 49 dígitos con módulo 11 (pesos cíclicos 2..7 de derecha a izquierda); fecha `dd/mm/aaaa` válida y no futura; `SUBTOTAL 15% × 0.15 = IVA 15%`; `SUBTOTAL + IVA + PROPINA = VALOR TOTAL`; suma de `Precio Total` de la tabla = subtotal (tolerancia 0.01); confianza < 90 en montos e identificadores → alerta.

**Ejercicio (2 min):** ejecuta `python3 03_inteligente.py docs/factura_foto.jpg`. Sorpresa: la foto sale **OK, 0 alertas**, y su `CLAVE_ACCESO` también la gana FORMS (95.2) sobre QUERIES (73.0). Compara sus alertas con las de `factura_trampa`: en la foto el riesgo estaba en el OCR y Textract lo resolvió; en la trampa el OCR es perfecto y el error está en el documento. ¿Cuál de los dos casos te preocuparía más en producción?

**Pregunta guía:** si `VALOR_TOTAL` llegara con confianza 71 pero cuadrara con subtotal + IVA, ¿lo aceptarías? ¿Qué regla escribirías? (En estos fixtures no ocurre: el total se lee con 98.0. La regla tiene que existir igual, para el día que ocurra.)

**Si te atrasas:** `cp checkpoints/lab3/03_inteligente.py .`. Si el ponente anuncia "Lab 3 como demo", míralo en pantalla y ejecútalo en casa: en offline funciona exactamente igual.

---

## Lab 4 (minuto 55) — esto es un sistema

```bash
python3 04_sistema.py docs/
```

**Qué mirar:**

1. `04_sistema.py` son pocas líneas: la lista `ETAPAS = [texto, estructura, consultas, clasificar_etapa, validar, salida]` y un bucle `for etapa in ETAPAS: ctx = etapa(ctx)`. Cada etapa recibe y devuelve un diccionario de contexto; el resultado es un `Resultado` con `tipo_documento`, `campos`, `tablas`, `alertas`, `estado`, `paginas`, `costo_usd`.
2. La tabla (6 filas, en orden alfabético): `factura_foto · factura · OK · 0`, `factura_limpia · factura · OK · 0`, `factura_trampa · factura · REVISAR · 2`, `formulario_inscripcion · formulario · OK · 0`, `mini · desconocido · REVISAR · 1` (4 líneas sin RUC ni checkbox: así se ve un documento sin patrón conocido) y `orden_compra_prosa · desconocido · REVISAR · 1`. Resumen: `3 OK · 3 REVISAR · 0 SIN DATOS`. Un documento sin fixture ni cache aparece como `SIN DATOS`.
3. `salida/resumen.json` y `salida/<doc>.validado.json`.
4. La línea final de costo: US$ 0.00, porque todo sale de `cache/` y `fixtures/` (solo `--online` llama a AWS).
5. `textract_lab/clasificar.py` decide el tipo por evidencia (`CLAVE DE ACCESO`/`FACTURA`/`RUC` → factura; `SELECTION_ELEMENT` o `Inscripción` → formulario; nada → desconocido). Es Python puro y trivial a propósito: en producción se reemplaza por reglas más ricas, un LLM o Bedrock Data Automation sin tocar el resto.

**Pregunta guía:** ¿dónde enchufarías una cola de revisión humana? ¿Y una base de datos? (Pista: una etapa nueva al final de `ETAPAS`, o el estado `REVISAR`.)

Aunque no hayas terminado los Labs 2 y 3, este lab corre igual porque usa las funciones de la librería.

---

## Bonus (minuto 59, demo del ponente) — Bedrock razona sobre lo que Textract extrajo

Solo observa; puedes ejecutar la versión offline en tu máquina:

```bash
python3 05_bonus_bedrock.py docs/orden_compra_prosa.png --offline
python3 05_bonus_bedrock.py docs/factura_foto.jpg --offline --modelo nova
```

**Qué mirar:**

1. Sobre `orden_compra_prosa.png` (una carta en prosa, sin etiquetas ni tabla) las 3 queries fallan de la peor manera posible: `PROVEEDOR` → `Gerente de Compras` con **60.0** (es el cargo de quien firma la carta, del lado del comprador), `TOTAL_COMPRA` → sin respuesta (correcto: el total no está escrito, hay que calcularlo) y `CANT_MONITORES` → `27` con **99.0**… que son las pulgadas del monitor, no la cantidad (son 3). Sobre prosa, Queries no dice "no sé": **responde con seguridad y se equivoca**. El LLM, leyendo el texto que extrajo `DetectDocumentText`, devuelve los tres bien: Tecnología Andina Ejemplo S.A., 3 monitores, total 1221.20.
2. Sobre `factura_foto.jpg`: el LLM normaliza (fecha ISO, montos) y explica cada alerta en español; después, su JSON **vuelve a pasar por los validadores**: cualquier diferencia con lo que Textract ya validó saldría como alerta `el LLM cambió X: a → b`. Con esta foto no cambió nada (`revalidado por módulo 11: OK`). "El LLM propone, el módulo 11 dispone". Ojo: los fixtures de Bedrock son los únicos que siguen siendo **sintéticos**, y el texto que el modelo devuelve ahí menciona alertas (una `O` por `0`, un total con confianza 71) que los fixtures reales de Textract ya no producen; el script avisa `fixture SINTÉTICO, no salió de Bedrock`.
3. `usage` (tokens de entrada/salida) y el costo aproximado: menos de medio centavo por factura con Haiku 4.5.
4. `fixtures/bedrock/<doc>__<modelo>.json` contiene el request completo (system prompt en español, mensaje, esquema JSON) y la respuesta: léelo para ver exactamente qué se le pidió al modelo.

Para ejecutarlo en online en tu cuenta necesitas preparación previa (formulario de caso de uso de Anthropic, método de pago, política IAM): está todo en [`bonus/README.md`](bonus/README.md).

---

## Cierre (minuto 64)

```bash
python3 00_check.py --costo
```

Muestra las páginas consumidas y el costo estimado de tu sesión (≈ US$ 0.23 si hiciste todo en online; US$ 0 en offline). Antes de irte: si creaste claves de acceso IAM para hoy, elimínalas o rótalas; cierra CloudShell; escanea el QR final.

Para seguir en casa: `extra/`, `bonus/README.md`, `python3 -m pytest -q` (tests sin red) y `CHEATSHEET.md`.
