# Spike del día 1: motor PDF (Typst frente a Chrome headless)

Fecha: 2026-10-11. Los scripts están en `spike/`. Para reproducirlo:

```
uv run --with typst python spike/render.py
uv run --with typst python spike/extract.py
```

## Qué se probó

Se generó el mismo CV ficticio de una columna con los dos motores:

- Typst 0.15, con el wheel `typst` de pip.
- Chrome headless, con `--print-to-pdf`.

Después se extrajo el texto con pypdf y con pdfminer.six. El texto de prueba incluye:

- Palabras con riesgo de ligadura: fi, fl, ffi, ff.
- Acentos en español.
- Rayas, comillas y viñetas.

## Resultados

| Criterio | Typst | Chrome |
|---|---|---|
| Glifos de ligadura (U+FB00–FB04) en el texto extraído | Ninguno | Ninguno |
| Guiones suaves o cortes de palabra | Ninguno (`hyphenate: false`) | Ninguno |
| Acentos y ñ | Correctos | Correctos |
| Viñetas en el texto extraído | Sí, sale `•` | No: el marcador de lista se dibuja como gráfico y se pierde |
| Orden de lectura con pypdf | Correcto | Correcto |
| Orden con pdfminer, con la fecha alineada a la derecha | La fecha se separa de su línea | La fecha se va al final del documento |
| Tiempo de render | 0.06 s | 1.9 s |
| Instalación | Wheel de pip, sin dependencias del sistema | Requiere Chrome instalado |

Hallazgos adicionales:

- **Typst mapea las ligaduras a Unicode.** Aun con ligaduras activadas en Libertinus Serif, el texto extraído sale `fi` y no `ﬁ`. Las ligaduras se mantienen apagadas como invariante, pero el riesgo con Typst es menor.
- **La fecha alineada a la derecha se rompe con pdfminer en los dos motores.** Un hueco horizontal grande parte la línea en dos bloques de texto. El problema está en la plantilla, no en el motor. La solución verificada es poner la fecha en línea con el puesto: `Staff Engineer — Company · 2020 – Present` se extrae intacto. El `.row` con flexbox que usaba `~/code/cv` tenía este mismo defecto.
- **Las comillas tipográficas:** Typst convierte `"` en `“ ”`. Se desactiva con `#set smartquote(enabled: false)` para que el texto sea ASCII donde se pueda.
- **Fuentes:** en esta Mac no hay Carlito ni Calibri, así que los dos motores usaron Arial. Sin fuentes del sistema, Typst usa sus fuentes empaquetadas (Libertinus Serif). Para que la salida sea igual en macOS, Linux y CI, hay que empaquetar Carlito (licencia OFL) y pasarla con `font_paths` e `ignore_system_fonts=True`.

## Decisión

**Se usa Typst.** Cumple el criterio del plan: el texto extraído sale limpio, en orden, sin ligaduras y sin cortes raros. Además:

- Permite instalar en una línea (`uvx honest-cv`).
- Conserva las viñetas en el texto.
- Es unas 30 veces más rápido, lo que importa porque `fit_pages` renderiza varias veces.

Chrome queda descartado para la v0.1.

## Consecuencias para los días 2–3

- Pasar los datos a la plantilla como JSON con `sys_inputs`, nunca interpolados en el código Typst. Así se evita escapar el markup (`@`, `#`, `*`, `_`, `$`) y no hay inyección.
- Empaquetar Carlito Regular y Bold en `src/honest_cv/render/fonts/`, con su licencia OFL.
- Fijar en la plantilla: `ligatures: false`, `hyphenate: false`, `smartquote(enabled: false)`, sin `header` ni `footer`.
- Poner las fechas en línea con el puesto, nunca alineadas a la derecha en otra caja.
- `verify.py` debe comprobar que cada línea de puesto conserva su fecha en la extracción de pdfminer.
