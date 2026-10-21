"""Shared fixtures. No test here calls OpenRouter or needs an API key.

The stand-in graph is a small graph in the graph team's Vr6 format, so tests stay stable when the
real graph changes; the agent itself never falls back to it.
"""
import sys
from pathlib import Path

import networkx as nx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # the AgentRag folder

import georag_agent


def build_vr6_graph() -> nx.Graph:
    """A small graph in the Vr6 format (Graph_n_Geocoding/KNOWLEDGE_GRAPH_README.md): TEXT paragraphs,
    PER/ORG/LOC entities, IN_THE_TEXT mentions, a few text relations and SAME_AS links - including
    the kind of junk SAME_AS the real graph has ("." -> NATO, Wagner -> Africa Corps)."""
    G = nx.Graph()
    tid = [0]

    def paragraph(article, index, text, title=None):
        n = f"TEXT_{tid[0]}"
        G.add_node(n, type="TEXT", text_id=tid[0], text=text, source=article, index=index, title=title, sub_title=None)
        tid[0] += 1
        return n

    def entity(name, type_, texts, **attrs):
        G.add_node(name, type=type_, **attrs)
        for i in range(texts):
            p = paragraph(f"Article about {name}", i + 1, f"{name} is mentioned here, paragraph {i}.")
            G.add_edge(name, p, weight=1, relations={"IN_THE_TEXT": [{"start": 0, "end": len(name)}]})

    def place(lat, lon, place_type, importance, address):
        return dict(latitude=lat, longitude=lon, place_type=place_type, importance=importance, address=address,
                    geometry_wkt=f"POINT ({lon} {lat})")

    # people
    for name, n in [("Volodymyr Zelenskyy", 12), ("Zelenskyy", 15), ("Volodomyr Zelenskyy", 1),
                    ("Volodymyr Zelensky", 2), ("of President Zelenskyy", 1), ("Olena Zelenska", 3),
                    ("Valery Gerasimov", 10), ("Gerasimov", 8), ("Andrei Gerasimov", 1),
                    ("Sergei Ivanov", 3), ("Igor Ivanov", 3), ("Ivanov", 4)]:
        entity(name, "PER", n)
    # organizations
    for name, n in [("Wagner", 9), ("Wagner Group", 10), ("PMC Wagner", 2), ("Wagner Orchestra", 1),
                    ("Africa Corps", 2), (".", 5), ("NATO", 20), ("Russian Armed Forces", 9),
                    ("Ukrainian Air Force", 4), ("General Staff", 6), ("Avdiivka Coke Plant", 6)]:
        entity(name, "ORG", n)
    # places
    entity("Kyiv", "LOC", 20, **place(50.45, 30.52, "city", 0.79, "Kyiv, Ukraine"))
    entity("Kiev", "LOC", 5, **place(50.45, 30.52, "city", 0.79, "Kyiv, Ukraine"))
    entity("Kyiv City", "LOC", 1, **place(50.38, 30.47, "shop", 0.1, "Kyiv City, a shop"))
    entity("Kharkiv", "LOC", 12, **place(49.99, 36.23, "city", 0.71, "Kharkiv, Ukraine"))
    entity("Bakhmut", "LOC", 8, **place(48.59, 38.0, "town", 0.57, "Bakhmut, Donetsk Oblast, Ukraine"))
    entity("Donbas", "LOC", 7, **place(41.99, 21.43, "road", 0.04, "Donbas, Skopje, North Macedonia"))
    entity("Avdiivka Industrial Zone", "LOC", 5, **place(48.14, 37.75, "industrial", 0.3, "Avdiivka, Ukraine"))
    entity("Novorossiya", "LOC", 3)   # not geocoded

    for u, v in [("Wagner", "Africa Corps"), (".", "NATO"), ("Kyiv", "Kiev")]:
        G.add_edge(u, v, weight=0.1, relations={"SAME_AS": [{"text_id": 0, "source_start": 0, "source_end": 1,
                                                             "target_start": 2, "target_end": 3,
                                                             "subject": None, "confidence": 0.5}]})
    # articles that are events / have an entity's name
    paragraph("Battle of Bakhmut", 0, "The Battle of Bakhmut was a major battle for control of the city of Bakhmut. "
                                      "It lasted many months.")
    paragraph("Battle of Bakhmut", 1, "Wagner Group fighters attacked Bakhmut.", title="Battle")
    paragraph("Valery Gerasimov", 0, "Valery Gerasimov is a Russian army general. He is Chief of the General Staff.")
    paragraph("Kyiv", 0, "Kyiv is the capital of Ukraine.")

    # --- for the retrieve step: countries, polygons, the INSIDE hierarchy, text relations ---
    entity("Ukraine", "LOC", 30, **place(49.0, 31.0, "country", 0.94, "Ukraine"))
    G.nodes["Ukraine"]["geometry_wkt"] = "POLYGON ((22 44, 41 44, 41 53, 22 53, 22 44))"
    entity("Russia", "LOC", 30, **place(60.0, 90.0, "country", 0.94, "Russia"))
    entity("Belarus", "LOC", 5, **place(53.7, 27.9, "country", 0.8, "Belarus"))
    entity("Soledar", "LOC", 2, **place(48.68, 38.09, "town", 0.45, "Soledar, Donetsk Oblast, Ukraine"))
    entity("Maidan Nezalezhnosti", "LOC", 3, **place(50.4505, 30.524, "square", 0.5, "Maidan, Kyiv, Ukraine"))
    entity("Telegram", "ORG", 4)
    G.nodes["Kyiv"]["geometry_wkt"] = "POLYGON ((30.2 50.3, 30.8 50.3, 30.8 50.6, 30.2 50.6, 30.2 50.3))"
    for inner in ("Bakhmut", "Kharkiv", "Kyiv", "Soledar"):
        G.add_edge(inner, "Ukraine", weight=0.1, relations={"INSIDE": [{"subject": inner, "basis": "geometry"}]})

    def node_text(n):
        return G.nodes[n]["text"]

    def mention(name, text_node):
        start = node_text(text_node).find(name)
        assert start >= 0, (name, text_node)
        G.add_edge(name, text_node, weight=1, relations={"IN_THE_TEXT": [{"start": start, "end": start + len(name)}]})

    def relate(u, v, relation, text_node, subject=None, confidence=None):
        t = node_text(text_node)
        su, sv = t.find(u), t.find(v)
        assert su >= 0 and sv >= 0, (u, v, text_node)
        rec = {"text_id": G.nodes[text_node]["text_id"], "source_start": su, "source_end": su + len(u),
               "target_start": sv, "target_end": sv + len(v), "subject": subject, "confidence": confidence}
        if G.has_edge(u, v):
            G[u][v]["relations"].setdefault(relation, []).append(rec)
        else:
            G.add_edge(u, v, weight=1.0, relations={relation: [rec]})

    battle_lead = "TEXT_" + str(next(d["text_id"] for _, d in G.nodes(data=True)
                                     if d.get("source") == "Battle of Bakhmut" and d.get("index") == 0))
    battle_1 = "TEXT_" + str(next(d["text_id"] for _, d in G.nodes(data=True)
                                  if d.get("source") == "Battle of Bakhmut" and d.get("index") == 1))
    mention("Bakhmut", battle_lead)
    mention("Bakhmut", battle_1)
    mention("Wagner Group", battle_1)
    relate("Wagner Group", "Bakhmut", "ATTACKED", battle_1, subject="Wagner Group", confidence=0.9)
    spread = paragraph("Battle of Bakhmut", 2, "Fighting spread to Soledar near Bakhmut.", title="Battle")
    mention("Soledar", spread)
    mention("Bakhmut", spread)

    drones = paragraph("Attacks on Bakhmut", 0, "Russian Armed Forces launched drone attacks on Bakhmut in 2023.")
    mention("Bakhmut", drones)
    relate("Russian Armed Forces", "Bakhmut", "ATTACKED", drones, subject="Russian Armed Forces", confidence=0.85)
    claim = paragraph("Attacks on Bakhmut", 1, "Telegram posts claimed Bakhmut was captured.")
    relate("Telegram", "Bakhmut", "ATTACKED", claim, subject="Telegram", confidence=0.47)   # low: "mentioned with"
    chief = paragraph("Valery Gerasimov", 1, "Valery Gerasimov is Chief of the General Staff.")
    relate("Valery Gerasimov", "General Staff", "LEADS", chief, subject="Valery Gerasimov", confidence=0.9)
    visit = paragraph("Zelenskyy travels", 0, "Zelenskyy visited Kharkiv and then Kyiv.")
    relate("Zelenskyy", "Kharkiv", "VISITED", visit, subject="Zelenskyy", confidence=0.8)
    relate("Zelenskyy", "Kyiv", "CO_OCCURS_WITH", visit)
    borders = paragraph("Neighbours", 0, "Russia and Ukraine both border Belarus.")
    relate("Russia", "Belarus", "CO_OCCURS_WITH", borders)
    relate("Ukraine", "Belarus", "CO_OCCURS_WITH", borders)
    relate("Russia", "Ukraine", "CO_OCCURS_WITH", borders)
    strike = paragraph("Drones over Kyiv", 0, "A drone hit a building near Maidan Nezalezhnosti.")
    mention("Maidan Nezalezhnosti", strike)

    # presidents (LEADS place), a fleet with only a low-confidence leader, and an organization link
    entity("Vladimir Putin", "PER", 5)
    entity("Petro Poroshenko", "PER", 3)
    entity("Black Sea Fleet", "ORG", 3)
    entity("Viktor Sokolov", "PER", 1)
    for who, where, text in [("Zelenskyy", "Ukraine", "Zelenskyy is the president of Ukraine."),
                             ("Vladimir Putin", "Russia", "Vladimir Putin is the president of Russia."),
                             ("Petro Poroshenko", "Ukraine", "Petro Poroshenko was president of Ukraine."),
                             ("Petro Poroshenko", "Ukraine", "In 2014 Petro Poroshenko led Ukraine.")]:
        p = paragraph("Presidents", 0, text)
        relate(who, where, "LEADS", p, subject=who, confidence=0.9)
    fleet = paragraph("Black Sea Fleet", 0, "Viktor Sokolov commanded the Black Sea Fleet.")
    relate("Viktor Sokolov", "Black Sea Fleet", "LEADS", fleet, subject="Viktor Sokolov", confidence=0.45)
    staff = paragraph("Command", 0, "The Russian Armed Forces answer to the General Staff.")
    relate("Russian Armed Forces", "General Staff", "CO_OCCURS_WITH", staff)
    return G


@pytest.fixture(scope="session")
def vr6_index():
    from graph_index import GraphIndex
    return GraphIndex(build_vr6_graph())


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """Make sure no test can reach OpenRouter, even if the developer has a real .env."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def fresh_graph_cache(monkeypatch):
    """georag_agent keeps the loaded graph for the life of the process; tests start without it."""
    monkeypatch.setattr(georag_agent, "_graph", None)
