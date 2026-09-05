# Bonus: Bedrock razona sobre lo que Textract extrajo — cómo replicarlo en casa

En el taller, el bonus (`05_bonus_bedrock.py`) fue una demo del ponente porque habilitar modelos de Anthropic en una cuenta nueva no cabe en 70 minutos. Aquí tienes el camino completo para hacerlo en tu cuenta con calma. Tiempo estimado: 20–30 minutos la primera vez (la mayor parte es esperar).

Lo que hace el script: toma el texto que `DetectDocumentText` extrajo de `docs/orden_compra_prosa.png` (una carta en prosa donde las 3 queries de Textract fallan: una no responde y las otras dos responden mal, una de ellas con 99 % de confianza) o de `docs/factura_foto.jpg`, se lo entrega a un LLM vía la API **Converse** de Amazon Bedrock con un system prompt en español y un **JSON Schema** fijo (`textract_lab/bedrock.py: SCHEMA_DOCUMENTO`), y vuelve a pasar el JSON del modelo por `textract_lab/validadores.py`. Regla: **el LLM propone, el módulo 11 dispone** (toda corrección del LLM se etiqueta como alerta para un humano).

Mientras no tengas Bedrock habilitado, todo funciona en offline con las respuestas grabadas:

```bash
python3 05_bonus_bedrock.py docs/orden_compra_prosa.png --offline
python3 05_bonus_bedrock.py docs/factura_foto.jpg --offline --modelo nova
```

`fixtures/bedrock/<doc>__<modelo>.json` guarda el request completo (system, mensaje, esquema), la respuesta y `usage`. Los fixtures de **Textract** son reales (grabados el 2026-09-04 en us-east-1, 16 llamadas por US$ 0.3955); los 4 de **Bedrock** siguen siendo sintéticos (`"sintetico": true`) y el script lo avisa en pantalla. Consecuencia: en la parte (b) del bonus, la respuesta grabada del modelo explica alertas (una `O` leída por `0`, un total con confianza 71) que los fixtures reales de Textract ya **no** producen — `docs/factura_foto.jpg` hoy sale `OK` con 0 alertas. Cuando grabes los tuyos con `--online --grabar-fixture`, esa diferencia desaparece.

---

## Pre-checklist (en este orden)

### 1. Cuenta AWS con método de pago válido

Los modelos de Anthropic se cobran a través de AWS Marketplace: la primera invocación crea automáticamente una suscripción, y si la cuenta no tiene un método de pago válido devuelve `AccessDeniedException` ("AWS Marketplace Agreement Failed"). Amazon Nova no pasa por Marketplace: si solo quieres Nova, este paso no te bloquea.

### 2. Permisos IAM

Adjunta a tu usuario (o rol) la política [`iam/bedrock-workshop-policy.json`](../iam/bedrock-workshop-policy.json):

- `bedrock:InvokeModel` y `bedrock:InvokeModelWithResponseStream` sobre `arn:aws:bedrock:*::foundation-model/*` **y** `arn:aws:bedrock:*:*:inference-profile/*` (Converse se autoriza con `InvokeModel`; los perfiles `us.`/`global.` necesitan ambos ARN).
- `bedrock:ListFoundationModels`, `bedrock:GetFoundationModel`, `bedrock:ListInferenceProfiles`, `bedrock:GetFoundationModelAvailability` (solo lectura, para `tools/bedrock_check.py` y la consola).
- `bedrock:GetUseCaseForModelAccess` y `bedrock:PutUseCaseForModelAccess` (el formulario del paso 3).
- `aws-marketplace:Subscribe`, `aws-marketplace:ViewSubscriptions` y `aws-marketplace:Unsubscribe` condicionados a `aws:CalledViaLast = bedrock.amazonaws.com` (solo cuando Bedrock los invoca en tu nombre; se necesitan únicamente la primera vez).

Alternativa rápida y más permisiva: la política administrada `AmazonBedrockFullAccess`.

### 3. Formulario de caso de uso de Anthropic (una sola vez por cuenta)

Desde octubre de 2025 los modelos serverless de Bedrock están habilitados por defecto, pero los de **Anthropic** exigen un formulario de "caso de uso" (First Time Use):

1. Consola de AWS → región **us-east-1** → **Amazon Bedrock** → **Model catalog** → **Claude Haiku 4.5**.
2. Pulsa **Submit use case details** (también aparece al abrir el Playground).
3. Rellena: nombre de la empresa (vale tu nombre), sitio web (AWS acepta tu perfil de GitHub, portafolio o la URL de este repo), usuarios previstos, industria y descripción del caso de uso (por ejemplo: "Estructurar y validar texto OCR de facturas ecuatorianas extraído con Amazon Textract, uso educativo").
4. Según la documentación oficial, el acceso se concede **inmediatamente** tras enviarlo. Hay reportes comunitarios (no verificados) de denegaciones o cuota 0 en cuentas nuevas fuera de EE. UU.: si te pasa, usa Nova (paso 6).

Documentación: <https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html>

### 4. Verifica con `tools/bedrock_check.py`

```bash
export AWS_PROFILE=tuperfil
python3 tools/bedrock_check.py
```

Hace un `converse` mínimo con Claude Haiku 4.5 (perfil `us.`) y con Nova Lite, y traduce los errores típicos:

| Error de AWS | Significado | Qué hacer |
|---|---|---|
| `FTUFormNotFilled` / "use case" | Falta el formulario del paso 3 | Envíalo y vuelve a probar |
| `MPAgreementBeingCreated` / "Marketplace" | La suscripción de Marketplace está en curso | Espera hasta 15 minutos y reintenta |
| `AccessDeniedException` | IAM no permite `bedrock:InvokeModel`, o falló el acuerdo de Marketplace (método de pago) | Revisa el paso 1 y 2 |
| `ValidationException … on-demand throughput isn't supported` | Usaste el ID base `anthropic.claude-haiku-4-5-…` | Usa `us.anthropic.claude-haiku-4-5-20251001-v1:0` o `global.anthropic.…` |
| `ThrottlingException` / `ServiceUnavailable` | Cuota o carga | Reintenta, o `--modelo haiku-global` / `--modelo nova` |

### 5. Precalienta el esquema (opcional, recomendado)

La primera llamada con un JSON Schema nuevo en **structured outputs** puede tardar "hasta unos minutos" mientras Bedrock compila la gramática; después se cachea 24 horas **por cuenta**. `python3 tools/precalentar_esquema.py` hace esa primera llamada con el esquema exacto del taller para que `05_bonus_bedrock.py` responda rápido.

### 6. Ejecuta el bonus en online

```bash
python3 05_bonus_bedrock.py docs/orden_compra_prosa.png --online
python3 05_bonus_bedrock.py docs/factura_foto.jpg --online
```

Modelos disponibles con `--modelo`:

| Clave | modelId | Estrategia JSON | Requisitos |
|---|---|---|---|
| `haiku` (por defecto) | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | `outputConfig` json_schema (structured outputs) | Formulario Anthropic + Marketplace |
| `haiku-global` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` | idem, sin el recargo regional del 10 % | idem |
| `nova` | `amazon.nova-lite-v1:0` | `toolConfig` con `toolChoice` forzado (Nova no soporta structured outputs) | Ninguno: ID base en us-east-1, sin formulario ni Marketplace |
| `nova-micro` | `amazon.nova-micro-v1:0` | idem | Ninguno |

**Fallback automático:** si la llamada con Haiku falla, el script intenta `nova` una vez y, si también falla, cae a `--offline`. Puedes forzar Nova desde el inicio con `--modelo nova`: es el camino más simple si no quieres pasar por el formulario. Nunca uses el ID base `anthropic.claude-haiku-4-5-20251001-v1:0` en us-east-1: la invocación In-Region no está soportada.

---

## Cuánto cuesta (aproximado; precios de Bedrock tomados de fuentes secundarias, no confirmados en la página oficial)

| Modelo | US$ por millón de tokens (entrada / salida) | Una factura (≈ 2.000 tokens entrada, ≈ 300 salida) |
|---|---|---|
| Claude Haiku 4.5 | 1.00 / 5.00 (`us.` lleva +10 % sobre `global.`) | ≈ US$ 0.0035 |
| Amazon Nova Lite | 0.06 / 0.24 | ≈ US$ 0.0002 |
| Amazon Nova Micro | 0.035 / 0.14 | ≈ US$ 0.0001 |

El script imprime `usage` (`inputTokens` / `outputTokens`) y el costo estimado con `textract_lab.bedrock.costo_aprox()`. Cien facturas con Haiku 4.5 cuestan menos de medio dólar; con Nova Lite, dos centavos.

---

## Cómo está hecho (para leer `textract_lab/bedrock.py`)

- Un solo `boto3.client('bedrock-runtime', region_name='us-east-1')`.
- `estructurar(texto, campos, alertas, modelo=...)` elige la estrategia por el prefijo del `modelId`:
  - `us.anthropic` / `global.anthropic` / `anthropic.` → `outputConfig={'textFormat': {'type': 'json_schema', 'structure': {'jsonSchema': {'name': 'documento', 'description': '…', 'schema': json.dumps(SCHEMA_DOCUMENTO)}}}}`. Ojo: en boto3 el campo `schema` es un **string** JSON, no un dict.
  - `amazon.nova` → `toolConfig={'tools': [{'toolSpec': {'name': 'registrar_documento', 'inputSchema': {'json': SCHEMA_DOCUMENTO}}}], 'toolChoice': {'tool': {'name': 'registrar_documento'}}}` y se lee `output.message.content[].toolUse.input`.
  - Cualquier otro → prompt "responde solo JSON" + limpieza de fences + `json.loads`.
- `inferenceConfig={'temperature': 0, 'maxTokens': 1024}`; system prompt en español con reglas: no inventar; dato ausente = cadena vacía o 0 más una alerta; fechas `YYYY-MM-DD`; USD por defecto; validar RUC de 13 dígitos y que subtotal + IVA cuadre con el total; explicar cada alerta en una frase.
- El esquema (`SCHEMA_DOCUMENTO`) usa `additionalProperties: false` y `required` en todos los niveles: structured outputs de Bedrock solo admite un subconjunto de JSON Schema 2020-12 (sin `minimum`/`maximum`/`minLength`, sin recursión).
- Mantén el esquema **idéntico** (mismo `json.dumps`) entre llamadas para aprovechar el caché de compilación.

---

## Notas y alternativas

- **Endpoint bedrock-mantle.** Existe un endpoint alternativo con la Messages API nativa de Anthropic (`https://bedrock-mantle.us-east-1.api.aws/anthropic/v1/messages`) que **no exige el formulario** de caso de uso, pero requiere el SDK `anthropic` (cliente `AnthropicBedrockMantle`) y no soporta structured outputs. No se usa en el taller para no añadir dependencias; es una vía de escape si el formulario te bloquea.
- **Bedrock Data Automation (BDA).** Es lo que AWS recomienda "para la mayoría de casos" de IDP: blueprints por tipo de documento, español soportado, precio por página (≈ US$ 0.01 estándar / 0.04 personalizado según fuentes secundarias). No está en `sa-east-1`. Es el siguiente paso natural cuando tienes muchos tipos de documento y no quieres escribir parseadores; Textract sigue siendo el OCR por defecto de ese pipeline.
- **Modelos más grandes.** Claude Sonnet 4.6 (`us.anthropic.claude-sonnet-4-6`) también soporta structured outputs; Claude Sonnet 5 **no** lo soporta en `bedrock-runtime`. Para este caso Haiku 4.5 sobra.
- **Seguridad.** Igual que con Textract: credenciales solo por `AWS_PROFILE`, política mínima, presupuesto con alerta, y borra la suscripción de Marketplace (`aws-marketplace:Unsubscribe`) si no vas a seguir usando el modelo.

Fuentes: [Acceso a modelos](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html) · [Converse](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html) · [Structured outputs](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html) · [Model card Claude Haiku 4.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-4-5.html) · [Model card Nova Lite](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-lite.html) · [Políticas IAM de Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/security_iam_id-based-policy-examples.html) · [Claude en Bedrock (Anthropic)](https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock).
