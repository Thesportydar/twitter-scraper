# AGENTS.md — Fintwit Argy Bot

Guía de contexto para agentes de IA trabajando en este repositorio.
Leé esto antes de tocar cualquier código.

---

## Qué es este proyecto

**Fintwit Argy Bot** es un pipeline serverless que monitorea la conversación financiera argentina en X (Twitter), la analiza con GPT-5, y publica reportes automáticos en un sitio estático.

Flujo principal:
```
EventBridge (cron)
  → Dispatcher Lambda  (¿hay que scrapear ahora?)
  → ECS Fargate Task   (Playwright stealth scraper)
  → S3 (tweets.parquet) + EventBridge (TweetsUploaded)
  → Processor Lambda   (OpenAI GPT-5 → Markdown)
  → Git commit → GitHub Action → Astro build → CloudFront
```

---

## Estructura del repo

```
scraper/        Python + Playwright (ECS Fargate, Docker)
lambdas/
  dispatcher/   Node.js ESM — decide si lanzar el scraper
  processor/    Node.js ESM — análisis OpenAI + commit al repo
  layer/        Dependencias compartidas empaquetadas como Lambda Layer
frontend/       Astro — sitio estático, content en src/content/
terraform/      IaC completa del stack AWS
.github/
  workflows/    CI/CD: deploy-fargate, deploy-dispatcher,
                       deploy-processor, deploy-front
```

---

## Reglas generales

- **No commitear secrets.** Toda credencial vive en SSM Parameter Store.
  Los nombres de parámetros siguen el patrón `/{env}/{service}/{key}`.
- **Terraform es la única fuente de verdad** para infraestructura.
  No tocar recursos AWS a mano; hacer cambios en `terraform/` y aplicar.
- **Los `.zip` de lambdas son artefactos de deploy**, no código fuente.
  No editarlos directamente. El CI los regenera.
- Los ambientes son `dev` y `prod`, controlados con `terraform/dev.tfvars`
  y `terraform/prod.tfvars` respectivamente.

---

## Módulo: `scraper/`

**Stack:** Python 3.12, Playwright (async), playwright-stealth, PyArrow, boto3.

**Variables de entorno relevantes** (seteadas en `terraform/scraper_ecs.tf`):
| Variable | Descripción |
|---|---|
| `MAX_TWEETS` | Tope de tweets por run (default 15) |
| `MAX_IDLE_SCROLLS` | Scrolls sin nuevos tweets antes de parar |
| `MODO_HUMANO` | Activa delays y movimientos aleatorios |
| `HEADLESS` | Modo headless del browser |
| `DYNAMODB_TABLE` | Tabla de deduplicación |
| `S3_BUCKET` | Bucket destino del parquet |
| `EVENT_BUS_NAME` | EventBridge bus para emitir `TweetsUploaded` |

**Workflow de desarrollo local:**
```bash
cd scraper
docker build -t fintwit-scraper .
docker run --env-file .env.local fintwit-scraper
```

**Al modificar `scraper.py`:**
- Mantener el schema Parquet definido en `PARQUET_SCHEMA` sincronizado con la tabla Athena.
- El scraper emite el evento `TweetsUploaded` al finalizar; no quitar esa lógica.
- Stealth: no agregar código que haga el browser detectable (headers, fingerprints).

**Deploy:** push a cualquier path bajo `scraper/` → `deploy-fargate.yml` construye y sube la imagen a ECR y actualiza el task definition.

---

## Módulo: `lambdas/`

**Stack:** Node.js 20, ESM (`.mjs`), AWS SDK v3.

**No hay framework de tests configurado.** Si agregás uno, usá Jest o Vitest y documentalo acá.

### `dispatcher/`
Decide si el momento actual justifica un nuevo scrape y lanza el ECS task.
- Lógica de tiempo en `argentina-time.mjs` (compartida con processor).
- Al modificar: revisar que las ventanas horarias (pre-market, media-rueda, post-market) sigan siendo correctas respecto al horario de Buenos Aires.
- **Deploy:** push a `lambdas/dispatcher/` → `deploy-dispatcher.yml`.

### `processor/`
Recibe el evento `TweetsUploaded`, descarga el parquet de S3, construye el prompt dinámico según el tipo de día/momento, llama a OpenAI, y commitea el Markdown al repo.

- Los 4 prompts del sistema están en `generateAnalysisPrompt()` dentro de `index.mjs`.
- Los tipos de día son: `Pre-Mercado`, `Media-Rueda`, `Post-Mercado`, `Fin de semana`, `Feriado Argentina`, `Feriado USA`.
- Al agregar un nuevo prompt o tipo de día, actualizar también la función `getTipoDia()`.
- El token de GitHub para el commit vive en SSM; el nombre del parámetro está en `terraform/parameters.tf`.
- **Deploy:** push a `lambdas/processor/` → `deploy-processor.yml`.

### `layer/`
Dependencias Node empaquetadas como Lambda Layer. Si agregás una dependencia a dispatcher o processor, hay que reconstruir y re-deployar el layer.

---

## Módulo: `frontend/`

**Stack:** Astro 5, TypeScript, Vanilla CSS.

**Contenido:** Los reportes generados por el processor llegan como archivos `.md` en `src/content/`. No tocar esos archivos manualmente.

```bash
cd frontend
npm install
npm run dev      # desarrollo local
npm run build    # validar build (no es necesario para deploy)
```

**Deploy:** el processor commitea a `src/content/` → `deploy-front.yml` buildea y sincroniza con S3/CloudFront.

Al modificar componentes Astro:
- Respetar la estructura de colecciones definida en `src/content.config.ts`.
- Las constantes globales (título del sitio, etc.) están en `src/consts.ts`.

---

## Módulo: `terraform/`

**Provider:** AWS. **Backend:** S3 + DynamoDB (config en `backend.conf`).

```bash
cd terraform
terraform init -backend-config=backend.conf
terraform workspace select dev   # o prod
terraform plan -var-file=dev.tfvars
terraform apply -var-file=dev.tfvars
```

**Archivos clave:**
| Archivo | Qué define |
|---|---|
| `scraper_ecs.tf` | Task definition, Fargate cluster, IAM del scraper |
| `dispatcher.tf` | Lambda dispatcher + EventBridge rule (cron) |
| `processor.tf` | Lambda processor + suscripción al evento |
| `frontend.tf` | S3 bucket + CloudFront distribution |
| `shared.tf` | Recursos compartidos (EventBridge bus, VPC, etc.) |
| `parameters.tf` | SSM Parameters (tokens, keys) — valores seteados fuera del repo |
| `variables.tf` | Variables de entrada (environment, region, etc.) |

Al agregar infraestructura nueva:
- Seguir el principio de mínimo privilegio en los IAM roles.
- Agregar outputs relevantes a `outputs.tf`.

---

## CI/CD — GitHub Actions

| Workflow | Trigger | Qué hace |
|---|---|---|
| `deploy-fargate.yml` | push en `scraper/**` | Build Docker → ECR → update ECS task def |
| `deploy-dispatcher.yml` | push en `lambdas/dispatcher/**` | Zip → update Lambda |
| `deploy-processor.yml` | push en `lambdas/processor/**` | Zip → update Lambda |
| `deploy-front.yml` | push en `frontend/src/content/**` | Astro build → S3 sync → CF invalidate |

Los secrets de AWS están configurados en GitHub Secrets del repo. No los toques desde acá.

---

## Patrones a preservar

1. **Event-driven estricto:** los componentes no se llaman entre sí directamente. Toda comunicación es via EventBridge o S3.
2. **Stealth first:** cualquier cambio en el scraper debe mantener la imperceptibilidad del bot.
3. **Prompts contextuales:** el processor nunca usa un prompt genérico. Siempre deriva el contexto temporal antes de llamar a OpenAI.
4. **Git como CMS:** el ciclo de publicación cierra con un commit, no con un API call a un backend.

---

## Qué NO hacer

- ❌ No hardcodear credenciales, API keys, ni ARNs de producción en el código.
- ❌ No modificar los `.zip` en `lambdas/` directamente.
- ❌ No agregar dependencias pesadas al processor sin evaluar el impacto en cold start.
- ❌ No romper el schema Parquet sin actualizar la tabla Athena correspondiente.
- ❌ No deployar a `prod` sin haber validado en `dev` primero.
