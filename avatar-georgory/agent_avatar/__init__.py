"""Talking agent avatar for Streamlit (the persistent component behind Agent Geo-rgory).

``agent_avatar(...)`` loads ``frontend/index.html`` with ``components.declare_component``.
The iframe persists across reruns and receives new text as arguments, so the browser's
one-time "allow audio" click carries over to later answers. App-specific behaviour
(briefing, sidebar, placement) lives in ``georgory.py``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

import streamlit.components.v1 as components

__all__ = ["GESTURES", "agent_avatar", "build_config"]

_FRONTEND_DIR = Path(__file__).parent / "frontend"

_component = components.declare_component("agent_avatar", path=str(_FRONTEND_DIR))

GESTURES = ("auto", "none", "point", "dossier", "earpiece", "peek", "nod")
Gesture = Literal["auto", "none", "point", "dossier", "earpiece", "peek", "nod"]


def build_config(
    text: str = "",
    *,
    gesture: Gesture | Sequence[str] = "auto",
    target: Mapping[str, Any] | None = None,
    facing: Literal["right", "left"] = "right",
    height: int = 520,
    speak_id: str | int | None = None,
    autoplay: bool = True,
    audio: Mapping[str, str] | None = None,
    callsign: str | None = None,
    compact: bool | None = None,
    transparent: bool = False,
    voice: Mapping[str, Any] | None = None,
    anim: Mapping[str, Any] | None = None,
    colors: Mapping[str, str] | None = None,
    emit_events: bool = False,
    tour: Sequence[Mapping[str, Any]] | None = None,
    home_bbox: Sequence[float] | None = None,
    tour_map: bool = True,
    busy: bool = False,
    nonce: Any = None,
) -> dict[str, Any]:
    """Assemble the JSON config the frontend understands.

    text        What the agent says. Inline tags fire gestures at that point in the
                speech: ``"[earpiece] HQ confirms. [point] The target is here."``
    gesture     Used when the text has no tags: "auto" (picks from keywords and
                ``target``), "none", one gesture name, or a list spread over sentences.
    target      ``{"name", "lat", "lon"}``; shown in the HUD and dossier.
    facing      Side of the screen the map is on. The agent points that way.
    speak_id    Unique id per message. A given id is spoken once, so reruns don't
                repeat it. Defaults to a hash of text + gesture + target; pass a
                counter to repeat identical text.
    audio       ``{"b64", "mime"}`` or ``{"url"}`` to play instead of TTS.
    voice       Overrides, e.g. ``{"pitch": 0.5, "rate": 0.8, "name": "Pavel",
                "russianAccent": True}``.
    anim        Overrides, e.g. ``{"speed": 1.3, "idleGestures": False}``.
    colors      CSS variable overrides, e.g. ``{"--coat": "#1f2a3a"}``.
    emit_events Component mode only: return ``{"event": "ended", "id": ...}`` to
                Python when speech starts/ends. Each event triggers a rerun.
    tour        Map stops ``[{"n", "name", "lat", "lon", "kind"}]``. A ``[point:n]`` tag in
                the text flies the st_folium map on the same page to stop n.
    home_bbox   ``[west, south, east, north]`` the map returns to after a tour.
    tour_map    False = the agent never moves the map.
    busy        True while the backend is answering: the agent stops talking and
                listens to his earpiece ("DECRYPTING").
    nonce       Any value that changes between questions. Streamlit only re-renders a component
                when its arguments change, and after a failed query the next question's
                arguments would otherwise be identical, so "DECRYPTING" wouldn't show again.
    """
    if isinstance(gesture, str) and gesture not in GESTURES:
        raise ValueError(f"gesture must be one of {GESTURES} or a list, got {gesture!r}")
    if speak_id is None:
        raw = json.dumps([text, gesture, target], ensure_ascii=False, sort_keys=True, default=str)
        speak_id = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

    cfg: dict[str, Any] = {
        "id": str(speak_id),
        "text": text or "",
        "gesture": list(gesture) if not isinstance(gesture, str) else gesture,
        "target": dict(target) if target else None,
        "facing": facing,
        "height": int(height),
        "autoplay": bool(autoplay),
        "audio": dict(audio) if audio else None,
        "compact": compact,
        "transparent": bool(transparent),
        "emitEvents": bool(emit_events),
        "tour": [dict(s) for s in tour or []],
        "homeBbox": list(home_bbox) if home_bbox else None,
        "tourMap": bool(tour_map),
        "busy": bool(busy),
        "nonce": nonce,
    }
    if callsign is not None:
        cfg["callsign"] = callsign
    if voice:
        cfg["voice"] = dict(voice)
    if anim:
        cfg["anim"] = dict(anim)
    if colors:
        cfg["colors"] = dict(colors)
    return cfg


def agent_avatar(text: str = "", *, key: str = "agent_avatar", **kwargs: Any) -> Any:
    """Render as a persistent bidirectional component (recommended).

    Keep ``key`` stable: with a key, Streamlit identifies the component by key only,
    so new text updates the live iframe instead of replacing it.
    Returns the last event dict when ``emit_events=True``, else ``None``.
    """
    return _component(config=build_config(text, **kwargs), key=key, default=None)
