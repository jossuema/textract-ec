# docs/salidas/ — salidas de ejemplo de los labs (modo offline)

Son los archivos que dejan los labs en `salida/` cuando se corren en modo OFFLINE sobre `fixtures/`.
Sirven para seguir el taller desde el celular, sin Pillow, o si no puedes ejecutar nada.
Se regeneran con `bash tools/gen_salidas.sh` (sin AWS, ~10 s).

**Origen:** estas salidas vienen de **respuestas reales de Amazon Textract**, grabadas el 2026-09-04 en
`us-east-1` (16 llamadas, US$ 0.3955); `fixtures/META.json` dice `"origen": "textract"` y
`00_check.py --offline` valida los hashes de `fixtures/MANIFEST.sha256`.
**Única excepción:** los 4 archivos de `fixtures/bedrock/` siguen siendo sintéticos (`"sintetico": true`),
así que los dos `*.bedrock.json` de abajo son texto de ejemplo con la forma de `converse()`, no la respuesta
de un modelo real; `05_bonus_bedrock.py` lo avisa en pantalla (`fixture SINTÉTICO, no salió de Bedrock`).

| Archivo | Comando que lo produce | Qué muestra |
|---|---|---|
| `factura_limpia.overlay.png` | `python3 01_texto.py docs/factura_limpia.png --overlay` | Cajas de cada `LINE` coloreadas por confianza (verde ≥ 90, ámbar 70–90, rojo < 70): 70 verdes y 1 ámbar de 71 (`Teléfono: 07 283 4567`, 87.5). |
| `factura_foto.overlay.png` | `python3 01_texto.py docs/factura_foto.jpg --overlay` | La misma factura fotografiada (inclinada, borrosa, JPEG 62): aun así 65 verdes, 6 ámbar y **0 rojas** de 71. La foto no se rompe: Textract es robusto. |
| `factura_limpia.tabla1.csv` / `.detalle.csv` | `python3 02_formulario_tabla.py docs/factura_limpia.png --csv` | Tabla de ítems (3 filas × 5 columnas) reconstruida desde `TABLE` → `CELL`. |
| `factura_limpia.tabla2.csv` | ídem | Tabla de totales (`SUBTOTAL 15%` … `VALOR TOTAL`), 10 filas × 2 columnas. |
| `factura_limpia.tabla3.csv` | ídem | Tabla "Forma de Pago / Valor". |
| `factura_limpia.validado.json` | `python3 03_inteligente.py docs/factura_limpia.png` | Campos con valor, confianza y origen (FORMS / QUERIES / TABLES); 0 alertas; estado `OK`. Fíjate en `CLAVE_ACCESO`: QUERIES 83.0 vs FORMS 95.0 → **gana FORMS**. |
| `factura_trampa.validado.json` | `python3 03_inteligente.py docs/factura_trampa.png` | Estado `REVISAR` con 2 alertas: clave de acceso con dígito verificador inválido (esperado 3, leído 4) e ítems que no suman el subtotal (831.60 vs 821.60). El OCR es perfecto y aun así el documento está mal. |
| `factura_foto.validado.json` | `python3 03_inteligente.py docs/factura_foto.jpg` | Estado `OK` con **0 alertas**: los mismos valores que la factura limpia. Lo único que se degrada de verdad es `CLAVE_ACCESO` por QUERIES (83.0 → 73.0), y ahí vuelve a ganar FORMS. |
| `formulario_inscripcion.validado.json`, `mini.validado.json`, `orden_compra_prosa.validado.json`, `resumen.json` | `python3 04_sistema.py docs/` | El pipeline completo (`ETAPAS`) sobre todos los documentos de `docs/`: tipo, estado, alertas, páginas, costo. Totales: **3 OK · 3 REVISAR · 0 SIN DATOS**. |
| `orden_compra_prosa.bedrock.json` | `python3 05_bonus_bedrock.py docs/orden_compra_prosa.png --offline` | JSON estructurado por el LLM (fixture) para la carta en prosa donde las 3 queries de Textract fallan: `PROVEEDOR` → `Gerente de Compras` (60.0, es el cargo del firmante), `CANT_MONITORES` → `27` (99.0, son las pulgadas; la cantidad es 3) y solo `TOTAL_COMPRA` se abstiene, que es lo correcto. |
| `factura_foto.bedrock.json` | `python3 05_bonus_bedrock.py docs/factura_foto.jpg --offline --modelo nova` | Normalización y alertas explicadas en español por el LLM, re-validadas por `validadores.py`. **Ojo:** este fixture es sintético y su texto menciona alertas (una `O` por `0`, un total con confianza 71) que los fixtures reales de Textract ya **no** producen. |

`salida/` (ignorada por git) es donde caen **tus** ejecuciones; esta carpeta es la copia versionada de referencia.

## `taller-ejecutado.html`

El notebook `notebooks/taller.ipynb` ya ejecutado, con todas las salidas y el overlay en línea.
Ábrelo en el navegador (o desde el celular) si quieres seguir el taller sin ejecutar nada.
Se regenera con:

```bash
cd notebooks && cp taller.ipynb _tmp.ipynb
LAB_MODO=offline python3 -m jupyter nbconvert --to notebook --execute --inplace _tmp.ipynb
python3 -m jupyter nbconvert --to html --output-dir ../docs/salidas --output taller-ejecutado.html _tmp.ipynb
rm _tmp.ipynb
```
