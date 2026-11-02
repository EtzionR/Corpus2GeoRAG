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
TOGGLE_KEY = "georgory_toggle"
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
    .st-key-{PIP_KEY} [data-testid="stElementContainer"]:not(:has(iframe)) {{ display: none; }}
    div[data-testid="stMainBlockContainer"] div[data-testid="stColumn"]:last-child .st-key-{PIP_KEY} iframe {{
        height: clamp(210px, calc(100vh - 370px), {PIP_HEIGHT}px) !important;
        min-height: 0 !important;
        max-height: {PIP_HEIGHT}px !important;
        border-radius: 12px !important;
    }}
</style>"""

_HIDDEN_CSS = f"<style>.st-key-{PIP_KEY} {{ visibility: hidden; }}</style>"

# His face for the chat-box button, drawn from the avatar's own hat, lenses and mustache (a CSS mask, so
# it takes the button's color). The second one has a slash through it, for when he is hidden.
_ICON_ON = "data:image/svg+xml,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20viewBox%3D%27104%2096%20192%20192%27%3E%3Cpath%20d%3D%27M%20148%20180%20C%20146%20140%20156%20112%20178%20104%20C%20190%20111%20210%20111%20222%20104%20C%20244%20112%20254%20140%20252%20180%20Z%27%2F%3E%3Cpath%20d%3D%27M%20108%20180%20C%20146%20166%20254%20166%20292%20180%20C%20300%20184%20294%20192%20284%20191%20C%20256%20186%20232%20188%20200%20195%20C%20168%20188%20144%20186%20116%20191%20C%20106%20192%20100%20184%20108%20180%20Z%27%2F%3E%3Cg%20transform%3D%27translate%280%209%29%27%3E%3Cpath%20d%3D%27M%20155%20203%20Q%20175%20199%20195%20202%20Q%20197%20220%20189%20228%20Q%20177%20231%20165%20228%20Q%20155%20222%20155%20203%20Z%27%2F%3E%3Cpath%20d%3D%27M%20245%20203%20Q%20225%20199%20205%20202%20Q%20203%20220%20211%20228%20Q%20223%20231%20235%20228%20Q%20245%20222%20245%20203%20Z%27%2F%3E%3Cpath%20d%3D%27M190%20205%20Q200%20199%20210%20205%27%20fill%3D%27none%27%20stroke%3D%27%23000%27%20stroke-width%3D%276%27%2F%3E%3Cpath%20d%3D%27M%20200%20248%20C%20194%20245%20184%20246%20178%20251%20C%20173%20255%20170%20261%20167%20267%20C%20172%20265%20177%20262%20182%20260%20C%20189%20258%20195%20258%20200%20259.5%20C%20205%20258%20211%20258%20218%20260%20C%20223%20262%20228%20265%20233%20267%20C%20230%20261%20227%20255%20222%20251%20C%20216%20246%20206%20245%20200%20248%20Z%27%2F%3E%3C%2Fg%3E%3C%2Fsvg%3E"
_ICON_OFF = "data:image/svg+xml,%3Csvg%20xmlns%3D%27http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%27%20viewBox%3D%27104%2096%20192%20192%27%3E%3Cpath%20d%3D%27M%20148%20180%20C%20146%20140%20156%20112%20178%20104%20C%20190%20111%20210%20111%20222%20104%20C%20244%20112%20254%20140%20252%20180%20Z%27%2F%3E%3Cpath%20d%3D%27M%20108%20180%20C%20146%20166%20254%20166%20292%20180%20C%20300%20184%20294%20192%20284%20191%20C%20256%20186%20232%20188%20200%20195%20C%20168%20188%20144%20186%20116%20191%20C%20106%20192%20100%20184%20108%20180%20Z%27%2F%3E%3Cg%20transform%3D%27translate%280%209%29%27%3E%3Cpath%20d%3D%27M%20155%20203%20Q%20175%20199%20195%20202%20Q%20197%20220%20189%20228%20Q%20177%20231%20165%20228%20Q%20155%20222%20155%20203%20Z%27%2F%3E%3Cpath%20d%3D%27M%20245%20203%20Q%20225%20199%20205%20202%20Q%20203%20220%20211%20228%20Q%20223%20231%20235%20228%20Q%20245%20222%20245%20203%20Z%27%2F%3E%3Cpath%20d%3D%27M190%20205%20Q200%20199%20210%20205%27%20fill%3D%27none%27%20stroke%3D%27%23000%27%20stroke-width%3D%276%27%2F%3E%3Cpath%20d%3D%27M%20200%20248%20C%20194%20245%20184%20246%20178%20251%20C%20173%20255%20170%20261%20167%20267%20C%20172%20265%20177%20262%20182%20260%20C%20189%20258%20195%20258%20200%20259.5%20C%20205%20258%20211%20258%20218%20260%20C%20223%20262%20228%20265%20233%20267%20C%20230%20261%20227%20255%20222%20251%20C%20216%20246%20206%20245%20200%20248%20Z%27%2F%3E%3C%2Fg%3E%3Cpath%20d%3D%27M112%20280%20L288%20104%27%20stroke%3D%27%23000%27%20stroke-width%3D%2714%27%20stroke-linecap%3D%27round%27%2F%3E%3C%2Fsvg%3E"

# Takes the arrow's old spot; the arrow moves left by one button and a gap. Same size, corners and
# resting color as the arrow, with the theme's cyan while he is showing.
_BUTTON_CSS = """<style>
    div[data-testid="stColumn"] .st-key-TOGGLE {
        position: absolute !important;
        top: auto !important;
        left: auto !important;
        right: 18px !important;
        bottom: 14px !important;
        width: 32px !important;
        height: 32px !important;
        z-index: 51;
    }
    .st-key-TOGGLE > div, .st-key-TOGGLE span { width: 32px !important; }
    div[data-testid="stColumn"]:has(.st-key-TOGGLE) [data-testid="stChatInputSubmitButton"] { margin-right: 40px; }
    .st-key-TOGGLE button {
        width: 32px !important;
        height: 32px !important;
        min-height: 0 !important;
        padding: 0 !important;
        display: flex !important;
        align-items: center;
        justify-content: center;
        border-radius: 8px !important;
        background: BG !important;
        border: 1px solid BORDER !important;
        box-shadow: GLOW !important;
        color: COLOR !important;
        transition: border-color .15s, box-shadow .15s, color .15s;
    }
    .st-key-TOGGLE button:hover {
        color: #00e5ff !important;
        border-color: #00e5ff !important;
        box-shadow: 0 0 10px rgba(0, 229, 255, .40) !important;
    }
    .st-key-TOGGLE button p { display: none; }
    .st-key-TOGGLE button::before {
        flex: none;
        content: "";
        width: 24px;
        height: 24px;
        background: currentColor;
        -webkit-mask: url("ICON") center / contain no-repeat;
        mask: url("ICON") center / contain no-repeat;
    }
</style>"""

# A click reruns the script, which would interrupt a running question and ask the agent again, so both
# switches rest while the agent answers. Gated on the script state: a failed query can't leave them stuck.
_BUSY_CSS = """<style>
    [data-testid="stApp"][data-test-script-state="running"] .st-key-TOGGLE button,
    [data-testid="stApp"][data-test-script-state="running"] .st-key-georgory_on {
        opacity: .45;
        pointer-events: none;
    }
</style>"""

# Streamlit can't read text that hasn't been sent, so the browser decides. A typed question goes through
# the real send arrow. If he is hidden the click carries on and shows him; if he is showing it stops there.
_ASK_SCRIPT = """<script>
(function () {
    if (window._georgoryAskInstalled) return;
    window._georgoryAskInstalled = true;
    document.addEventListener("click", function (e) {
        if (!e.target.closest || !e.target.closest(".st-key-TOGGLE button")) return;
        var box = document.querySelector('[data-testid="stChatInput"] textarea');
        var send = document.querySelector('[data-testid="stChatInputSubmitButton"]');
        if (!box || !box.value.trim() || !send || send.disabled) return;
        var pip = document.querySelector(".st-key-PIP");
        if (pip && getComputedStyle(pip).visibility !== "hidden") {
            e.stopPropagation();
            e.preventDefault();
        }
        send.click();
    }, true);
})();
</script>""".replace("TOGGLE", TOGGLE_KEY).replace("PIP", PIP_KEY)

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


def _speak_latest(messages: Sequence[Mapping[str, Any]], busy: bool, hidden: bool = False) -> None:
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
        hidden=hidden,
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


def _flip() -> None:
    st.session_state.georgory_on = not _setting("georgory_on")


def chat_button() -> None:
    """The avatar button inside the chat box. Empty box: show or hide him. Typed question: send it to him.

    Only the button lives here. A container in this column would be stretched by the app's layout rules
    and squeeze the chat, so render() supplies its styling and script from his own panel.
    """
    try:
        st.button("Agent Geo-rgory", key=TOGGLE_KEY, on_click=_flip,
                  help="Show or hide Agent Geo-rgory. With a question typed, it sends the question and he answers.")
    except Exception as err:
        print(f"[Agent Geo-rgory] Skipped the chat button: {err}")


def _button_css(showing: bool, busy: bool) -> str:
    css = (
        _BUTTON_CSS.replace("TOGGLE", TOGGLE_KEY)
        .replace("BG", "rgba(0, 229, 255, .10)" if showing else "rgba(140, 165, 197, .15)")
        .replace("BORDER", "rgba(0, 229, 255, .45)" if showing else "transparent")
        .replace("GLOW", "0 0 8px rgba(0, 229, 255, .25)" if showing else "none")
        .replace("COLOR", "#00e5ff" if showing else "rgba(216, 226, 236, .4)")
        .replace("ICON", _ICON_ON if showing else _ICON_OFF)
    )
    return css + _BUSY_CSS.replace("TOGGLE", TOGGLE_KEY) if busy else css


def render(messages: Sequence[Mapping[str, Any]], *, busy: bool = False) -> None:
    """Render the avatar for the latest answer (or his introduction). Call it on every run.

    He stays mounted while hidden: the map keeps its position and doesn't reload, and the browser's
    audio unlock survives, so he can answer as soon as he reappears. Any failure in here is logged
    and costs only the avatar.
    """
    with st.container(key=PIP_KEY):
        try:
            showing = _setting("georgory_on")
            st.markdown((_CSS if showing else _CSS + _HIDDEN_CSS) + _button_css(showing, busy), unsafe_allow_html=True)
            st.html(_ASK_SCRIPT, unsafe_allow_javascript=True)
            _speak_latest(messages, busy, hidden=not showing)
        except Exception as err:
            print(f"[Agent Geo-rgory] Skipped this run: {err}")
