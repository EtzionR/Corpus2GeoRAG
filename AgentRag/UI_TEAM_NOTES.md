# Notes for the UI team

Found while running `ui/app.py` against the agent (2026-10-29, updated 2026-10-30). We changed
nothing in `ui/`; each item says what we saw and the change we suggest.

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
(`st.session_state.map_layers.extend(agent_resp.layers)`, `app.py` ~line 2951). After a few questions
"Where is Ukraine?" shows Ukraine plus every earlier answer's outlines. It also confuses follow-ups:
"Tell me about number 4" always means place 4 of the **last** answer, but a pin numbered 4 from an
earlier answer may still be on the map.

**Suggested fix:** replace instead of extend for each new answer
(`st.session_state.map_layers = list(agent_resp.layers)`), with an optional "keep previous answers
on the map" toggle if you want the old behaviour.

## 4. How many places an answer carries

`result["map"]["showing"]` says which places `geo_locations` holds:

- `"all"`: list answers and questions about a map area return every place found.
- `"discussed"`: other answers return the places the answer talks about, plus the place asked about.
  `map.not_shown` says how many more were found; a line such as "12 more places found" is enough.

Outlines (`shape`) come with the main places only (up to 10). Nothing else in the format changed.

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

## What changed on our side that you will see (no format change)

- Some places now come **without a point** when the graph's point was wrong and the graph has no right
  one ("Soviet Union" was a shop in Romania). They appear in the answer text, not on the map.
- Donbas (a street in Skopje in the graph) now comes as a region: the outlines of Donetsk and Luhansk
  oblasts together (a `MultiPolygon` shape) with a point between them.
- Some points are corrected from the graph's own data (Dnipro was on the river near Chernihiv).
- The region grouping follows each place's own address: Kharkiv Oblast and Crimea under Ukraine,
  no longer under Russia.
