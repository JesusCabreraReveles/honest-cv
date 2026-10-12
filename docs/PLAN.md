# honest-cv: plan y alcance de la v0.1

honest-cv es un servidor MCP, una CLI y una skill de Claude Code. Convierte la experiencia real de una persona en CVs aptos para ATS, adaptados a cada tipo de puesto, sin inventar nada.

La versión con diseño de este mismo plan está en `docs/plan.html`.

## Objetivo

Publicar en unas 2 semanas una v0.1 que se instale en una línea y se use desde Claude Code o Cursor. Debe resolver tres cosas:

1. **Inventario honesto.** Una entrevista guiada registra cada skill con su nivel de evidencia y sus años.
2. **Variantes por puesto.** Genera PDF y DOCX aptos para ATS desde una sola fuente de datos.
3. **Análisis contra una vacante.** Mide la cobertura y explica qué falta y por qué.

## Qué lo hace distinto

### La honestidad la aplica el sistema

Cada skill lleva un nivel:

| Nivel | Significado | Cómo sale en el CV |
|---|---|---|
| `P` | Producción | Normal |
| `L` | Proyecto propio o laboratorio | Normal |
| `F` | Familiaridad | Siempre con la etiqueta "Familiarity" / "Familiaridad" |
| `X` | No la tiene | Nunca aparece |

Para subir de nivel una skill hacen falta dos cosas: el campo `evidence` y la confirmación de la persona.

### El análisis de brechas usa el inventario propio

Para cada palabra clave que falta, la herramienta distingue tres casos:

- La tienes en `P` o `L`, pero no está en este CV.
- La tienes en `F`.
- No la tienes.

### El servidor no necesita API key

El servidor es determinista. El LLM del cliente extrae las palabras clave y conduce la entrevista. El servidor valida, genera y mide.

### Las garantías de ATS se comprueban en cada build

- Una sola columna.
- Sin ligaduras.
- Orden de lectura igual al orden del DOM: flexbox, sin float.
- Texto extraíble, verificado con pypdf y pdfminer.six.

## Alcance

### Lo que entra en la v0.1

| Pieza | Detalle |
|---|---|
| Modelo de datos | YAML validado con pydantic. Incluye perfil, pool de bullets (cada uno con id y tags), inventario de skills y plan de variantes (con herencia `extends:`). Soporta EN y ES. |
| Render | Una plantilla clásica de una columna que sale a PDF. DOCX con python-docx. `fit_pages` ajusta la densidad tipográfica hasta caber en el máximo de páginas. |
| Verificación | Extracción de texto, más revisión del orden de lectura, las ligaduras y el número de páginas. |
| Score y brechas | Cobertura de palabras clave con sinónimos (k8s ⇄ Kubernetes). Brechas clasificadas por nivel del inventario. |
| Servidor MCP | Las herramientas y prompts de la sección siguiente, por transporte stdio. |
| CLI | `honest-cv init`, `build`, `verify`, `score`. |
| Skill | Un `SKILL.md` para Claude Code que orquesta la entrevista y la adaptación a una vacante. |
| Ejemplo | El perfil ficticio "Ada Example" con una vacante de muestra. |

### Lo que queda fuera

| Pieza | Cuándo |
|---|---|
| Importar y exportar JSON Resume | v0.2 |
| Importar el PDF de LinkedIn | v0.2 |
| Carta de presentación por vacante | v0.2 |
| Más plantillas | v0.3, con contribuciones |
| UI web o servicio hospedado | No está previsto. Los datos se quedan en local. |

## Herramientas y prompts MCP

| Nombre | Qué hace |
|---|---|
| `init_profile` | Crea la carpeta del perfil con plantillas YAML vacías. |
| `get_inventory` | Devuelve las skills con su nivel, años y evidencia. |
| `set_skill` | Agrega o cambia una skill. Para subir de nivel exige `evidence`. |
| `add_bullet` | Agrega un logro al pool, con su rol, tags y métricas. |
| `list_variants` | Lista las variantes y sus bullets. |
| `build_cv` | Genera el PDF o DOCX de una variante e idioma, y lo verifica. |
| `verify_pdf` | Revisa que el archivo sea apto para ATS y devuelve el texto extraído. |
| `score_job` | Recibe la vacante y las palabras clave que extrajo el cliente. Devuelve la cobertura por variante. |
| `gap_report` | Clasifica lo que falta en tres casos: está en el inventario pero no en el CV, la tienes en `F`, o no la tienes. |
| prompt `interview` | Entrevista guiada para llenar el inventario y los bullets. |
| prompt `tailor_for_job` | Encadena score, brechas, ajuste de la variante y rebuild. |

## Estructura del repo

```
honest-cv/
├── src/honest_cv/
│   ├── model.py        # esquemas pydantic: Profile, Skill, Bullet, Variant
│   ├── render/         # html.py, pdf.py, docx.py, templates/classic.html
│   ├── verify.py       # extracción y revisiones ATS
│   ├── score.py        # cobertura, sinónimos, brechas
│   ├── server.py       # servidor MCP (herramientas y prompts)
│   └── cli.py
├── examples/ada/       # perfil ficticio y vacante de muestra
├── skills/honest-cv/SKILL.md
├── tests/
├── .github/workflows/ci.yml
└── README.md · LICENSE (MIT) · CONTRIBUTING.md
```

## Calendario

Calculado a razón de 2–3 h por día.

| Día | Entregable |
|---|---|
| 1 | Repo, `pyproject.toml` y spike del motor PDF (Typst frente a Chrome) |
| 2–3 | Esquemas pydantic, carga de YAML, render a HTML, PDF y DOCX |
| 4 | `verify.py` y `score.py`, con sinónimos y brechas |
| 5 | Servidor MCP con las herramientas, probado en Claude Code |
| 6 | Los prompts `interview` y `tailor_for_job`, y el `SKILL.md` |
| 7 | Perfil de ejemplo, tests y CI |
| 8 | README con GIF y la configuración para Claude Code, Cursor y Claude Desktop |
| 9 | Publicación en PyPI (`uvx honest-cv`) y en los directorios de MCP |
| 10 | Lanzamiento: Show HN, Reddit, LinkedIn y un artículo |

## Decisiones tomadas (2026-10-11)

| Decisión | Resultado |
|---|---|
| Nombre | `honest-cv`. Estaba libre en PyPI el 2026-10-11. |
| Motor PDF | **Typst** (spike del día 1, ver `docs/spike-pdf-engine.md`). El texto extraído sale limpio y permite instalar en una línea sin dependencias del sistema. Chrome headless queda descartado. |
| Idioma | README en inglés, más `README.es.md`. CVs en EN y ES desde la v0.1. El código y los comentarios, en inglés. |
| Licencia | MIT. |

## Riesgos

- **Fuga de datos personales.**
  - `profiles/` está en `.gitignore`.
  - Los tests y las demos usan solo el perfil ficticio.
- **Dependencia de Chrome.** Rompe la instalación en una línea. Se mitiga con el spike de Typst.
- **Competencia establecida.** Ya hay generadores de CV desde YAML y comparadores de CV contra vacantes con miles de estrellas. No conviene competir en plantillas. La diferencia está en tres cosas: diseño MCP desde el inicio, honestidad aplicada por el sistema y brechas medidas contra el inventario propio.
- **Que el proyecto se alargue.** Todo lo que no está en "Lo que entra en la v0.1" espera a la v0.2.

## Cómo saber si funcionó

- El autor lo usa para sus propias postulaciones.
- Está publicado en PyPI, en el registro de MCP y en awesome-mcp-servers.
- Consigue 100–300 estrellas el primer mes.
