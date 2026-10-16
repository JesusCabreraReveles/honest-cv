# honest-cv

[![CI](https://github.com/JesusCabreraReveles/honest-cv/actions/workflows/ci.yml/badge.svg)](https://github.com/JesusCabreraReveles/honest-cv/actions/workflows/ci.yml)
[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-blue.svg)](LICENSE)

<!-- mcp-name: io.github.JesusCabreraReveles/honest-cv -->

**CVs honestos, aptos para ATS y adaptados a cada puesto, generados por tu agente de IA.**
honest-cv es un servidor MCP, una CLI y una skill de Claude Code. Guarda una sola fuente de verdad
sobre tu experiencia y la convierte en un PDF y un DOCX para cada tipo de puesto. Nunca afirma una
skill que no tienes.

[Read in English](README.md)

![Demo: checklists de skills, incluida una propia, el puntaje contra una vacante, un build verificado, una carta que rechaza una skill que la persona no tiene, los textos de LinkedIn y el registro de la postulación](docs/assets/demo.gif)

## Por qué

Muchos CVs que no reciben llamadas no fallan por el diseño. Fallan por el enfoque, y por detalles
que rompen la extracción de texto sin que nadie lo note. La IA facilita el problema contrario: un
modelo llena el CV de palabras clave que no puedes defender en una entrevista. honest-cv se basa
en tres ideas:

- **La honestidad la aplica el código, no un prompt.** Cada skill tiene un nivel. Una skill de
  familiaridad siempre sale etiquetada como tal, y una que no tienes nunca se imprime. Subir de
  nivel requiere evidencia escrita y *tu* confirmación, que el servidor te pide directamente. El
  modelo no puede confirmar por ti.
- **Las brechas se miden contra tu propio inventario.** Para cada palabra clave que pide una
  vacante, honest-cv te dice cuál de tres casos es:
  - la tienes, pero este CV no la muestra;
  - solo la conoces a nivel de familiaridad;
  - no la tienes.
- **La compatibilidad con ATS se comprueba en cada build.** Cada PDF pasa por dos extractores de
  texto (pypdf y pdfminer.six). El build revisa que el texto sea de una columna, que no tenga
  ligaduras, que cada fecha quede en la línea de su puesto, que el orden de lectura sea el correcto
  y que estén todos los bullets.

El servidor es determinista y no necesita API key. El modelo de tu cliente MCP conduce la
conversación; honest-cv valida, genera, verifica y mide. Guarda tu perfil en una carpeta de tu
máquina y nunca lo envía a ningún lado. En [Privacidad](#privacidad) se explica qué hace con él tu
cliente de IA.

<p align="center"><img src="docs/assets/ada-platform-en.png" width="560" alt="CV de una página generado para Ada Example, una persona ficticia"></p>

## Inicio rápido

honest-cv necesita [uv](https://docs.astral.sh/uv/). Typst y las fuentes vienen dentro del
paquete, así que no hay que instalar nada más.
Funciona en Linux (glibc) con x86_64 y ARM64, en macOS con Intel y Apple
Silicon, y en Windows con x64. Alpine Linux y Windows en ARM no están soportados, porque el paquete
`typst` no publica wheels para ellos.

### Claude Code

```bash
claude mcp add honest-cv -- uvx honest-cv serve --profile ~/cv-profile
```

Para instalar también la skill, que guía la entrevista y la adaptación:

```bash
mkdir -p ~/.claude/skills/honest-cv
curl -fsSL https://raw.githubusercontent.com/JesusCabreraReveles/honest-cv/master/skills/honest-cv/SKILL.md \
  -o ~/.claude/skills/honest-cv/SKILL.md
```

Después sigue [Tu primer CV, paso a paso](#tu-primer-cv-paso-a-paso).

### Cursor

Agrega esto a `~/.cursor/mcp.json`, o a `.cursor/mcp.json` dentro de un proyecto:

```json
{
  "mcpServers": {
    "honest-cv": {
      "command": "uvx",
      "args": ["honest-cv", "serve", "--profile", "/ruta/absoluta/a/cv-profile"]
    }
  }
}
```

### Claude Desktop

Edita `claude_desktop_config.json`:
- en macOS, `~/Library/Application Support/Claude/`;
- en Windows, `%APPDATA%\Claude\`.

Agrega el mismo bloque `mcpServers` del ejemplo de Cursor y reinicia la app. Si la app no encuentra
`uvx`, usa su ruta absoluta (`which uvx`).

### Cómo confirma cada cliente una subida de nivel

Subir de nivel una skill necesita tu propia confirmación, que el servidor pide mediante
*elicitation* de MCP. No todos los clientes lo soportan todavía:

| Cliente | Dónde confirmas |
|---|---|
| Claude Code | En el chat: un formulario con un campo "no / sí" por cada subida, hasta 10 a la vez. Solo se guardan las que respondes "sí"; Decline no guarda nada. |
| Claude Desktop | En una terminal. El servidor rechaza el cambio y te da el comando para ejecutarlo: `uvx honest-cv skill <perfil> "<nombre>" <nivel> --evidence "..."`. |
| Otros clientes | En el chat si soportan *elicitation*; si no, en una terminal como arriba. |

## Tu primer CV, paso a paso

Este recorrido usa Claude Code; con cualquier cliente MCP funciona igual, solo cambia la
instalación.

**1. Instala uv y agrega honest-cv.** Se hace una sola vez. En macOS o Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh        # Windows: ver docs.astral.sh/uv
claude mcp add honest-cv -- uvx honest-cv serve --profile ~/cv-profile
```

`~/cv-profile` es la carpeta donde vivirá tu perfil. No tiene que existir todavía, y no debe estar
dentro de un repositorio público. Instala también la skill ([Claude Code](#claude-code), arriba).

**2. Empieza la entrevista.** Abre Claude Code en cualquier carpeta (`claude`) y escribe
*"entrevístame para mi CV"*, o ejecuta `/mcp__honest-cv__interview`. El asistente mantiene tu
idioma durante toda la conversación. Puedes contestar en voz con el dictado de tu sistema (en
macOS: Ajustes del Sistema → Teclado → Dictado): te lee los nombres y los números antes de
guardarlos, porque el dictado los confunde. Va más o menos así:

> **Tú:** Entrevístame para mi CV.
>
> **Asistente:** La carpeta `~/cv-profile` todavía no existe. ¿La creo? … La entrevista completa
> puede llevar algunas horas, pero todo se guarda sobre la marcha. Para un primer CV basta una
> sesión con tus datos de contacto, tus dos puestos más recientes y el checklist de skills.
> ¿Tienes la exportación de datos de LinkedIn o un JSON Resume para empezar?

- **Importa, si puedes** (opcional). Descarga la exportación de datos de LinkedIn (ver
  [Importar](#importa-lo-que-ya-tienes)) y dale al asistente la ruta del ZIP. Entran tus puestos,
  tu educación y tus logros; las skills llegan sin nivel para que tú las marques.
- **Contacto, puestos y educación.** Pregunta unos cuantos datos a la vez y te lee los nombres y
  los números antes de guardarlos. Luego pregunta una vez por certificaciones, cursos y lo que
  hayas escrito.
- **Logros, puesto por puesto.** Por cada puesto: qué hacía el equipo, qué hiciste *tú* y qué
  cambió, con números. Redacta un bullet y lo guarda solo cuando apruebas la redacción.
- **Skills.** Te ofrece un checklist, por ejemplo `backend-jvm` + `engineering-lead`, o uno tuyo
  para cualquier profesión. Abre `~/cv-profile/checklist.md` en tu editor, pon P, L, F o X en cada
  línea, escribe después de " — " dónde la usaste, guarda y dile al asistente *"listo"*. Te pide
  por grupos la evidencia que falte. Después un formulario te pide confirmar las subidas de nivel:
  solo se guarda lo que respondes "sí".
- **Tus logros más grandes.** Un logro suele cubrir varias skills. Luego pregunta por tus skills P
  principales que todavía ningún logro muestra; las demás pueden esperar a una vacante.

**3. Genera tu primer CV.** El asistente propone una *variante* por cada tipo de puesto al que
aplicas (por ejemplo "platform" o "engineering manager"): título, resumen y qué bullets mostrar.
Cuando la apruebas:

> **Tú:** Genera mi CV de platform en inglés y en español.

El PDF y el DOCX quedan en `~/cv-profile/out/`, ya verificados para ATS. Sin cliente de IA, lo
mismo es `uvx honest-cv build ~/cv-profile -v platform -l es`.

**4. Adáptalo a una vacante.** Pega la vacante, o ejecuta `/mcp__honest-cv__tailor_for_job`:

> **Tú:** Esta es una vacante: *(pégala)*. ¿Qué tanto encajo y qué debería cambiar?

Recibes la cobertura de cada variante, las palabras clave que faltan separadas en *la tienes pero
este CV no la muestra*, *solo familiaridad* y *no la tienes*, además de las que marcaste en tu
checklist pero aún sin evidencia (te pregunta dónde las usaste), una variante adaptada para aprobar y
el build. Después puede redactar una carta de presentación, que `check_claims` revisa antes de
generarla, y registrar la postulación con el texto de la vacante y lo que conviene preparar para
la entrevista. Cuando te den la entrevista, *"ayúdame a preparar la entrevista"* redacta las
preguntas probables con respuestas tomadas de tus propios logros.

**5. Regresa cuando quieras.** Di *"sigamos con la entrevista de mi CV"*: empieza por lo que falta.
Para actualizar tu perfil de LinkedIn, di *"actualiza mi LinkedIn"*.

## Tu perfil

Un perfil es una carpeta con cuatro archivos YAML. Créalo con `honest-cv init ~/cv-profile`, o deja
que el prompt `interview` lo llene contigo. Mantenlo fuera de repositorios públicos.

| Archivo | Qué guarda |
|---|---|
| `profile.yaml` | Datos de contacto, puestos, educación, certificaciones, publicaciones, cursos e idiomas. |
| `bullets.yaml` | Un pool de logros, cada uno con `id`, `role` y `tags`. |
| `skills.yaml` | Tu inventario de skills, con niveles y evidencia. |
| `variants.yaml` | Un plan de CV por tipo de puesto. Una variante puede heredar de otra con `extends:`. |

Cualquier texto puede ser una sola cadena o una por idioma: `{en: ..., es: ...}`. Los CVs se pueden
generar en inglés y en español.

| Nivel | Significado | En el CV |
|---|---|---|
| `P` | La usaste en producción en un empleo | Se muestra |
| `L` | Proyecto propio o laboratorio | Se muestra |
| `F` | Familiaridad | Solo en la línea etiquetada "Familiaridad" |
| `X` | No la tienes | Nunca se muestra, pero se registra para que las brechas sean honestas |

### Checklists de skills

Registrar decenas de skills una pregunta a la vez es lento. Un checklist es un archivo Markdown que
marcas en tu editor, una letra por línea:

```markdown
## Messaging and streaming
evidence: Plataforma de pagos en Acme, 2020–2026
- [P] Kafka — flujo de conciliación, 2M eventos al día · años: 6 · último uso: 2026
- [F] RabbitMQ — un taller y los tutoriales oficiales
- [X] NATS
```

El texto después de " — " es la evidencia, y una línea `evidence:` bajo un título cubre esa
sección. Las líneas sin evidencia nunca se guardan: regresan como pendientes y tu asistente te
pregunta por ellas en grupos. Las subidas de nivel se confirman una sola vez para todo el archivo.

Los checklists vienen en inglés y en español (`--lang es`): los nombres en español son
sinónimos de los nombres en inglés, así que una skill que marcas en español también coincide con
una vacante en inglés.

```bash
honest-cv checklist list --lang es                           # backend-jvm, platform-sre, ...
honest-cv checklist new ~/cv-profile backend-jvm engineering-lead --lang es
honest-cv checklist apply ~/cv-profile ~/cv-profile/checklist.md
```

**Sirve para cualquier profesión.** Los checklists incluidos cubren software (backend, frontend,
móvil, datos, platform/SRE, QA, seguridad, ML/IA, embebidos, videojuegos, arquitectura y liderazgo
de ingeniería), además de análisis de datos/BI, gestión de producto y de proyectos, diseño UX,
marketing, ventas, atención a clientes, finanzas y contabilidad, recursos humanos, cadena de
suministro, enfermería y docencia. Una
plantilla es solo una lista Markdown con este formato: guarda la tuya (o una que te compartan)
en `~/cv-profile/checklists/` y aparece en `checklist list` y se combina con las demás en
`checklist new`, que también acepta una ruta. Una plantilla puede declarar sinónimos, como
`same: Work Breakdown Structure = WBS = EDT`, y el puntaje contra la vacante, las brechas y la
revisión de cartas los usan, junto con sus nombres de skills. Empieza desde
[`examples/checklists/event-planning.md`](examples/checklists/event-planning.md). También puedes aplicar un archivo que ya marcaste tú,
en inglés o en español (`años`, `último uso`). Al terminar, honest-cv te dice qué skills P y L no
respalda ningún logro, y tu asistente te pide un ejemplo real de cada una.

```bash
honest-cv checklist list ~/cv-profile                        # también las tuyas, p. ej. contabilidad
honest-cv checklist new ~/cv-profile contabilidad engineering-lead
```

Los checklists nuevos para otros tipos de puesto son bienvenidos: consulta
[CONTRIBUTING.md](CONTRIBUTING.md).

En [`examples/ada/`](examples/ada/) hay un perfil completo y ficticio, con tres variantes, una
vacante y sus palabras clave.

## Privacidad

- **honest-cv no hace ninguna llamada de red.** No hay cuentas, telemetría ni API keys. Tu perfil
  es una carpeta de archivos YAML en tu máquina, y el motor de PDF y las fuentes corren en local.
  Puedes comprobarlo: todos los comandos funcionan con la red desconectada.
- **Tu cliente de IA es otro asunto.** Lo que su modelo lee por medio de las herramientas llega al
  proveedor de ese modelo, bajo sus términos, como cualquier otra cosa que compartas en un chat.
  Eso incluye tus skills, tus bullets y el texto de tus CVs.
- **Algunos clientes copian archivos a la nube.** Para editar archivos directamente, Claude Desktop
  puede pedir acceso a la carpeta del perfil y avisar que los archivos salen de tu dispositivo. Las
  herramientas de edición de honest-cv lo hacen innecesario: rechaza el acceso y pide al asistente
  que use las herramientas.
- **Si no quieres que nada salga de tu máquina,** usa solo la CLI (`build`, `verify`, `score`,
  `skill`) y edita tú los archivos YAML.

## Importa lo que ya tienes

`honest-cv import` lee un archivo [JSON Resume](https://jsonresume.org) o la exportación de datos de
LinkedIn (Ajustes → Privacidad de datos → Descargar tus datos, un ZIP con CSVs, o su carpeta si tu
navegador lo descomprimió). Pide el archivo completo: el básico, el que ofrece al elegir archivos,
solo trae tu titular y tu resumen, sin puestos.
Contacto, puestos, formación, certificaciones, idiomas y los logros de cada puesto pasan a tu
perfil. Si trae titular y resumen, también crea una primera variante, así que `build` funciona de
inmediato.

- Solo agrega lo que le falta a tu perfil y nunca sobrescribe. Prueba primero con `--dry-run`.
- Los logros importados llevan la etiqueta `imported`: revisa su redacción.
- **Las skills llegan sin nivel**, porque ningún formato dice si usaste una skill en producción.
  Van a `imported-skills.md`, un checklist para que las marques.

El PDF de "Guardar como PDF" de LinkedIn cambia de formato sin aviso, así que no se interpreta
automáticamente: con un cliente MCP, el prompt `import_linkedin_pdf` lee su texto y te propone cada
sección para que la apruebes.

## Seguimiento de postulaciones

`honest-cv apps` lleva un registro en `applications.yaml`, dentro de la carpeta de tu perfil: qué
variante y qué archivos mandaste a qué empresa, y cada estado con su fecha (`draft`, `applied`,
`interview`, `offer`, `rejected`, `withdrawn`). Si registras otra vez la misma empresa y puesto, se
actualiza. Con un cliente MCP, tu asistente te ofrece registrar la postulación después de generar el
CV o la carta, y `list_applications` te señala las que llevan dos semanas sin noticias. También
guarda una copia de cada archivo que enviaste en `sent/`, porque el siguiente build sobrescribe
`out/`, y el texto de la vacante en `posts/`, porque los enlaces caducan, y lo que te conviene preparar
para la entrevista; pregúntale a tu asistente "¿qué tenía que preparar para Acme?".

Cuando te den la entrevista, di *"ayúdame a preparar la entrevista de Acme"* (o usa el prompt
`interview_prep`). Para cada palabra clave de la vacante guardada, honest-cv muestra tu nivel, tu
evidencia y los bullets que la respaldan, empezando por los del CV que mandaste. Tu asistente
redacta las preguntas probables con respuestas STAR tomadas solo de esos bullets, respuestas
honestas para lo que solo conoces como familiaridad o no tienes, y preguntas para hacerles. Las
notas que apruebes se guardan en `prep/`. Sin cliente de IA: `honest-cv apps prep ~/cv-profile
acme_sre -k "Kafka,Scala"`.

## LinkedIn

`honest-cv linkedin` convierte una variante en los textos de LinkedIn, cada uno dentro de su límite:
el titular (tu puesto y hasta cinco skills de producción), "Acerca de" (el resumen y los bullets de
impacto), una descripción por puesto con sus bullets y la lista de skills. Los escribe en un archivo
Markdown para copiarlos. Las skills son solo P y L: LinkedIn no puede etiquetar la familiaridad, así
que las F quedan fuera, y las X nunca aparecen. Con un cliente MCP, el prompt `linkedin_profile`
pule la redacción y la revisa con `check_claims`.

## Exportar

En sentido contrario, `honest-cv export` escribe una variante como JSON Resume para otras
herramientas y sitios de CV, con las mismas reglas que el CV: las skills X nunca aparecen y las F
solo en un grupo "Familiaridad" con ese nivel.

## Cartas de presentación

El prompt `cover_letter` redacta una carta de una página para una vacante con tus propios bullets.
Antes de generarla, `check_claims` revisa el texto contra tu perfil:

- **Los problemas bloquean la carta:** una skill que marcaste X, o una skill de familiaridad
  presentada como experiencia ("uso Rust en producción" cuando Rust es F; "tengo familiaridad con
  Rust" está bien).
- **Las advertencias son para que las revises:** una tecnología que ni tu inventario ni tus
  bullets muestran, o un número que no aparece en tu perfil. Si es cierto, regístralo primero; si
  no, sale de la carta.

La carta usa las fuentes del CV y pasa las mismas verificaciones ATS. Sin un cliente de IA,
escríbela en un archivo de texto (párrafos separados por una línea en blanco) y usa
`honest-cv letter check` y `letter build`.

## CLI

Ejecuta cualquier comando con `uvx honest-cv ...`, o instálalo una vez con
`uv tool install honest-cv` para escribir solo `honest-cv`.

```bash
honest-cv init ~/cv-profile                        # crea las plantillas del perfil
honest-cv build ~/cv-profile -v backend -l en -l es # PDF + DOCX, verificados en cada build
honest-cv verify cualquier-cv.pdf --text            # revisa cualquier PDF, aunque lo hayas hecho en otro lado
honest-cv score ~/cv-profile -k "Kubernetes,Go" -p "Rust"   # cobertura por variante, con brechas
honest-cv skill ~/cv-profile "Rust" L --evidence "CLI en GitHub"  # te pide confirmar
honest-cv import ~/cv-profile linkedin-export.zip --dry-run         # o resume.json
honest-cv export ~/cv-profile -v backend -l es                       # JSON Resume
honest-cv apps log ~/cv-profile --company Acme --role "SRE" -s applied -v platform
honest-cv apps list ~/cv-profile                                     # la más reciente primero
honest-cv apps prep ~/cv-profile acme_sre -k "Kafka,Scala"           # qué respalda cada palabra clave, para la entrevista
honest-cv linkedin ~/cv-profile -v platform -l es                    # textos para pegar en LinkedIn
honest-cv remove skill ~/cv-profile "Kafka"                          # te pide confirmar
honest-cv letter check ~/cv-profile carta.txt -k "Kubernetes,Go"      # afirmaciones que tu perfil no respalda
honest-cv letter build ~/cv-profile carta.txt --company Acme --role "Platform Engineer" -l es
honest-cv serve --profile ~/cv-profile              # el servidor MCP, por stdio
```

`verify` funciona con cualquier PDF. Usa `--text` para ver exactamente lo que extrae un parser. Su
revisión `single_column` también detecta un defecto común: una fecha alineada a la derecha, que los
parsers separan de su puesto.

## Herramientas y prompts MCP

| Nombre | Qué hace |
|---|---|
| `init_profile` | Crea la carpeta del perfil con plantillas comentadas. |
| `get_inventory` | Devuelve tus skills agrupadas por nivel, con años y evidencia. |
| `set_skill` | Agrega o cambia una skill. Para subir de nivel exige evidencia y te pide confirmar. |
| `set_skills` | Agrega o cambia varias skills a la vez. Las subidas de nivel se confirman con una sola pregunta que lista cada cambio. |
| `checklist_list` | Lista los checklists incluidos. |
| `checklist_new` | Combina checklists incluidos en un archivo, prellenado con tu inventario. |
| `checklist_apply` | Guarda las skills marcadas en un checklist y devuelve las líneas que todavía necesitan evidencia. |
| `add_bullet` | Agrega un logro al pool. |
| `remove_skill`, `remove_bullet`, `remove_role`, `remove_publication` | Borran definitivamente y quitan cada uso en las variantes. Un puesto con bullets necesita `with_bullets`. Los clientes piden permiso antes de usarlas. |
| `set_contact` | Cambia los datos de contacto: nombre, email, teléfono, ubicación y links. |
| `set_profile_details` | Reemplaza la lista de certificaciones, la de cursos y la línea de idiomas. |
| `upsert_role` | Agrega un puesto en orden de fechas, o cambia campos de uno existente. |
| `upsert_education` | Agrega o cambia una entrada de formación. |
| `upsert_publication` | Agrega o cambia un libro, artículo o paper que la persona escribió. Cada variante muestra todos, o los que liste. |
| `save_variant` | Agrega o reemplaza una variante. Revisa todas sus referencias antes de guardar. |
| `list_variants` | Lista las variantes ya con la herencia aplicada, con el texto de sus bullets y los bullets que ninguna usa. |
| `build_cv` | Genera el PDF y/o el DOCX y lo verifica. |
| `verify_pdf` | Pasa las revisiones ATS a cualquier PDF y devuelve su texto extraído. |
| `score_job` | Mide la cobertura de palabras clave de cada variante. El cliente extrae las palabras clave. |
| `gap_report` | Agrupa las palabras clave que faltan según lo que honestamente puedes hacer con cada una. |
| prompt `interview` | Llena tu inventario y tu pool de bullets, una pregunta a la vez. |
| `check_claims` | Revisa cualquier texto contra tu perfil: bloquea skills X y la familiaridad presentada como experiencia, y señala lo que el perfil no muestra. |
| `build_letter` | Genera la carta de presentación en PDF y DOCX, de una página, con las verificaciones ATS del CV. Se niega mientras `check_claims` encuentre problemas. |
| prompt `tailor_for_job` | Puntúa las variantes, explica las brechas, adapta una variante y vuelve a generar el CV. |
| prompt `cover_letter` | Redacta una carta para una vacante con tus bullets, revisa sus afirmaciones y la genera. |
| `import_profile` | Importa JSON Resume o la exportación de datos de LinkedIn, agregando solo lo que falta. Con un PDF de LinkedIn devuelve el texto. |
| `export_json_resume` | Exporta una variante como JSON Resume; las skills X nunca aparecen y las F conservan su etiqueta. |
| `log_application` | Registra una postulación (empresa, puesto, variante del CV, archivos enviados, el texto de la vacante, qué preparar) o un nuevo estado, con su fecha. |
| `linkedin_profile` | Titular, "Acerca de", descripciones de puestos y skills (solo P y L) de LinkedIn a partir de una variante, dentro de sus límites. |
| `list_applications` | Lista las postulaciones, la más reciente primero, con un conteo por estado y las que llevan 14 días o más sin noticias. |
| `interview_prep` | Para una postulación: la vacante guardada y, por palabra clave, tu nivel, tu evidencia y los bullets que la respaldan. Guarda las notas de preparación. |
| prompt `import_linkedin_pdf` | Convierte el PDF de "Guardar como PDF" de LinkedIn en un perfil, sección por sección, con tu aprobación. |
| prompt `linkedin_profile` | Pule los textos de LinkedIn de una variante sin agregar afirmaciones, revisados con `check_claims`. |
| prompt `interview_prep` | Prepara una entrevista: preguntas probables, respuestas STAR con tus propios bullets y respuestas honestas para los huecos. |

## Garantías ATS

La plantilla las aplica. `verify` las revisa en cada build, y los tests corren en CI en Linux,
macOS y Windows:

- Una sola columna. Sin tablas de maquetación, imágenes, iconos, encabezados ni pies de página.
- Sin ligaduras, sin kerning, sin división silábica, y términos como "CI/CD", las URLs y los
  emails nunca se parten entre líneas.
- El orden de lectura es el orden del código fuente. Las fechas van en la misma línea que su puesto.
- El texto lo extraen tanto pypdf como pdfminer.six, y los dos coinciden.
- Las fuentes (Carlito, con las mismas métricas que Calibri) van incrustadas y son idénticas en
  cualquier máquina.

## Desarrollo

```bash
uv sync
uv run pytest
uv run honest-cv build examples/ada -l en -l es
```

El `.mcp.json` del repositorio registra `honest-cv-dev` con el perfil ficticio, para que Claude
Code use tu copia de trabajo dentro de esta carpeta. Consulta [CONTRIBUTING.md](CONTRIBUTING.md).

## Licencia

MIT. La fuente Carlito incluida usa la SIL Open Font License; consulta
`src/honest_cv/render/fonts/OFL.txt`.
