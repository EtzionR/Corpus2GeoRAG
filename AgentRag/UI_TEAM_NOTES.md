# Notes for the UI team

Found while running `ui/app.py` against the agent (2026-10-29). We changed nothing in `ui/`; each
item says what we saw and the change we suggest.

## 1. Blank page (no map, no chat box) on PCs with Smart App Control

Windows Smart App Control blocks a compiled file of **pandas 3.x** ("An Application Control policy
has blocked this file"). Streamlit imports pandas to draw the page, so the app stops before the map
and the chat box appear. pandas 2.3.3 is allowed.

**Fix:** add `pandas<3` to `ui/requirements.txt`.

## 2. Old answers' polygons stay on the map

After each answer the app *adds* the answer's layers to the map and never clears the previous ones
(`st.session_state.map_layers.extend(agent_resp.layers)`, `app.py` ~line 2945). After a few questions
"Where is Ukraine?" shows Ukraine plus every earlier answer's outlines.

**Suggested fix:** replace instead of extend for each new answer
(`st.session_state.map_layers = list(agent_resp.layers)`), with an optional "keep previous answers
on the map" toggle if you want the old behaviour.

## 3. A "show more places" toggle

The result now says which place an answer is about: `result["map"]["focus"]` (place numbers; empty
for lists and map-area questions, which show everything).

- Non-list answers return the places they discuss, and only the focus place gets an outline
  (`shape`). "Where is Ukraine?" outlines Ukraine only.
- **Suggested:** by default draw only the `focus` places; a toggle "Show N more places" draws the rest
  of `geo_locations`. `map.not_shown` says how many more places were found beyond those.

## 4. Big topic lists

"Where were drone attacks?" now answers from the whole corpus and can return ~1,500 places
(`map.showing: "all"`). Drawing them as individual Folium markers is slow; a `MarkerCluster` keeps
the map responsive.
