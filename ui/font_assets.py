"""
Offline-first typography assets for GeoAI Defense C2.

Embeds locally bundled SIL OFL 1.1 `.woff2` font files as cached base64
`@font-face` rules so every UI layer—the main Streamlit document, Folium map
iframe, adjustable-columns resizer iframe, and interactive subgraph modal—renders
with `Chakra Petch`, `Plus Jakarta Sans`, and `JetBrains Mono` with zero external
network dependencies and zero system-font fallbacks.
"""

from __future__ import annotations

import base64
import functools
from pathlib import Path
from typing import Optional, Tuple

FONTS_DIR: Path = Path(__file__).resolve().parent / "fonts"
FONT_STYLE_ELEMENT_ID: str = "geoai-embedded-fonts"

# 3-Tier Semantic Font Stacks
FONT_DISPLAY: str = "'Chakra Petch', 'Plus Jakarta Sans', 'Segoe UI', sans-serif"
FONT_BODY: str = "'Plus Jakarta Sans', 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif"
FONT_MONO: str = "'JetBrains Mono', Consolas, monospace"

# Uniform manifest: (font_family, weight_spec, filename, unicode_range)
FONT_SPECS: Tuple[Tuple[str, str, str, str], ...] = (
    (
        "Chakra Petch",
        "600",
        "chakra-petch-600-latin-ext.woff2",
        "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C4, U+2113, U+2C60-2C7F, U+A720-A7FF",
    ),
    (
        "Chakra Petch",
        "600",
        "chakra-petch-600-latin.woff2",
        "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD",
    ),
    (
        "Chakra Petch",
        "700",
        "chakra-petch-700-latin-ext.woff2",
        "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C4, U+2113, U+2C60-2C7F, U+A720-A7FF",
    ),
    (
        "Chakra Petch",
        "700",
        "chakra-petch-700-latin.woff2",
        "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD",
    ),
    (
        "JetBrains Mono",
        "300 700",
        "jetbrains-mono-300-700-cyrillic-ext.woff2",
        "U+0460-052F, U+1C80-1C8A, U+20B4, U+2DE0-2DFF, U+A640-A69F, U+FE2E-FE2F",
    ),
    (
        "JetBrains Mono",
        "300 700",
        "jetbrains-mono-300-700-cyrillic.woff2",
        "U+0301, U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116",
    ),
    (
        "JetBrains Mono",
        "300 700",
        "jetbrains-mono-300-700-latin-ext.woff2",
        "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C4, U+2113, U+2C60-2C7F, U+A720-A7FF",
    ),
    (
        "JetBrains Mono",
        "300 700",
        "jetbrains-mono-300-700-latin.woff2",
        "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD",
    ),
    (
        "Plus Jakarta Sans",
        "300 800",
        "plus-jakarta-sans-300-800-cyrillic-ext.woff2",
        "U+0460-052F, U+1C80-1C8A, U+20B4, U+2DE0-2DFF, U+A640-A69F, U+FE2E-FE2F",
    ),
    (
        "Plus Jakarta Sans",
        "300 800",
        "plus-jakarta-sans-300-800-latin-ext.woff2",
        "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C4, U+2113, U+2C60-2C7F, U+A720-A7FF",
    ),
    (
        "Plus Jakarta Sans",
        "300 800",
        "plus-jakarta-sans-300-800-latin.woff2",
        "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD",
    ),
)


@functools.lru_cache(maxsize=4)
def get_embedded_font_face_css(fonts_dir: Optional[Path] = None) -> str:
    """Build and cache inline `@font-face` CSS rules using base64-encoded local WOFF2 files."""
    resolved_dir = Path(fonts_dir) if fonts_dir is not None else FONTS_DIR
    rules = []
    for family, weight, filename, unicode_range in FONT_SPECS:
        font_path = resolved_dir / filename
        if not font_path.is_file():
            continue
        encoded = base64.b64encode(font_path.read_bytes()).decode("ascii")
        rules.append(
            f"@font-face {{\n"
            f"  font-family: '{family}';\n"
            f"  font-style: normal;\n"
            f"  font-weight: {weight};\n"
            f"  font-display: swap;\n"
            f"  src: url(data:font/woff2;base64,{encoded}) format('woff2');\n"
            f"  unicode-range: {unicode_range};\n"
            f"}}"
        )
    return "\n".join(rules)


@functools.lru_cache(maxsize=1)
def get_font_style_block() -> str:
    """Return a cached `<style id='geoai-embedded-fonts'>` block for Streamlit HTML injection."""
    css = get_embedded_font_face_css()
    if not css:
        return ""
    return f"<style id='{FONT_STYLE_ELEMENT_ID}'>\n{css}\n</style>"


@functools.lru_cache(maxsize=1)
def build_iframe_font_sync_js() -> str:
    """
    Return a lightweight, fail-safe JS helper that clones the parent document's
    embedded `@font-face` style tag into child iframes (map & resizer) without
    duplicating base64 payloads inside Jinja templates.
    """
    return f"""
window.geoaiSyncEmbeddedFonts = function(targetDoc) {{
    try {{
        if (!targetDoc || (!targetDoc.head && !targetDoc.body)) return;
        var existing = targetDoc.getElementById('{FONT_STYLE_ELEMENT_ID}');
        if (existing && existing.textContent) return;
        var src = document.getElementById('{FONT_STYLE_ELEMENT_ID}');
        if (!src && window.parent && window.parent !== window && window.parent.document) {{
            src = window.parent.document.getElementById('{FONT_STYLE_ELEMENT_ID}');
        }}
        if (!src || !src.textContent) return;
        if (!existing) {{
            existing = targetDoc.createElement('style');
            existing.id = '{FONT_STYLE_ELEMENT_ID}';
            (targetDoc.head || targetDoc.body).appendChild(existing);
        }}
        existing.textContent = src.textContent;
    }} catch (e) {{}}
}};
""".strip()
