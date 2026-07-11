# Sticker asset attribution

The 8 sticker PNGs in this directory (`1f525.png`, `1f602.png`, `1f4af.png`,
`1f440.png`, `1f680.png`, `2764.png`, `1f631.png`, `1f3af.png`) are from
**Twemoji** by Twitter, Inc. and other contributors.

- Source: https://github.com/twitter/twemoji
- License: [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- Graphics: Copyright 2020 Twitter, Inc and other contributors

Files are named by their Unicode codepoint (e.g. `1f525.png` = 🔥,
U+1F525), matching Twemoji's own `assets/72x72/` naming convention,
fetched from the `master` branch. No modifications were made to the
source images.

Mapping to the frontend's fixed sticker picker
(`frontend/src/components/editor/Inspector.jsx :: STICKER_CHOICES`) and
the codepoint-to-file lookup live in `services/overlay_renderer.py ::
STICKER_FILES`.
