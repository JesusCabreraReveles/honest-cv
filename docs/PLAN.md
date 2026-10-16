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
| Render | Una plantilla clásica de una columna que sale a PDF con Typst. DOCX con python-docx. `fit_pages` ajusta la densidad tipográfica hasta caber en el máximo de páginas. |
| Verificación | Extracción de texto, más revisión del orden de lectura, las ligaduras y el número de páginas. |
| Score y brechas | Cobertura de palabras clave con sinónimos (k8s ⇄ Kubernetes). Brechas clasificadas por nivel del inventario. |
| Servidor MCP | Las herramientas y prompts de la sección siguiente, por transporte stdio. |
| CLI | `honest-cv init`, `build`, `verify`, `score`, `skill`, `checklist`, `import`. |
| Edición del perfil | Herramientas para contacto, puestos, formación y variantes, para que ningún cliente necesite editar los YAML a mano. |
| Checklists ([#1](https://github.com/JesusCabreraReveles/honest-cv/issues/1)) | Listas en Markdown para marcar el nivel de muchas skills en minutos. Vienen listas incluidas y se puede aplicar cualquier archivo con el mismo formato. Las líneas sin evidencia quedan pendientes. `set_skills` confirma varias subidas de nivel con una sola pregunta. |
| Carta de presentación | Un prompt redacta la carta con los bullets y skills P/L. `build_letter` la genera en PDF y DOCX con las mismas verificaciones. `check_claims` avisa si el texto menciona una skill X, o una F como experiencia. |
| Importar | JSON Resume y la exportación de datos de LinkedIn (ZIP con CSVs), de forma determinista. El PDF del perfil de LinkedIn, con el texto extraído por el servidor y organizado por el cliente. Las skills importadas llegan sin nivel, como líneas pendientes de un checklist. |
| Skill | Un `SKILL.md` para Claude Code que orquesta la entrevista y la adaptación a una vacante. |
| Ejemplo | El perfil ficticio "Ada Example" con una vacante de muestra. |

### Lo que queda fuera

| Pieza | Cuándo |
|---|---|
| Exportar a JSON Resume | v0.2 (ver "Alcance de la v0.2") |
| Preparar entrevistas | Después de la v0.2 |
| Checklists en varios idiomas | Después de la v0.2: una carpeta por idioma, p. ej. `checklists/en/` y `checklists/es/`, para que cada quien marque en su idioma. Los sinónimos entre idiomas (`same:`) ya permiten que el puntaje cruce una vacante en inglés con skills en español. |
| Más plantillas | v0.3, con contribuciones |
| UI web o servicio hospedado | No está previsto. honest-cv guarda los datos en local y no hace llamadas de red. |

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
| `set_contact`, `upsert_role`, `upsert_education`, `save_variant` | Editan el perfil y las variantes, validando todo antes de escribir. |
| `set_skills` | Varias skills a la vez. Las subidas de nivel se confirman con una sola pregunta que lista cada cambio y su evidencia. |
| `checklist_new`, `checklist_apply` | Arman un checklist a partir de las listas incluidas y lo aplican al inventario. |
| `build_letter` | Genera la carta de presentación en PDF y DOCX, y la verifica. |
| `check_claims` | Revisa un texto y avisa si menciona skills que el inventario no respalda. |
| `import_profile` | Importa JSON Resume o el ZIP de LinkedIn. |
| prompt `interview` | Entrevista guiada para llenar el inventario y los bullets. |
| prompt `tailor_for_job` | Encadena score, brechas, ajuste de la variante y rebuild. |
| prompt `cover_letter` | Redacta la carta para una vacante, revisa sus afirmaciones y la genera. |
| prompt `import_linkedin_pdf` | Organiza el texto del PDF de LinkedIn con las herramientas de edición, con la aprobación de la persona. |

## Estructura del repo

```
honest-cv/
├── src/honest_cv/
│   ├── model.py        # esquemas pydantic: Profile, Skill, Bullet, Variant
│   ├── document.py     # variante + idioma → documento; aplica las reglas de honestidad
│   ├── build.py        # punto de entrada común para la CLI y el servidor
│   ├── render/         # pdf.py (Typst), docx.py, templates/classic.typ, fonts/ (Carlito, OFL)
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
| 9 | Pruebas previas a PyPI: artefactos, Linux limpio en Docker, MCP Inspector, Claude Code y Claude Desktop |
| 10 | Herramientas de edición del perfil, entrevista por temas, tabla de soporte por cliente |
| 11–13 | Checklists: formato, parser, CLI, herramientas MCP, `set_skills` y listas incluidas |
| 14–15 | Carta de presentación: prompt, `build_letter` y `check_claims` |
| 16–17 | Importar: JSON Resume, ZIP de LinkedIn y PDF de LinkedIn |
| 18 | Versión 0.1.0, `server.json` y publicación en PyPI y en los directorios de MCP |
| 19 | Lanzamiento: Show HN, Reddit, LinkedIn y un artículo |

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

## Decisiones tomadas (2026-10-12)

| Decisión | Resultado |
|---|---|
| Alcance de la v0.1 | Se amplía con checklists, carta de presentación, importación y herramientas de edición del perfil. No se publica un producto incompleto. |
| Orden | Edición del perfil, checklists, carta, importar y publicar. La carta va antes de importar porque solo usa datos que ya existen. |
| Confirmación en grupo | `set_skills` muestra una sola pregunta con la lista completa de cambios y su evidencia. Sigue siendo una confirmación humana. |
| Evidencia en checklists | Sigue siendo obligatoria. Las líneas sin evidencia quedan pendientes y se preguntan en grupo. |
| LinkedIn | Los dos caminos: el ZIP de exportación de datos, que es confiable, y el PDF del perfil, que es práctico. |

## Decisiones tomadas (2026-10-14)

| Tema | Decisión |
|---|---|
| v0.1 | Congelada en la rama `release/0.1`, sin publicar. Las pruebas en clientes que quedan (importar el ZIP real de LinkedIn, Claude Desktop) y la publicación salen de esa rama cuando el autor decida. Las correcciones que necesite se hacen ahí y se pasan a `master`. |
| v0.2 | El desarrollo sigue en `master`, versión `0.2.0.dev0`. Cerrada el 2026-10-15 como `0.2.0`, sin publicar (ver abajo). |

## Alcance de la v0.2

Decidido el 2026-10-14. Las mismas reglas que en la v0.1: el servidor es determinista, la
honestidad la aplica el código y nada de esto hace llamadas de red.

| Pieza | Detalle |
|---|---|
| Exportar a JSON Resume | Una variante en un idioma sale como JSON Resume: los puestos con sus bullets, la formación, las certificaciones, los idiomas y las skills por grupo. Las skills F salen en su propio grupo "Familiarity" con `level: Familiarity`, y las X nunca salen. Volver a importar el archivo da el mismo perfil. Herramienta `export_json_resume` y `honest-cv export`. |
| Plantillas propias | honest-cv es genérico: sirve para cualquier profesión, no solo desarrollo. Una plantilla de skills es cualquier Markdown con el formato de los checklists. Las que la persona guarda en `<perfil>/checklists/` aparecen en `checklist_list` junto a las incluidas y se combinan con `checklist_new`, que también acepta una ruta. Después de aplicarla, `checklist_apply` devuelve las skills P y L que ningún bullet respalda, y la entrevista pide un logro real por cada una. Así la plantilla sirve para llenar rápido o como guion de la entrevista. |
| Seguimiento de postulaciones | Un `applications.yaml` en la carpeta del perfil: empresa, puesto, enlace, fecha, variante e idioma, archivos enviados (CV y carta), estado (`draft`, `applied`, `interview`, `offer`, `rejected`, `withdrawn`) con su historial de fechas, y notas. Herramientas `log_application` y `list_applications`, y `honest-cv apps`. |
| Sugerencias para LinkedIn | Desde una variante: titular (máx. 220 caracteres), "Acerca de" (máx. 2,600), la descripción de cada puesto con sus bullets (máx. 2,000) y las skills P y L, nunca F ni X. Cada texto lleva su conteo contra el límite. El cliente puede pulir la redacción con un prompt, pero el texto final pasa por `check_claims`. Herramienta `linkedin_profile`, prompt `linkedin_profile` y `honest-cv linkedin`. |
| Checklist de arquitectura | Uno incluido, `software-architecture`, para quien diseña sistemas: estilos y patrones, integración, atributos de calidad, datos y la práctica (ADRs, revisiones, deuda técnica). Pedido al probar como usuario nuevo con un perfil de desarrollador, arquitecto y gerente. |

Orden: exportar (reutiliza el documento del CV y el importador para la prueba de ida y vuelta),
plantillas propias, postulaciones, LinkedIn.

### Lo que agregó la prueba como usuario nuevo (2026-10-14 y 15)

La prueba completa desde cero, con un perfil real de desarrollador, arquitecto y gerente, sacó
huecos que entraron a la v0.2:

| Pieza | Detalle |
|---|---|
| Cursos | Sección propia (`courses`). Un curso sin examen no es una certificación ni una skill. |
| Publicaciones | Libros, artículos y papers (`upsert_publication`, `remove_publication`), cada variante elige cuáles muestra. Lo autopublicado se dice en `venue`. Se importan de LinkedIn y JSON Resume. La entrevista pregunta una vez por certificaciones, cursos y publicaciones. |
| Checklist | Ejemplos marcados en el encabezado, que el lector ignora por estar en un comentario. Una marca con espacios (`[ P]`) cuenta, y un texto que no entiende se reporta en vez de saltarse en silencio. |
| Logros por vacante | Ahora solo se piden logros de las skills P principales (★ o en una variante). El resto espera a una vacante que las pida: `gap_report` → `no_achievement`. |
| Postulaciones | Guardan el texto de la vacante en `<perfil>/posts/`, porque los enlaces caducan, y qué preparar para la entrevista (`prep`). |
| Sinónimos en español | Liderazgo, gestión de personas, revisión de código, patrones de diseño, agentes de IA… En una carta, las prácticas no son afirmaciones que verificar. |
| Conversación | El cliente mantiene el idioma de la persona aunque las herramientas respondan en inglés. Un "sí" a una lista no es evidencia. La entrevista avisa que es larga y se puede hacer por sesiones. |

### Pendiente para publicar

- Decidido el 2026-10-15: se publica directo la 0.2 como primera versión. La 0.1 nunca sale; la
  rama `release/0.1` queda como registro.
- `.github/workflows/release.yml` publica sin contraseñas (trusted publishing): a mano va a
  TestPyPI; un tag `vX.Y.Z` va a PyPI y luego al registro de MCP. Antes hace falta la cuenta de
  PyPI con un "pending publisher" para este workflow (entorno `pypi`) y, para la prueba, lo mismo
  en TestPyPI (entorno `testpypi`).
- Publicada la 0.2.0 el 2026-10-15 en PyPI y en el registro de MCP. Issues abiertos: preparar
  entrevistas (#2), más plantillas (#3), checklists por idioma (#4), `gap_report` con skills marcadas
  pero pendientes en el checklist (#5) y copia de los archivos enviados (#6).
- 0.2.1 (2026-10-15): el README paso a paso. 0.3.0 (2026-10-15): cierra #2, #4, #5 y #6, y una
  primera tanda de 10 plantillas para #3, que queda abierto a contribuciones.
- 0.3.1 (2026-10-15): cierra #3 con 8 plantillas más; las 26 incluidas tienen versión en español.
