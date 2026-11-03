"""
Tests for Agent Geo-rgory. Run from the repo root:
    pytest avatar-georgory/test_georgory.py -v

The tests that need the hooks in ui/app.py are skipped until app_hooks.patch is applied.
"""

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
UI_DIR = HERE.parent / "ui"
sys.path[:0] = [str(HERE), str(UI_DIR)]

from geo_agent import AgentResponse, MapLayer, query_geo_agent
from agent_avatar.georgory import BESIDE_MAP, DEFAULTS, ON_MAP, avatar_payload, build_briefing, speakable

needs_hooks = pytest.mark.skipif(
    "from agent_avatar import georgory" not in (UI_DIR / "app.py").read_text(encoding="utf-8"),
    reason="app_hooks.patch is not applied to ui/app.py",
)


def _place(number, label, role="primary", kind="city", lon=37.0, lat=48.0):
    return {"number": number, "label": label, "role": role, "kind": kind,
            "geometry": {"type": "point", "coordinates": [lon, lat]}}


# Numbers may skip (agent contract), and context pins are dropped unless the answer cites them.
LIVE = {
    "answer": "The strongest few are Avdiivka [1], Mariupol [2, S3], and Bakhmut [5]. They lie in Donetsk Oblast [L1].",
    "geo_locations": [
        _place(1, "Avdiivka", lon=37.75, lat=48.14),
        _place(2, "Mariupol"),
        _place(5, "Bakhmut"),
        _place(7, "Toretsk", role="context"),
    ],
}


def _live_response(**kw):
    return AgentResponse(answer=LIVE["answer"], raw_response=LIVE, **kw)


class TestPayload:
    def test_keeps_primary_places_with_lat_lon(self):
        payload = avatar_payload(_live_response())
        assert [p["n"] for p in payload["places"]] == [1, 2, 5]
        assert payload["places"][0] == {"n": 1, "name": "Avdiivka", "lat": 48.14, "lon": 37.75, "kind": "city"}
        assert payload["total"] == 4

    def test_keeps_a_context_place_the_answer_cites(self):
        resp = AgentResponse(answer="See Toretsk [7].", raw_response=LIVE)
        assert 7 in [p["n"] for p in avatar_payload(resp)["places"]]

    def test_each_answer_gets_its_own_id(self):
        assert avatar_payload(_live_response())["id"] != avatar_payload(_live_response())["id"]

    @pytest.mark.parametrize("raw", [
        {"geo_locations": [{"number": "not-a-number", "geometry": {"coordinates": [1, 2]}}]},
        {"geo_locations": [{"number": 1, "geometry": {"coordinates": ["x", "y"]}}]},
        {"geo_locations": [{"number": 1, "geometry": None}]},
        {"geo_locations": ["not-a-dict"]},
        {"geo_locations": 5},
        "not-a-dict",
    ])
    def test_never_raises_on_a_malformed_answer(self, raw):
        """It runs in the answer path: a surprising shape must not cost the operator the answer."""
        payload = avatar_payload(AgentResponse(answer="Text.", raw_response=raw))
        assert isinstance(payload["places"], list) and payload["id"]


class TestBriefing:
    def _briefing(self, **kw):
        resp = _live_response()
        payload = avatar_payload(resp)
        return build_briefing(resp.answer, payload["places"], total=payload["total"], **kw)

    def test_points_at_each_cited_pin_and_strips_marks(self):
        b = self._briefing()
        assert "[point:1] Avdiivka, [point:2] Mariupol, and [point:5] Bakhmut." in b["text"]
        for mark in ("[S3]", "[L1]", "[1]", "[5]"):
            assert mark not in b["text"]
        assert [s["n"] for s in b["tour"]] == [1, 2, 5]
        assert b["target"]["name"] == "Avdiivka"

    def test_mock_answer_matches_place_names_and_loses_its_markdown(self):
        resp = query_geo_agent(text_prompt="Show key logistics nodes", force_mock=True)
        payload = avatar_payload(resp)
        b = build_briefing(resp.answer, payload["places"], total=payload["total"])
        assert "###" not in b["text"] and "**" not in b["text"] and "Inquiry" not in b["text"]
        assert b["tour"], "the mock's sector pins should become tour stops"

    def test_brief_mode_truncates_and_full_mode_does_not(self):
        answer = " ".join(f"Sentence number {i} carries a little more detail about the front." for i in range(30))
        brief = build_briefing(answer, [], mode="brief")
        full = build_briefing(answer, [], mode="full")
        assert "The rest of the report is in the console." in brief["text"]
        assert "Sentence number 29" in full["text"] and "console" not in full["text"]

    def test_many_places_are_counted_truthfully(self):
        """When the map shows only the discussed places, he must not claim all of them are marked."""
        b = build_briefing("Kyiv is the capital.", [], total=12, not_shown=30)
        assert "I have marked 12 places on your map." in b["text"]
        assert "30 more are in the file." in b["text"]
        assert "all" not in b["text"].lower().split()

    def test_ungrounded_answer_is_flagged_in_character(self):
        b = build_briefing("No data from the graph — answer from the LLM only. Kyiv is the capital.", [], grounded=False)
        assert b["text"].startswith("[peek] Headquarters has no file on this")
        assert "LLM only" not in b["text"]

    def test_speakable_cleans_markdown_coordinates_and_emoji(self):
        text = speakable("### 🎯 Title\n- **Target:** `49.9935° N, 36.2304° E`\n💡 **Interactive Tip:** click")
        assert text == "Target: 49.99 north, 36.23 east."


class TestRender:
    def test_each_new_question_changes_the_arguments_even_after_a_failed_query(self, monkeypatch):
        """Streamlit skips the render when arguments are unchanged, which used to hide DECRYPTING."""
        from agent_avatar import georgory
        calls = []
        monkeypatch.setattr(georgory, "agent_avatar", lambda text, **kw: calls.append(kw))
        history = [{"role": "user", "content": "first question"}]
        georgory._speak_latest(history, busy=True)
        history.append({"role": "user", "content": "second question"})
        georgory._speak_latest(history, busy=True)
        assert calls[0]["nonce"] != calls[1]["nonce"]

    def test_he_introduces_himself_before_the_first_answer(self, monkeypatch):
        from agent_avatar import georgory
        spoken = []
        monkeypatch.setattr(georgory, "agent_avatar", lambda text, **kw: spoken.append((text, kw["speak_id"])))
        georgory._speak_latest([{"role": "assistant", "content": "Welcome."}], busy=False)
        assert "I am Agent Geo-rgory" in spoken[0][0] and spoken[0][1] == "georgory-intro"


    def test_hidden_he_stays_mounted_but_silent(self, monkeypatch):
        """Unmounting would lose the browser's audio unlock, and he couldn't answer when he reappears."""
        from agent_avatar import georgory
        calls = []
        monkeypatch.setattr(georgory, "agent_avatar", lambda text, **kw: calls.append(kw))
        monkeypatch.setattr(georgory.st, "session_state", {"georgory_on": False})
        monkeypatch.setattr(georgory.st, "markdown", lambda *a, **k: None)
        monkeypatch.setattr(georgory.st, "html", lambda *a, **k: None)
        monkeypatch.setattr(georgory.st, "container", lambda **k: __import__("contextlib").nullcontext())
        georgory.render([], busy=False)
        assert calls[0]["hidden"] is True

    def test_he_starts_hidden_and_beside_the_map(self):
        assert DEFAULTS["georgory_on"] is False and DEFAULTS["georgory_place"] == BESIDE_MAP

    @pytest.mark.parametrize("showing, place, narrowed, hidden", [
        (True, BESIDE_MAP, True, False),
        (True, ON_MAP, False, False),
        (False, BESIDE_MAP, False, True),
        (False, ON_MAP, False, True),
    ])
    def test_the_map_narrows_only_while_he_stands_beside_it(self, monkeypatch, showing, place, narrowed, hidden):
        from agent_avatar import georgory
        monkeypatch.setattr(georgory.st, "session_state", {"georgory_place": place})
        css = georgory._placement_css(showing)
        assert ("margin-left" in css) is narrowed
        assert ("visibility: hidden" in css) is hidden

    def test_hiding_him_keeps_settings_whose_widgets_are_not_drawn(self, monkeypatch):
        from agent_avatar import georgory
        state = type("S", (dict,), {"__getattr__": dict.__getitem__})(georgory_mode="Full answer")
        monkeypatch.setattr(georgory.st, "session_state", state)
        for name in ("subheader", "toggle", "radio", "markdown"):
            monkeypatch.setattr(georgory.st, name, lambda *a, **k: None)
        georgory.sidebar()
        assert state["georgory_mode"] == "Full answer" and state["georgory_on"] is False

    def test_every_setting_rests_during_an_answer(self):
        """A rerun during an answer would ask the agent twice."""
        from agent_avatar.georgory import _BUSY_CSS
        for name in DEFAULTS:
            assert f".st-key-{name}" in _BUSY_CSS

    def test_the_chat_button_flips_him(self, monkeypatch):
        from agent_avatar import georgory
        state = {"georgory_on": True}
        monkeypatch.setattr(georgory.st, "session_state", type("S", (dict,), {"__setattr__": dict.__setitem__})(state))
        georgory._flip()
        assert georgory.st.session_state["georgory_on"] is False

    def test_a_typed_question_goes_through_the_real_send_arrow(self):
        from agent_avatar.georgory import _ASK_SCRIPT
        assert "stChatInputSubmitButton" in _ASK_SCRIPT and "send.click()" in _ASK_SCRIPT
        assert ".st-key-georgory_toggle button" in _ASK_SCRIPT and ".st-key-georgory_pip" in _ASK_SCRIPT


class TestAppIntegration:
    @needs_hooks
    def test_assistant_message_carries_the_payload(self):
        from app import _build_assistant_message
        assert [p["n"] for p in _build_assistant_message(_live_response())["avatar"]["places"]] == [1, 2, 5]

    @needs_hooks
    def test_assistant_message_works_without_the_avatar(self, monkeypatch):
        import app
        monkeypatch.setattr(app, "georgory", None)
        msg = app._build_assistant_message(_live_response())
        assert msg["avatar"] is None and msg["content"] == LIVE["answer"]

    @needs_hooks
    def test_app_loads_when_the_avatar_package_is_missing(self):
        code = (
            "import sys; sys.modules['agent_avatar'] = None\n"
            "import app\n"
            "assert app.georgory is None\n"
            "print('APP_OK')\n"
        )
        run = subprocess.run([sys.executable, "-c", code], cwd=UI_DIR, capture_output=True, text=True, timeout=300)
        assert "APP_OK" in run.stdout, run.stderr[-2000:]

    @needs_hooks
    def test_every_hook_in_app_is_guarded_and_the_map_call_is_untouched(self):
        code = (UI_DIR / "app.py").read_text(encoding="utf-8")
        assert "    from agent_avatar import georgory\nexcept Exception" in code.replace("\r\n", "\n")
        for hook in ("georgory.sidebar()", "georgory.render(", "georgory.chat_button()", "georgory.avatar_payload(resp) if georgory else None"):
            assert code.count(hook) == 1, hook
        assert code.count("if georgory:") == 3
        assert code.find("georgory.chat_button()") < code.find("st.chat_input(")
        assert code.find("georgory.render(") < code.find("map_data = st_folium(")
        assert 'returned_objects=["last_clicked", "last_active_drawing", "all_drawings"]' in code

    def test_iframe_size_rule_outranks_the_apps_map_column_rule(self):
        from agent_avatar.georgory import _BESIDE_CSS, _CSS
        code = (UI_DIR / "app.py").read_text(encoding="utf-8")
        assert 'div[data-testid="stMainBlockContainer"] div[data-testid="stColumn"]:last-child iframe' in code
        for css in (_CSS, _BESIDE_CSS):
            assert 'div[data-testid="stMainBlockContainer"] div[data-testid="stColumn"]:last-child .st-key-georgory_pip iframe' in css

    def test_frontend_never_injects_text_as_html_and_takes_no_outside_commands(self):
        html = (HERE / "agent_avatar" / "frontend" / "index.html").read_text(encoding="utf-8")
        assert "innerHTML" not in html and "eval(" not in html
        assert "agent:say" not in html

    def test_a_failed_query_cannot_leave_him_stuck_on_decrypting(self):
        html = (HERE / "agent_avatar" / "frontend" / "index.html").read_text(encoding="utf-8")
        assert "data-test-script-state" in html and "BUSY_LIMIT_MS" in html and "watchBusy();" in html
