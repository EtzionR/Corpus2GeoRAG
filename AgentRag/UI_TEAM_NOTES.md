# Notes for the UI team

Found while running `ui/app.py` against the agent (2026-10-29, updated 2026-10-31). We changed
nothing in `ui/`; each item says what we saw and the change we suggest.

## For now: the launcher runs a copy of the UI with these fixes

`RUN_GEORAG.bat` in the repo root (double-click; it installs everything and asks once for the key)
runs **`AgentRag/ui_mvp/`**, a copy of `ui/` with items 1, 3, 6 and 7 applied, so every team tests,
and the MVP shows, the fixed version. The UI is yours, so **please apply the items to your own
`ui/` and push your final version there**; then tell us and we delete `AgentRag/ui_mvp/`, and the
launcher runs `ui/` by itself. `git diff --no-index ui/app.py AgentRag/ui_mvp/app.py` shows our
changes. Besides those: `pandas<3` in its `requirements.txt`, and `geo_agent.py` also looks for the
agent in its parent folder (one line).

## 1. Blank page (no map, no chat box) on PCs with Smart App Control

Windows Smart App Control blocks a compiled file of **pandas 3.x** ("An Application Control policy
has blocked this file"). Streamlit imports pandas to draw the page, so the app stops before the map
and the chat box appear. pandas 2.3.3 is allowed.

**Fix:** add `pandas<3` to `ui/requirements.txt`.

## 2. The page can't scroll, so the chat box is out of reach on smaller screens

`app.py` ~lines 1029–1068 ("Lock Viewport to Chrome Window") set `height: 100vh; overflow: hidden`
on the page. When the window is shorter than the layout, the chat input sits below the bottom edge
and there is no way to scroll to it. Workaround for now: zoom out (Ctrl + minus) or full screen (F11).

**Suggested fix:** drop `overflow: hidden`, or let the chat column scroll on its own with the input
pinned to its bottom.

## 3. Old answers' pins and polygons stay on the map (most important)

After each answer the app *adds* the answer's layers to the map and never clears the previous ones
(`st.session_state.map_layers.extend(agent_resp.layers)`, `app.py` ~line 2951, and the same in the
three Recon Scan buttons, ~lines 1798, 1843, 2124). After a few questions
"Where is Ukraine?" shows Ukraine plus every earlier answer's outlines. It also confuses follow-ups:
"Tell me about number 4" always means place 4 of the **last** answer, but a pin numbered 4 from an
earlier answer may still be on the map.

**Suggested fix:** replace instead of extend in all four places
(`st.session_state.map_layers = list(agent_resp.layers)`, and `recon_response` / `recon_resp` in the
Recon buttons), with an optional "keep previous answers on the map" toggle if you want the old
behaviour. The answer's own layers include the current map selection, so that stays drawn. Tried on
a local copy (no errors; each answer now shows only its own pins).

## 4. How many places an answer carries

`result["map"]["showing"]` says which places `geo_locations` holds:

- `"all"`: list answers and questions about a map area return every place found.
- `"discussed"`: other answers return the places the answer talks about, plus the place asked about.
  `map.not_shown` says how many more were found; a line such as "12 more places found" is enough.

Outlines (`shape`) come only with the places the question is about, and `map.bbox` zooms to them:
"What happened in Crimea?" outlines Crimea, not Russia and Ukraine too; a list gets pins only; an
area question gets the named area it searched ("drone attacks in Kharkiv": Kharkiv). Draw every
`shape` you receive. Nothing else in the format changed.

## 5. Big lists

Some list answers return many places (Zelenskyy: ~550; "Russia and Ukraine with the same country"
when the model misses the country filter: ~1,700). Drawing them as individual Folium markers is
slow; a `MarkerCluster` keeps the map responsive.

## 6. The welcome note takes a third of the chat area

The greeting is the first chat message and stays at the top of the 465 px chat box after every
question. **Suggested:** show it as a fold-out, open on the first visit and folded to one line once
a question is asked. In the message loop (`app.py` ~line 1904), at the top of the loop body:

```python
            if m_idx == 0 and role == "assistant" and not msg.get("is_live"):
                # The welcome note: open on the first visit, folded to one line once a question is asked
                with st.expander("👋 Welcome: how to use the map and the chat",
                                 expanded=len(st.session_state.messages) == 1):
                    st.markdown(msg["content"])
                continue
```

We tried it on a local copy only (Streamlit's AppTest: no errors, the chat box still there).

## 7. A long answer opens at its end

Streamlit scrolls a fixed-height container that holds chat messages to the bottom by default, so a
long answer shows its last lines and the reader scrolls up to find the start. **Suggested:** turn
that off and scroll to the start of the new answer once, when it arrives:

```python
    chat_container = st.container(height=chat_container_height, autoscroll=False)   # ~line 1902
```

after the message loop, inside `with chat_container:`

```python
        if st.session_state.pop("scroll_to_answer", False):
            # A new answer opens at its start, not its end (the box no longer auto-scrolls to the bottom)
            st.html(
                "<script>setTimeout(() => {"
                "const m = document.querySelectorAll('[data-testid=\"stChatMessage\"]');"
                "if (m.length) m[m.length - 1].scrollIntoView({block: 'start'});}, 300);</script>",
                unsafe_allow_javascript=True)
```

and where the answer is added (~line 2950), `st.session_state.scroll_to_answer = True`. Also tried on
a local copy only (no errors). `st.components.v1.html` would work too but is deprecated.

## 8. Without a key the app gives mock answers, and it's easy to miss

With no OpenRouter key (sidebar box empty, none in the environment) the app answers from its mock
engine; the only sign is "Deterministic Mock Engine" in a details panel. Testers can take mock
answers for the agent's. **Suggested:** a clear line on every mock answer ("Example answer: no
OpenRouter key set"). The launcher always passes the key, so this bites people who start the app
another way.

## What changed on our side that you will see (no format change)

- Some places now come **without a point** when the graph's point was wrong and the graph has no right
  one ("Soviet Union" was a shop in Romania). They appear in the answer text, not on the map.
- Donbas (a street in Skopje in the graph) now comes as a region: the outlines of Donetsk and Luhansk
  oblasts together (a `MultiPolygon` shape) with a point between them.
- Some points are corrected from the graph's own data (Dnipro was on the river near Chernihiv).
- Fewer outlines: only the places the question is about (item 4). Every place still has its pin.
- A topic with no area ("Show me where drone attacks happened", nothing selected) gets a short reply
  asking to name a place or select one on the map, with `status: "no_data"` and no places.
- Russia and the US no longer zoom out to the whole world (their outlines cross the 180th meridian).
- `answer_plain` (shown when citations are switched off) no longer keeps the commas between
  citation marks ("since 2019,,." is now "since 2019.").
- The region grouping follows each place's own address: Kharkiv Oblast and Crimea under Ukraine,
  no longer under Russia.
