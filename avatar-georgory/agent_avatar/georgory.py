"""Agent Geo-rgory: the GeoRAG UI's talking tour guide.

Turns an agent answer into a spoken briefing for the avatar:

- markdown, emojis and citation marks are cleaned out of the speech;
- every pin the answer names with a mark (``Bakhmut [1]``) becomes a map stop: the
  agent points and the map flies to that pin while he says the name;
- long answers are cut to a short briefing (``"Brief"`` narration); the full text stays
  in the chat.

``app.py`` calls three things, each guarded so the avatar can never break the app:
``avatar_payload()`` (stored on each assistant message), ``sidebar()`` and ``render()``.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Mapping, Sequence

import streamlit as st

from . import agent_avatar

CALLSIGN = "АГЕНТ ГЕО-РГОРИЙ · GEO-RGORY"

# Spoken once per browser session, before the first answer.
INTRO = (
    "[earpiece] Greetings, comrade. I am Agent Geo-rgory. "
    "[peek] Yes. Geo-rgory. I know every road, river and battlefield on this map. "
    "[point] Ask me about a place, a battle or a person, and I will show you where it happened. "
    "[dossier] Click a point or draw a box on the map, and I will open the file on it. "
    "[nod] I am listening."
)

# Matches the UI's cyan "Defense C2" theme (ui/.streamlit/config.toml).
THEME = {
    "--hud": "#00e5ff",
    "--hud-dim": "rgba(0, 229, 255, .30)",
    "--hud-glow": "rgba(0, 229, 255, .40)",
    "--rim": "rgba(0, 229, 255, .38)",
    "--bg-1": "#070b10",
    "--bg-2": "#0f1a24",
}

# Sidebar settings. CUSTOMIZE: set "georgory_on" to False to ship him switched off by default.
DEFAULTS = {
    "georgory_on": True,          # show the avatar over the map
    "georgory_mode": "Brief",     # "Brief" speaks ~3 sentences; "Full answer" speaks everything
    "georgory_tour": True,        # fly the map to each pin he names
    "georgory_pitch": 0.62,
    "georgory_rate": 0.88,
    "georgory_accent": False,     # read English with a Russian voice
}

PIP_KEY = "georgory_pip"
PIP_WIDTH, PIP_HEIGHT = 236, 300
MAX_TOUR = 10          # the agent contract gives at most 10 primary places per answer
BRIEF_CHARS = 520      # brief mode speaks about this much of the answer

# Pinned over the map's left edge, out of the layout flow, so the map keeps its exact position and
# size (AGENTS.md Rule 3.1): without `display: contents`, Streamlit's zero-height wrapper still
# takes a 16px flex gap. `bottom` clears the map's target HUD and scale bar; the height shrinks in short
# windows to stay clear of the draw tools above him. The iframe rule must outrank app.py's
# "every iframe in the map column fills the window" rule, hence the long selector.
_CSS = f"""<style>
    div[data-testid="stColumn"]:has(.st-key-{PIP_KEY}) {{ position: relative; }}
    [data-testid="stLayoutWrapper"]:has(> .st-key-{PIP_KEY}) {{ display: contents; }}
    .st-key-{PIP_KEY} {{
        position: absolute !important;
        left: 12px;
        bottom: 126px;
        width: {PIP_WIDTH}px !important;
        z-index: 900;
        gap: 0 !important;
        filter: drop-shadow(0 10px 24px rgba(0, 0, 0, 0.6));
    }}
    .st-key-{PIP_KEY} [data-testid="stElementContainer"]:has(style) {{ display: none; }}
    div[data-testid="stMainBlockContainer"] div[data-testid="stColumn"]:last-child .st-key-{PIP_KEY} iframe {{
        height: clamp(210px, calc(100vh - 370px), {PIP_HEIGHT}px) !important;
        min-height: 0 !important;
        max-height: {PIP_HEIGHT}px !important;
        border-radius: 12px !important;
    }}
</style>"""

_CITE = re.compile(r"\s*\[((?:\s*(?:\d+|[SL]\d+)\s*,?)+)\]")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍←-⇿★☆]")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


# --------------------------------------------------------------------------- places
def _short_name(name: str) -> str:
    """'Sector Alpha (Kyiv)' -> 'Kyiv'; '3. [CITY] Kyiv (?)' -> 'Kyiv'; 'Target: 49.9, 36.2' -> 'Target'."""
    name = re.sub(r"^\d+\.\s*", "", name or "")
    name = re.sub(r"\[[A-Z_]+\]\s*", "", name).replace("(?)", "").strip()
    paren = re.search(r"\(([^)]*)\)", name)
    if paren and re.search(r"[A-Za-z]", paren.group(1)) and not re.search(r"\d", paren.group(1)):
        return paren.group(1).strip()
    return re.split(r"[:(]", name)[0].strip()


def _places_from_response(resp: Any) -> tuple[List[Dict[str, Any]], int]:
    """Live answers: ``raw_response["geo_locations"]`` (numbered). Mock answers: marker layers in order."""
    raw = getattr(resp, "raw_response", None) or {}
    locs = raw.get("geo_locations") or []
    places: List[Dict[str, Any]] = []

    if any(loc.get("number") is not None for loc in locs):
        answer = getattr(resp, "answer", "") or ""
        cited = {int(t) for m in _CITE.finditer(answer) for t in m.group(1).split(",") if t.strip().isdigit()}
        for loc in locs:
            n = loc.get("number")
            coords = (loc.get("geometry") or {}).get("coordinates") or []
            if n is None or len(coords) < 2:
                continue
            # primary places, plus any context place the answer cites by number
            if loc.get("role", "primary") != "primary" and int(n) not in cited:
                continue
            places.append({
                "n": int(n),
                "name": loc.get("label") or loc.get("id") or "",
                "lat": float(coords[1]),
                "lon": float(coords[0]),
                "kind": loc.get("kind") or "",
            })
        return places, len(locs)

    for layer in getattr(resp, "layers", None) or []:
        data = getattr(layer, "data", None)
        if getattr(layer, "layer_type", "") != "marker" or not isinstance(data, dict) or "lat" not in data:
            continue
        places.append({
            "n": len(places) + 1,
            "name": _short_name(getattr(layer, "name", "")),
            "lat": float(data["lat"]),
            "lon": float(data["lng"]),
            "kind": data.get("kind") or "",
        })
    return places, len(places)


def avatar_payload(resp: Any) -> Dict[str, Any]:
    """What the avatar needs from an AgentResponse, small enough to keep on each chat message.

    Never raises: this runs in the answer path, and a surprising answer shape must cost the
    avatar his map tour, not the operator the answer.
    """
    try:
        places, total = _places_from_response(resp)
    except Exception as err:
        print(f"[Agent Geo-rgory] Could not read places from the answer: {err}")
        places, total = [], 0
    return {
        "id": uuid.uuid4().hex[:12],     # each answer is spoken exactly once
        "places": places[: MAX_TOUR + 10],
        "total": total,
        "not_shown": int(getattr(resp, "map_not_shown", 0) or 0),
        "status": getattr(resp, "status", "answered"),
        "grounded": bool(getattr(resp, "grounded", True)),
    }


# --------------------------------------------------------------------------- speech text
def speakable(markdown: str) -> str:
    """Markdown answer -> plain sentences for TTS. Citation marks are kept (cues need them)."""
    lines = []
    for line in (markdown or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue                                          # blank lines and headings
        if re.match(r"^[-*•]?\s*\**\s*(Query Intent|Inquiry)\b", s, re.I) or "Interactive Tip" in s:
            continue                                          # echoes of the question / UI tips
        s = re.sub(r"^[-*•]\s+", "", s)                       # bullets
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)        # markdown links
        s = s.replace("*", "").replace("`", "").replace("__", "")
        s = s.strip()
        if s and s[-1] not in ".!?:;…":
            s += "."
        lines.append(s)
    text = " ".join(lines)
    text = _EMOJI.sub("", text)
    text = re.sub(r"No data from the graph\s*[—–-]+\s*answer from the LLM only\.?", "", text, flags=re.I)
    text = text.replace("�", " to ").replace("–", " to ")
    text = re.sub(r"\(\s*[\d,.]+\s*(?:mi|sq mi|ft|lb)\s*\)", "", text)       # imperial conversions
    text = re.sub(r"(\d+\.\d{2})\d+", r"\1", text)                           # 49.9935 -> 49.99
    for sym, word in (("N", "north"), ("S", "south"), ("E", "east"), ("W", "west")):
        text = re.sub(rf"°\s*{sym}\b", f" {word}", text)
    text = text.replace("°", " degrees")
    return re.sub(r"\s+", " ", text).strip()


def _label_start(body: str, name: str, end: int) -> int:
    """Where the place name before a citation mark starts (so the gesture lands on the name)."""
    lo = max(0, end - 160)
    window = body[lo:end].lower()
    for candidate in (name, re.sub(r"^the\s+", "", name or "", flags=re.I)):
        idx = window.rfind((candidate or "").lower()) if candidate else -1
        if idx >= 0:
            return lo + idx
    cut = max(body.rfind(", ", 0, end), body.rfind(". ", 0, end))
    return cut + 2 if cut >= 0 else 0


def _place_cues(body: str, stops: Mapping[int, Mapping[str, Any]]) -> tuple[str, List[int]]:
    """Insert ``[point:n]`` before each place named with a mark, then strip all marks."""
    inserts: Dict[int, str] = {}
    cued: List[int] = []
    marks = list(_CITE.finditer(body))

    def add(pos: int, n: int) -> None:
        inserts[pos] = inserts.get(pos, "") + f"[point:{n}] "
        cued.append(n)

    for m in marks:
        for tok in re.split(r"\s*,\s*", m.group(1).strip()):
            if tok.isdigit() and int(tok) in stops and int(tok) not in cued and len(cued) < MAX_TOUR:
                add(_label_start(body, str(stops[int(tok)].get("name", "")), m.start()), int(tok))
                break
    if not any(t.strip().isdigit() for m in marks for t in m.group(1).split(",")):
        # no numbered marks (mock answers): match place names in the text instead
        for n, stop in stops.items():
            name = str(stop.get("name", ""))
            hit = re.search(rf"\b{re.escape(name)}\b", body, re.I) if len(name) > 2 else None
            if hit and n not in cued and len(cued) < MAX_TOUR:
                add(hit.start(), n)

    drop = bytearray(len(body))
    for m in marks:
        drop[m.start():m.end()] = b"\x01" * (m.end() - m.start())
    out = []
    for i, ch in enumerate(body):
        if i in inserts:
            out.append(inserts[i])
        if not drop[i]:
            out.append(ch)
    if len(body) in inserts:
        out.append(inserts[len(body)])
    text = re.sub(r"\s+([,.;:!?])", r"\1", "".join(out))
    return re.sub(r"\s+", " ", text).strip(), cued


def build_briefing(
    answer: str,
    places: Sequence[Mapping[str, Any]],
    *,
    total: int = 0,
    not_shown: int = 0,
    status: str = "answered",
    grounded: bool = True,
    mode: str = "brief",
) -> Dict[str, Any]:
    """Answer + places -> ``{"text": script with gesture tags, "tour": stops, "target": first stop}``."""
    stops = {int(p["n"]): dict(p) for p in places if p.get("n") is not None}
    sentences = [s for s in _SENTENCE.split(speakable(answer)) if s.strip()]

    kept, truncated = [], False
    for s in sentences:
        if mode == "brief" and kept and len(_CITE.sub("", " ".join(kept + [s]))) > BRIEF_CHARS:
            truncated = True
            break
        kept.append(s)
    body, cued = _place_cues(" ".join(kept), stops)

    if not cued and stops and body:
        # nothing named by mark or name: point at the first pin as the explanation starts
        first = min(stops)
        parts = _SENTENCE.split(body, maxsplit=1)
        body = f"{parts[0]} [point:{first}] {parts[1]}" if len(parts) > 1 else f"[point:{first}] {body}"
        cued = [first]

    if not grounded:
        opening = "[peek] Headquarters has no file on this, comrade. What follows is from my own memory. "
    elif status in ("no_data", "out_of_scope"):
        opening = "[peek] "
    elif status == "llm_failed":
        opening = "[earpiece] The line to headquarters is breaking up. "
    else:
        opening = "" if body.startswith("[point") else "[earpiece] "

    closing = []
    if total >= 10:
        closing.append(f"[dossier] I have marked {total} places on your map.")
    if not_shown > 0:
        closing.append(f"{not_shown} more are in the file.")
    if truncated:
        closing.append("[nod] The rest of the report is in the console.")

    text = " ".join(x for x in [opening + body, *closing] if x.strip())
    tour = [stops[n] for n in cued]
    target = tour[0] if tour else None
    return {
        "text": text,
        "tour": tour,
        "target": {"name": target["name"], "lat": target["lat"], "lon": target["lon"]} if target else None,
    }


# --------------------------------------------------------------------------- Streamlit
def _setting(name: str) -> Any:
    return st.session_state.get(name, DEFAULTS[name])


def sidebar() -> None:
    """The sidebar section. Hidden widgets lose their state, so defaults are restored on every run."""
    for name, value in DEFAULTS.items():
        st.session_state.setdefault(name, value)
    st.subheader("🕵️ Agent Geo-rgory")
    st.toggle("Show Agent Geo-rgory", key="georgory_on",
              help="A talking agent in the map's corner who reads each answer aloud and points at the places on the map.")
    if st.session_state.georgory_on:
        st.radio("Narration", ["Brief", "Full answer"], key="georgory_mode", horizontal=True,
                 help="Brief: the first few sentences and the main places. The full text is always in the chat.")
        st.toggle("Fly the map to each place he names", key="georgory_tour")
        with st.expander("🎙️ Voice"):
            st.slider("Pitch", 0.1, 1.5, step=0.02, key="georgory_pitch")
            st.slider("Rate", 0.5, 1.4, step=0.02, key="georgory_rate")
            st.toggle("Russian voice for English text", key="georgory_accent",
                      help="Uses a ru-RU voice such as Microsoft Pavel or Dmitry. Quality depends on the browser.")
        st.caption("No sound? Click ▶ on the agent once: browsers block speech until you interact with the page.")
    st.markdown("---")


def _speak_latest(messages: Sequence[Mapping[str, Any]], busy: bool) -> None:
    latest = next((m for m in reversed(messages) if m.get("role") == "assistant" and m.get("avatar")), None)
    if latest is None:
        text, tour, target, speak_id, home = INTRO, [], None, "georgory-intro", None
    else:
        payload = latest["avatar"]
        briefing = build_briefing(
            latest.get("content", ""),
            payload.get("places", []),
            total=payload.get("total", 0),
            not_shown=payload.get("not_shown", 0),
            status=payload.get("status", "answered"),
            grounded=payload.get("grounded", True),
            mode="brief" if _setting("georgory_mode") == "Brief" else "full",
        )
        text, tour, target = briefing["text"], briefing["tour"], briefing["target"]
        speak_id, home = payload["id"], latest.get("map_bbox")

    agent_avatar(
        text,
        key="georgory_avatar",        # stable key: new answers reach the same iframe, audio stays unlocked
        speak_id=speak_id,
        gesture="none",              # the briefing places every gesture itself
        target=target,
        tour=tour,
        home_bbox=home,
        tour_map=_setting("georgory_tour"),
        busy=busy,
        nonce=len(messages),         # grows with each question, so every "busy" run reaches the frontend
        facing="right",              # pinned to the map's left edge: points into it
        height=PIP_HEIGHT,
        compact=True,
        callsign=CALLSIGN,
        colors=THEME,
        voice={
            "pitch": _setting("georgory_pitch"),
            "rate": _setting("georgory_rate"),
            "russianAccent": _setting("georgory_accent"),
        },
    )


def render(messages: Sequence[Mapping[str, Any]], *, busy: bool = False) -> None:
    """Render the avatar for the latest answer (or his introduction). Call it on every run.

    The keyed container and its CSS are always emitted, even when he is switched off, so the map
    after them keeps its position in the page and doesn't reload when the toggle changes. Any
    failure in here is logged and costs only the avatar.
    """
    with st.container(key=PIP_KEY):
        try:
            st.markdown(_CSS, unsafe_allow_html=True)
            if _setting("georgory_on"):
                _speak_latest(messages, busy)
        except Exception as err:
            print(f"[Agent Geo-rgory] Skipped this run: {err}")
