# Agent Geo-rgory

An optional talking tour guide for the Streamlit UI: a Cold-War field agent (fedora, sunglasses, mustache, earpiece). He starts hidden and appears beside the map when you click his button in the chat box. He introduces himself once per session, reads each answer aloud, and tours the map. He uses the browser's built-in speech, so he needs no API key and no extra packages.

**Everything is in this folder, and `ui/` is untouched until you apply the patch.**

## Insert him

From the repo root:

```bash
git apply avatar-georgory/app_hooks.patch
```

That adds five guarded hooks to `ui/app.py` and nothing else. Then run the tests and start the app as usual:

```bash
pytest avatar-georgory/test_georgory.py -v
cd ui && streamlit run app.py
```

Use Chrome, and click his button in the chat box to show him. Click ▶ on the agent once if the browser blocks sound.

**If `app.py` has moved on and the patch no longer applies,** add the hooks by hand. There are only five, all marked `georgory` in `app_hooks.patch`:

1. The guarded import, above the `get_source_text` helpers
2. `"avatar": georgory.avatar_payload(resp) if georgory else None` in `_build_assistant_message`
3. `georgory.sidebar()` before "Session metrics"
4. `georgory.render(...)` right before `st_folium(...)`
5. `georgory.chat_button()` right before `st.chat_input(...)`

**Syncing from `GeoAI - Project`:** copying `app.py` over `ui/` (`AGENTS.md` §5.2) removes the hooks unless they are in that copy too, and he then silently disappears. Apply them there as well. The import looks for this folder next to `ui/`, so keep the same layout there.

## Turn him off or remove him

| To… | Do this |
|---|---|
| Show or hide him for a session | The button with his face in the chat box, or Sidebar → 🕵️ Agent Geo-rgory |
| Move him | Sidebar → Where he stands: *Beside the map* or *On the map* |
| Change what he starts with | `"georgory_on"` (hidden) and `"georgory_place"` (beside the map) in `DEFAULTS` in `agent_avatar/georgory.py` |
| Remove him | `git apply -R avatar-georgory/app_hooks.patch`, then delete this folder |

If this folder is missing or fails to load, the guarded import sets `georgory = None` and the app runs as if he didn't exist.

## What he does

- **Where he stands:** *Beside the map* (the default) gives him a strip on the map column's left, and the map narrows by 220 px while he is showing. *On the map* covers its left edge, and the map keeps its full size. Hidden, the map has its full size either way. Moving him changes only CSS, so neither iframe reloads.
- **Map tour:** every pin the answer cites by number (`Bakhmut [1]`) becomes a stop. As he says the name, he points, the map flies to that pin, pings it and opens its tooltip. Afterwards the map returns to the answer's `map_bbox`. This runs in the browser and adds no Python reruns (`st_folium` sends one update on the map's first move after load, whoever moves it; a user's first pan does the same).
- **Briefing, not a reading:** markdown, emojis and citation marks are removed from the speech. *Brief* narration speaks the first ~500 characters; *Full answer* speaks everything. The chat always has the full text.
- **While the agent thinks:** he holds his earpiece ("DECRYPTING"), and goes back to standby if the query fails. A new question cuts off whatever he is saying.
- **Chat-box button:** a button with his face sits right of the send arrow. With an empty box it shows or hides him. With a question typed it sends the question, shows him if he was hidden, and he answers. While hidden he stays silent and keeps an unspoken answer for when he reappears, so if the first thing he does is read an answer, he skips his introduction.
- **Sound:** browsers block speech until the user interacts with the page. When that happens he shows a **▶ ПРИНЯТЬ ПЕРЕДАЧУ** button, and one click unlocks audio for the session.

## Files

| File | What it does |
|---|---|
| `app_hooks.patch` | The five hooks for `ui/app.py` |
| `agent_avatar/georgory.py` | Answer → spoken script (`avatar_payload`, `build_briefing`), sidebar section, placement and CSS |
| `agent_avatar/__init__.py` | Streamlit component wrapper (`agent_avatar`, `build_config`) |
| `agent_avatar/frontend/index.html` | The avatar: one self-contained file (SVG, speech, gestures, map tour). Open it directly in a browser for a test bar with every gesture |
| `test_georgory.py` | His tests. Those that need the hooks are skipped until the patch is applied |

## Customizing

Search `frontend/index.html` for `CUSTOMIZE`: colors, character shapes, voice, animation speed, gestures, zoom per place type. The intro text and the UI theme colors are at the top of `georgory.py`.

## Known limits

- **Voice depends on the browser.** Chrome uses Google UK English Male, which is the intended voice. Edge picks a different one.
- **The "Russian voice" toggle can pick a woman's voice** (Svetlana in Edge). It is off by default.
- Beside the map, he takes 220 px from the map column, which is a lot in a small window. Drag the column divider, collapse the sidebar, or put him on the map.
- On the map, he covers about 236×300 px, so you can't draw a box underneath him. His button hides him.
- His button and settings rest during an answer because a rerun then asks the agent twice. The app's own sidebar settings aren't protected this way: changing Pin shape during an answer sends the question twice.
- The map tour uses `window.map` inside the `st_folium` iframe, which isn't a public API. If a future version changes it, tours are skipped and he still talks.
- Leaving "DECRYPTING" after a failed query reads Streamlit's `data-test-script-state` attribute, also not a public API. If it goes away, a 3-minute limit releases him instead.
