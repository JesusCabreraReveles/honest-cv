# honest-cv

[![CI](https://github.com/JesusCabreraReveles/honest-cv/actions/workflows/ci.yml/badge.svg)](https://github.com/JesusCabreraReveles/honest-cv/actions/workflows/ci.yml)
[![Licencia: MIT](https://img.shields.io/badge/licencia-MIT-blue.svg)](LICENSE)

**CVs honestos, aptos para ATS y adaptados a cada puesto, generados por tu agente de IA.**
honest-cv es un servidor MCP, una CLI y una skill de Claude Code. Guarda una sola fuente de verdad
sobre tu experiencia y la convierte en un PDF y un DOCX para cada tipo de puesto. Nunca afirma una
skill que no tienes.

[Read in English](README.md)

![Demo: puntuar una vacante, generar una variante y verificarla](docs/assets/demo.gif)

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

Después empieza con *"entrevístame para mi CV"*, o ejecuta `/mcp__honest-cv__interview`.

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

> **Subir de nivel una skill necesita un cliente con soporte de *elicitation* de MCP**, para que el
> servidor te pida la confirmación. En un cliente sin ese soporte, el servidor rechaza el cambio y
> te da un comando para ejecutarlo en la terminal:
> `uvx honest-cv skill <perfil> "<nombre>" <nivel> --evidence "..."`.

## Tu perfil

Un perfil es una carpeta con cuatro archivos YAML. Créalo con `honest-cv init ~/cv-profile`, o deja
que el prompt `interview` lo llene contigo. Mantenlo fuera de repositorios públicos.

| Archivo | Qué guarda |
|---|---|
| `profile.yaml` | Datos de contacto, puestos, educación, certificaciones e idiomas. |
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

En [`examples/ada/`](examples/ada/) hay un perfil completo y ficticio, con tres variantes, una
vacante y sus palabras clave.

## Privacidad

- **honest-cv no hace ninguna llamada de red.** No hay cuentas, telemetría ni API keys. Tu perfil
  es una carpeta de archivos YAML en tu máquina, y el motor de PDF y las fuentes corren en local.
  Puedes comprobarlo: todos los comandos funcionan con la red desconectada.
- **Tu cliente de IA es otro asunto.** Lo que su modelo lee por medio de las herramientas llega al
  proveedor de ese modelo, bajo sus términos, como cualquier otra cosa que compartas en un chat.
  Eso incluye tus skills, tus bullets y el texto de tus CVs.
- **Algunos clientes copian archivos a la nube.** Para editar archivos, Claude Desktop puede pedir
  acceso a la carpeta del perfil y avisar que los archivos salen de tu dispositivo. Claude Code los
  edita donde están.
- **Si no quieres que nada salga de tu máquina,** usa solo la CLI (`build`, `verify`, `score`,
  `skill`) y edita tú los archivos YAML.

## CLI

Ejecuta cualquier comando con `uvx honest-cv ...`, o instálalo una vez con
`uv tool install honest-cv` para escribir solo `honest-cv`.

```bash
honest-cv init ~/cv-profile                        # crea las plantillas del perfil
honest-cv build ~/cv-profile -v backend -l en -l es # PDF + DOCX, verificados en cada build
honest-cv verify cualquier-cv.pdf --text            # revisa cualquier PDF, aunque lo hayas hecho en otro lado
honest-cv score ~/cv-profile -k "Kubernetes,Go" -p "Rust"   # cobertura por variante, con brechas
honest-cv skill ~/cv-profile "Rust" L --evidence "CLI en GitHub"  # te pide confirmar
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
| `add_bullet` | Agrega un logro al pool. |
| `list_variants` | Lista las variantes ya con la herencia aplicada, con el texto de sus bullets y los bullets que ninguna usa. |
| `build_cv` | Genera el PDF y/o el DOCX y lo verifica. |
| `verify_pdf` | Pasa las revisiones ATS a cualquier PDF y devuelve su texto extraído. |
| `score_job` | Mide la cobertura de palabras clave de cada variante. El cliente extrae las palabras clave. |
| `gap_report` | Agrupa las palabras clave que faltan según lo que honestamente puedes hacer con cada una. |
| prompt `interview` | Llena tu inventario y tu pool de bullets, una pregunta a la vez. |
| prompt `tailor_for_job` | Puntúa las variantes, explica las brechas, adapta una variante y vuelve a generar el CV. |

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
