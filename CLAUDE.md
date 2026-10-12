# honest-cv

Generador de CVs honestos y aptos para ATS, con servidor MCP, CLI y skill de Claude Code. El plan y el alcance de la v0.1 están en `docs/PLAN.md`, que es la fuente de verdad del alcance.

## Reglas del proyecto

- **Repo público.** Nunca se commitean datos reales de personas. Para tests, demos, el README y los GIFs se usa solo `examples/ada/`, que es ficticio. Los perfiles reales van en `profiles/`, que está en `.gitignore`.
- **La honestidad la aplica el código, no un prompt.**
  - Una skill `F` siempre se renderiza con la etiqueta "Familiarity" / "Familiaridad".
  - Una skill `X` nunca se renderiza.
  - Para subir de nivel una skill hacen falta `evidence` y confirmación humana.
  - Cada una de estas reglas tiene su test.
- **El servidor es determinista y no tiene API key.**
  - El LLM vive en el cliente MCP.
  - El servidor valida, genera, verifica y mide.
- **Las garantías de ATS son invariantes y se prueban en cada build:**
  - Una sola columna, sin tablas de maquetación, sin imágenes ni iconos, sin encabezado ni pie de página.
  - Las ligaduras están desactivadas.
  - El orden del código fuente es el orden de lectura. Las fechas van en línea con el puesto, nunca en una caja alineada a la derecha.
  - El texto es extraíble con pypdf y pdfminer.six.
- **Alcance.** Lo que no esté en "Lo que entra en la v0.1" de `docs/PLAN.md` va a un issue o a la v0.2, no al código.

## Stack

- Python ≥ 3.11.
- Empaquetado con `uv`; se distribuye por PyPI y se ejecuta con `uvx honest-cv`.
- SDK oficial de MCP (`mcp` 2.x, `MCPServer`, antes FastMCP) con transporte stdio. La confirmación humana usa elicitation mediante `Resolve`/`Elicit`.
- pydantic, PyYAML, python-docx, pypdf y pdfminer.six.
- Motor de PDF: Typst (wheel `typst` de pip), con Carlito empaquetada. Ver `docs/spike-pdf-engine.md`.

## Convenciones

- El código, los nombres y los comentarios van en inglés. Los documentos de planeación pueden ir en español.
- El README principal va en inglés, con una versión en español en `README.es.md`.
- Commits pequeños, uno por entregable del calendario.
