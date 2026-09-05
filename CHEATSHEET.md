# CHEATSHEET · textract-ec (1 página)

**Repo** `https://github.com/jossuema/textract-ec` · **URL corta** `<URL-CORTA>` · **Región** `us-east-1` · **Modo** `--offline` / `--online` (sin flag: automático) · offline = respuestas **reales** de Textract grabadas el 4-sep-2026 (`[OFFLINE · fixtures reales grabados 2026-09-04]`)

## Comandos

```bash
git clone --depth 1 https://github.com/jossuema/textract-ec.git && cd textract-ec
python3 00_check.py                                        # checkpoint 0 → LISTO   (--costo al final)
python3 01_texto.py docs/factura_limpia.png [--overlay]     # Lab 1  DetectDocumentText
python3 02_formulario_tabla.py docs/factura_limpia.png --csv   # Lab 2  FORMS+TABLES+LAYOUT (TODO)
python3 03_inteligente.py docs/factura_trampa.png          # Lab 3  QUERIES + validadores → REVISAR
python3 04_sistema.py docs/                                # Lab 4  lote sobre cache/fixtures, $0
python3 05_bonus_bedrock.py docs/orden_compra_prosa.png --offline   # bonus (--modelo haiku|nova)
cp checkpoints/lab2/02_formulario_tabla.py .               # recuperarte (lab1, lab2, lab3)
```

## BlockTypes (la respuesta es un grafo: los hijos no conocen a su padre)

| BlockType | Qué es | Campos que importan |
|---|---|---|
| `PAGE` | raíz | `Relationships CHILD` → LINE, KEY_VALUE_SET, TABLE, QUERY |
| `LINE` → `WORD` | texto | `Text`, `Confidence` 0–100, `Geometry.BoundingBox` (0–1), `TextType` PRINTED/HANDWRITING |
| `KEY_VALUE_SET` | par de formulario | `EntityTypes` `['KEY']`/`['VALUE']`; KEY → `VALUE` → bloque VALUE; ambos → `CHILD` → WORD |
| `SELECTION_ELEMENT` | checkbox | `SelectionStatus` SELECTED / NOT_SELECTED (dentro de un VALUE o CELL) |
| `TABLE` → `CELL` | tabla | `RowIndex`, `ColumnIndex` (desde 1), `EntityTypes` COLUMN_HEADER; `MERGED_CELL` |
| `QUERY` → `QUERY_RESULT` | pregunta | `Query.Alias`; relación `ANSWER`; sin `ANSWER` = sin respuesta |
| `LAYOUT_*` | secciones | TITLE, HEADER, TEXT, TABLE, KEY_VALUE… (gratis con TABLES) |

## El patrón (todo el parseo cabe aquí)

```python
by_id = {b['Id']: b for b in resp['Blocks']}                       # 1. índice
def hijos(b, tipo='CHILD'):                                         # 2. navegar top-down
    return [by_id[i] for r in b.get('Relationships', [])
            if r['Type'] == tipo for i in r['Ids']]
def texto(b):                                                       # 3. texto de un bloque
    return ' '.join(h['Text'] if h['BlockType'] == 'WORD' else
                    ('[X]' if h.get('SelectionStatus') == 'SELECTED' else '[ ]')
                    for h in hijos(b))
kv = {texto(k).rstrip(':'): texto(hijos(k, 'VALUE')[0])            # 4. pares clave-valor
      for k in resp['Blocks'] if k['BlockType'] == 'KEY_VALUE_SET' and 'KEY' in k['EntityTypes']}
```

En la librería: `bloques.indice`, `bloques.hijos(b, by_id, tipo)`, `bloques.texto(b, by_id)`, `bloques.lineas`, `bloques.pares_clave_valor`, `bloques.tablas`, `bloques.respuestas_queries`, `bloques.selecciones`.

## Llamadas (boto3)

```python
tx = boto3.client('textract', region_name='us-east-1',
                  config=Config(retries={'total_max_attempts': 10, 'mode': 'standard'}))
tx.detect_document_text(Document={'Bytes': data})
tx.analyze_document(Document={'Bytes': data}, FeatureTypes=['FORMS', 'TABLES', 'LAYOUT'])
tx.analyze_document(Document={'Bytes': data}, FeatureTypes=['QUERIES'],
                    QueriesConfig={'Queries': [{'Text': 'What is the VALOR TOTAL?', 'Alias': 'VALOR_TOTAL'}]})
```

## Límites que importan

| | |
|---|---|
| Sync | 1 página, **< 10 MB**, JPEG/PNG/PDF/TIFF · async: solo desde S3, hasta 3.000 páginas |
| Idioma | español **impreso** sí (á é ñ ¿ €) · manuscrito, Queries, AnalyzeExpense: **solo inglés** (aunque las 7 queries del taller sí respondieron sobre la factura en español: funciona, no está soportado) · AnalyzeID: solo EE. UU. |
| Queries | máx. **15/página** sync · `Text`/`Alias` ≤ 200 chars, **solo ASCII** (sin tildes, ñ, ¿) · en inglés con la etiqueta literal del documento |
| Región | `us-east-1` (no hay Textract en `sa-east-1`) · cuotas: Detect 25 TPS, Analyze 10 TPS |
| Calidad | ≥ 150 DPI, texto ≥ 15 px · corrige rotación, no perspectiva ni blur |

## Precios (US$/página, Oregón, aprox.) y free tier (cuentas nuevas, 3 meses)

`DetectDocumentText` 0.0015 · `FORMS` 0.05 · `TABLES` 0.015 · `QUERIES` 0.015 · `LAYOUT` gratis con TABLES · `SIGNATURES` 0.0035 · `AnalyzeExpense` 0.01 · las features se **suman** (FORMS+TABLES+LAYOUT = 0.065) · free tier: 1.000 págs/mes Detect, 100 págs/mes AnalyzeDocument · **taller completo ≈ US$ 0.23** · Bedrock Haiku 4.5 ≈ US$ 0.003/factura, Nova Lite ≈ 0.0002.

## Confianza (semáforo)

verde **≥ 90** → aceptar en decisiones financieras · amarillo 70–90 → revisar · rojo < 70 → rechazar/re-capturar · ~50 basta para archivo · KEY y VALUE comparten `Confidence` · `Campo{valor, confianza, origen}`: entre QUERIES / FORMS / TABLES gana la mayor confianza · estado `OK` si no hay alertas, `REVISAR` si hay.

Cifras reales de estos fixtures: WORD **98.7** en `factura_limpia` (5 palabras < 90 de 172) vs **96.2** en `factura_foto` (20 de 173) → la foto de celular se degrada en la cola, no en la media. `CLAVE_ACCESO`: QUERIES 83.0 · FORMS 95.0 → **gana FORMS** (por eso se combinan fuentes). Lab 4 sobre `docs/`: **3 OK · 3 REVISAR · 0 SIN DATOS**; el único REVISAR con reglas de negocio es `factura_trampa` (2 alertas).

## Validadores ecuatorianos (deterministas, `Decimal`)

cédula 10 dígitos módulo 10 (coef. 2,1,2,1,2,1,2,1,2) · RUC 13 dígitos: natural = cédula + `001`; privada (3.er dígito 9) módulo 11 coef. 4,3,2,7,6,5,4,3,2 + `001`; pública (6) coef. 3,2,7,6,5,4,3,2 + `0001` · clave de acceso 49 dígitos módulo 11, pesos cíclicos 2..7 de derecha a izquierda (11→0, 10→1) · factura `^\d{3}-\d{3}-\d{9}$` · fecha `dd/mm/aaaa` no futura · `SUBTOTAL 15% × 0.15 = IVA` · `subtotal + IVA + propina = TOTAL` · Σ ítems = subtotal (± 0.01).

## Errores comunes → fix

| Error | Fix |
|---|---|
| amarillo `sin credenciales` | normal sin cuenta; con cuenta: `export AWS_PROFILE=<perfil>` |
| `AccessDeniedException` | adjunta `iam/textract-workshop-policy.json`; mientras tanto `--offline` |
| `EndpointConnectionError` / `Timed out while opening the session` | sin red / proxy: `--offline` o laptop |
| `InvalidParameterException` (queries) | query con tildes/¿/ñ o > 15 → inglés ASCII |
| `DocumentTooLargeException` / `UnsupportedDocumentException` | > 10 MB o PDF multipágina → 1 página, o `extra/07_async_s3.py` |
| `ThrottlingException` / `ProvisionedThroughputExceeded` | espera; 2.ª ejecución sale de `cache/` |
| `ValidationException … on-demand` (Bedrock) | usa `us.` / `global.` no el ID base |
| `overlay omitido` | `python3 -m pip install --user pillow` (si sale `externally-managed-environment`: añade `--break-system-packages`) o mira `docs/salidas/` |
| `TODO pendiente en mi_pares_clave_valor … usando textract_lab.bloques…` / `tu función devolvió vacío: usando textract_lab.bloques…` | no bloquea: el script usa la librería; tu `mi_pares_clave_valor` aún no devuelve nada |
| `tu implementación difiere de la librería (…)` | revisa `EntityTypes` (`'KEY'`), la relación `VALUE` y el `.rstrip(':')` de la clave |

**Seguridad:** nunca claves en código · política IAM mínima · borra/rota claves al salir · presupuesto con alerta.
