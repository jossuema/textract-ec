# extra/ — tarea para casa (nada de esto se usa en los 70 minutos del taller)

Tres scripts que amplían lo que hiciste en los labs. Los tres usan `textract_lab/` (mismo cliente, mismo
cache, mismos validadores) y se ejecutan **desde la raíz del repo**:

```bash
cd textract-ec
python3 extra/06_expense.py --offline
python3 extra/07_async_s3.py docs/factura_limpia.pdf --bucket mi-bucket --dry-run
python3 extra/08_textractor.py --offline
```

| Script | API | Costo aprox. (tarifa Oregón) | Funciona offline |
|---|---|---|---|
| `06_expense.py` | `AnalyzeExpense` | US$ 0.01 / página | sí, si existe `fixtures/<doc>/analyze_expense.json`. El repo trae los fixtures **reales** de `recibo_restaurante` para `DetectDocumentText` y `FORMS+TABLES+LAYOUT` (grabados el 2026-09-04), pero **no** el de `AnalyzeExpense`: el script explica en pantalla los 3 pasos para grabarlo |
| `07_async_s3.py` | `StartDocumentAnalysis` + `GetDocumentAnalysis` (o `*TextDetection`) | igual que la versión síncrona por página | no (solo online); `--dry-run` muestra el plan sin tocar AWS |
| `08_textractor.py` | ninguna nueva: reparsea la respuesta del Lab 2 | US$ 0 con cache/fixtures | sí; si `amazon-textract-textractor` no está instalada, explica cómo hacerlo y termina limpio |

## 06 — AnalyzeExpense: recibos y facturas sin plantilla (experimento)

`AnalyzeExpense` devuelve una taxonomía normalizada en vez del grafo de bloques: `ExpenseDocuments[].SummaryFields[]`
(`VENDOR_NAME`, `TAX_PAYER_ID`, `INVOICE_RECEIPT_DATE`, `SUBTOTAL`, `TAX`, `GRATUITY`, `TOTAL`…) y
`LineItemGroups[].LineItems[].LineItemExpenseFields[]` (`ITEM`, `QUANTITY`, `UNIT_PRICE`, `PRICE`). Es el parseo más
sencillo de Textract: `{Type.Text: ValueDetection.Text}`.

**Está documentado oficialmente solo para inglés** (FAQ de Textract: *Invoices and Receipts … are in English only*).
Con `docs/extra/recibo_restaurante.png` (en español, con PROPINA 10 % e IVA 15 %) es un experimento: puede mapear
`PROPINA` a `GRATUITY` y `IVA 15%` a `TAX`… o dejarlos como `OTHER`. El script muestra lo que devuelva y aplica
una validación rápida con `Decimal` (RUC con módulo 11, `SUBTOTAL + TAX + GRATUITY = TOTAL`).

```bash
# online (≈ US$ 0.01; queda en cache/recibo_restaurante/analyze_expense.json)
AWS_PROFILE=personal python3 extra/06_expense.py docs/extra/recibo_restaurante.png --online --json
# para que después funcione en offline son 3 pasos (sin regenerar el MANIFEST, pytest y 00_check avisan "fixture no listado"):
mkdir -p fixtures/recibo_restaurante
cp cache/recibo_restaurante/analyze_expense.json fixtures/recibo_restaurante/analyze_expense.json
shasum -a 256 $(find fixtures -name '*.json' -not -name META.json | sort) > fixtures/MANIFEST.sha256
python3 00_check.py --offline      # debe decir MANIFEST OK
```

Permiso IAM: `textract:AnalyzeExpense` (ya está en `iam/textract-workshop-policy.json`). Cuota por defecto en
us-east-1: 5 TPS.

## 07 — Asíncrono desde S3: PDF/TIFF de muchas páginas

Las llamadas síncronas del taller aceptan `Bytes` de una sola página (≤ 10 MB). Para PDF/TIFF multipágina
(hasta 500 MB y 3.000 páginas) se usa `StartDocumentAnalysis` → `JobId` → polling con `GetDocumentAnalysis`
hasta `JobStatus != IN_PROGRESS`, y luego se acumulan los `Blocks` siguiendo `NextToken` (`MaxResults` ≤ 1.000).
Reglas que importan:

- El documento **debe estar en S3**, en la **misma región** que Textract (`us-east-1`); si no, `InvalidS3ObjectException`.
- `NotificationChannel` (SNS) es opcional: con polling no hace falta SNS, SQS ni `iam:PassRole`.
- El `JobId` vale 7 días; máximo 600 trabajos concurrentes por cuenta.
- Permisos **adicionales** a los del taller: `textract:StartDocumentAnalysis`, `textract:GetDocumentAnalysis`
  (o `StartDocumentTextDetection`/`GetDocumentTextDetection` con `--solo-texto`), `s3:PutObject` y `s3:GetObject`
  sobre el bucket.

```bash
python3 extra/07_async_s3.py docs/factura_limpia.pdf --bucket mi-bucket-us-east-1 --dry-run   # solo imprime el plan
AWS_PROFILE=personal python3 extra/07_async_s3.py mi_contrato.pdf --bucket mi-bucket-us-east-1 --features FORMS TABLES
```

La respuesta completa queda en `salida/<documento>.async.json` con la misma forma que las síncronas: puedes pasarla
tal cual a `textract_lab.bloques` (`lineas`, `pares_clave_valor`, `tablas`).

Alternativa sin S3 para PDFs cortos: rasterizar con PyMuPDF a PNG por página y llamar en síncrono página a página.

## 08 — amazon-textract-textractor: el atajo

`amazon-textract-textractor` (v1.10.0, agosto de 2026, Python ≥ 3.10) es la librería oficial de AWS que convierte
la respuesta en objetos `Document` / `Table` / `KeyValue` con `to_pandas()`, `to_csv()`, `to_markdown()` y `to_html()`.
En el taller recorrimos los `Blocks` a mano porque es más didáctico y no añade dependencias; esta es la versión
"con librería" del Lab 2. El script sigue usando `textract_lab.cliente.llamar()` (cache/fixtures, costo controlado) y
le pasa el dict crudo a `textractor.parsers.response_parser.parse()`.

```bash
python3 -m pip install "amazon-textract-textractor[pandas]"    # opcional; o requirements-extra.txt
python3 extra/08_textractor.py docs/factura_limpia.png --offline --markdown
```

Salida: pares clave-valor, cada tabla como DataFrame y `salida/<doc>.tabla<N>.csv`, y con `--markdown` el texto
linealizado que se le daría a un LLM (compárala con `bloques.texto_completo()` del bonus).

## Para seguir

- `bonus/README.md`: preparar tu cuenta para el bonus de Bedrock.
- `python3 -m pytest -q tests/`: los tests corren 100 % offline.
- `CHEATSHEET.md`: límites, precios y errores frecuentes en una página.
