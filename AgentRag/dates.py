"""Dates (P2-80): the question's time words as a calendar range, and the dates the graph gives each passage.

The graph with dates (Graph_n_Geocoding/with_dates, README section 3) gives every paragraph its date mentions:
`dates` on a TEXT node, each with its position, the text as written, and the calendar range it covers (`from`,
`to`, ISO). Three uses:
  C1  each passage the LLM reads carries its date, so the answer can say when and keep the order;
  C2  a question with a period ("in 2023") reads the passages dated in it first;
  C3  a question with only a date ("What happened on 24 February 2022?") reads the paragraphs of that date.
On the graph without dates no paragraph has a date, so none of this changes an answer.
"""
import calendar
import re
from typing import Optional

from pydantic import BaseModel

FAR_PAST, FAR_FUTURE = "0001-01-01", "9999-12-31"   # the open end of "since 2022" / "before 2014"

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9
_MONTH = "(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_YEAR = r"((?:19|20)\d\d)"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_MONTH_YEAR = re.compile(rf"\b{_DAY}\s+(?:of\s+)?{_MONTH},?\s+{_YEAR}\b")
_MONTH_DAY_YEAR = re.compile(rf"\b{_MONTH}\s+{_DAY},?\s+{_YEAR}\b")
_DAYS_MONTH_YEAR = re.compile(rf"\b{_DAY}\s*(?:-|–|to|and)\s*{_DAY}\s+{_MONTH},?\s+{_YEAR}\b")   # 24–25 February 2022
_MONTH_YEAR = re.compile(rf"\b{_MONTH},?\s+(?:of\s+)?{_YEAR}\b")
_MONTHS_YEAR = re.compile(rf"\b{_MONTH}\s*(?:-|–|to|and|until)\s*{_MONTH},?\s+{_YEAR}\b")       # March to May 2022
_PART_YEAR = re.compile(rf"\b(early|mid|late|spring|summer|autumn|fall)(?:\s+of)?\s+{_YEAR}\b")
_YEARS = re.compile(rf"\b{_YEAR}\b")
_SINCE = re.compile(r"\b(?:since|after|from|starting)\b")
_UNTIL = re.compile(r"\b(?:before|until|till|up to|prior to|by)\b")
_PARTS = {"early": (1, 4), "mid": (5, 8), "late": (9, 12), "spring": (3, 5), "summer": (6, 8),
          "autumn": (9, 11), "fall": (9, 11)}


class Period(BaseModel):
    start: str          # ISO YYYY-MM-DD, inclusive
    end: str
    label: str          # as the answer can say it: "24 February 2022", "February 2022", "since 2022"


def _month_end(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def _day(year, month, day) -> Optional[tuple[str, str]]:
    try:
        calendar.weekday(int(year), int(month), int(day))   # raises on 31 February
    except ValueError:
        return None
    iso = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return iso, iso


def _range_of(text: str) -> Optional[tuple[str, str]]:
    """The calendar range one written date covers, most specific pattern first."""
    t = text.lower()
    if m := _ISO.search(t):
        return _day(*m.groups())
    if m := _DAYS_MONTH_YEAR.search(t):
        a, b = _day(m[4], _MONTHS[m[3]], m[1]), _day(m[4], _MONTHS[m[3]], m[2])
        return (a[0], b[1]) if a and b else None
    if m := _DAY_MONTH_YEAR.search(t):
        return _day(m[3], _MONTHS[m[2]], m[1])
    if m := _MONTH_DAY_YEAR.search(t):
        return _day(m[3], _MONTHS[m[1]], m[2])
    if m := _MONTHS_YEAR.search(t):
        y = int(m[3])
        return f"{y:04d}-{_MONTHS[m[1]]:02d}-01", _month_end(y, _MONTHS[m[2]])
    if m := _MONTH_YEAR.search(t):
        y, mo = int(m[2]), _MONTHS[m[1]]
        return f"{y:04d}-{mo:02d}-01", _month_end(y, mo)
    if m := _PART_YEAR.search(t):
        y, (a, b) = int(m[2]), _PARTS[m[1]]
        return f"{y:04d}-{a:02d}-01", _month_end(y, b)
    years = [int(y) for y in _YEARS.findall(t)]
    if years:                                   # "2023", "2014–2015", "between 2022 and 2023", "the winter of 2022"
        return f"{min(years):04d}-01-01", f"{max(years):04d}-12-31"
    return None


def parse_period(time_words: list[str]) -> Optional[Period]:
    """The question's time words ("in 2023", "since February 2022", "on 24 February 2022") as one calendar
    range; several words make one range from the first to the last. None if no word names a calendar date
    ("recently", "in February" without a year)."""
    periods = []
    for words in time_words:
        r = _range_of(words)
        if r is None:
            continue
        low, said = words.lower(), label(*r)
        if _SINCE.search(low) and not re.search(r"\b(?:to|until|and|-|–)\b", low.split(None, 1)[-1]):
            periods.append(Period(start=r[0], end=FAR_FUTURE, label=f"since {said}"))   # from then on
        elif _UNTIL.search(low):
            periods.append(Period(start=FAR_PAST, end=r[1], label=f"up to {said}"))
        else:
            periods.append(Period(start=r[0], end=r[1], label=said))
    if len(periods) <= 1:
        return periods[0] if periods else None
    start, end = min(p.start for p in periods), max(p.end for p in periods)
    return Period(start=start, end=end, label=" – ".join(p.label for p in periods))


def label(start: str, end: str) -> str:
    """A calendar range in words: "24 February 2022", "February 2022", "2022", "2014–2015"."""
    y1, m1, d1 = (int(x) for x in start.split("-"))
    y2, m2, d2 = (int(x) for x in end.split("-"))
    whole_months = d1 == 1 and end == _month_end(y2, m2)
    if start == end:
        return f"{d1} {calendar.month_name[m1]} {y1}"
    if whole_months and (m1, m2) == (1, 12):
        return str(y1) if y1 == y2 else f"{y1}–{y2}"
    if whole_months:
        if (y1, m1) == (y2, m2):
            return f"{calendar.month_name[m1]} {y1}"
        first = calendar.month_name[m1] + ("" if y1 == y2 else f" {y1}")
        return f"{first} – {calendar.month_name[m2]} {y2}"
    if (y1, m1) == (y2, m2):
        return f"{d1}–{d2} {calendar.month_name[m1]} {y1}"
    return f"{label(start, start)} – {label(end, end)}"


def within(d: dict, period: Period) -> bool:
    """A date mention (or a record's date) lies inside the period. A coarser mention ("2022" for a question
    about 24 February 2022) overlaps the period but doesn't date anything in it, so it doesn't count."""
    return bool(d and d.get("from") and d.get("to")) and period.start <= d["from"] and d["to"] <= period.end


def passage_dates(node: dict, a: int, b: int) -> tuple[list[dict], Optional[str]]:
    """The dated mentions inside text[a:b] of a paragraph ("passage"); if there are none, the last dated one
    before the passage in the same paragraph ("paragraph"), as the graph dates its relation records."""
    dated = [d for d in node.get("dates") or [] if d.get("from")]
    inside = [d for d in dated if a <= d["start"] and d["end"] <= b]
    if inside:
        return inside, "passage"
    before = [d for d in dated if d["end"] <= a]
    return ([before[-1]], "paragraph") if before else ([], None)


def describe(dates: list[dict], most: int = 2) -> Optional[str]:
    """The distinct dates of a passage in words, at most `most` of them."""
    words = list(dict.fromkeys(label(d["from"], d["to"]) for d in dates))
    return ", ".join(words[:most]) + (" …" if len(words) > most else "") if words else None


def _dated_texts(gi) -> list[tuple[int, list[dict]]]:
    """(text id, its dated mentions) for every paragraph that has one; built once per graph."""
    if getattr(gi, "_dated_cache", None) is None:
        gi._dated_cache = [(n["text_id"], [d for d in n["dates"] if d.get("from")]) for _, n in gi.G.nodes(data=True)
                           if n.get("type") == "TEXT" and any(d.get("from") for d in n.get("dates") or [])]
    return gi._dated_cache


def texts_in(gi, period: Period) -> dict[int, list[dict]]:
    """Every paragraph with a date mention inside the period, with those mentions (text id -> mentions)."""
    out = {}
    for tid, mentions in _dated_texts(gi):
        hit = [d for d in mentions if within(d, period)]
        if hit:
            out[tid] = hit
    return out


def has_dates(gi) -> bool:
    """False for the graph without dates: no paragraph carries a date."""
    return bool(_dated_texts(gi))
