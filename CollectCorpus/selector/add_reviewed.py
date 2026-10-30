"""Apply the manual decisions from the two Excels and rebuild the corpus.

    python -m selector.add_reviewed                (run from the CollectCorpus folder, with the Excels closed)

* summaries/ukraine_war_final/review_pages.xlsx  - review-zone pages: "להוסיף" adds the page to the corpus.
* summaries/ukraine_war_final/cleanup_pages.xlsx - borderline pages in the corpus: "להוציא" removes the page.
"לא להוסיף" / "להשאיר" are recorded too, so a checked page shows its decision in the next Excels.

The decisions are appended to selector/manual_decisions.csv (committed, so the team sees what was decided by hand)
and the corpus is rebuilt (selector.build_final_corpus): DATA.json + DATA.json.gz, the reports and the two Excels.
It can be run after every round of review; pages without a decision are left as they are.
"""
import sys
from pathlib import Path

import pandas as pd

from selector import build_final_corpus as final

sys.stdout.reconfigure(encoding="utf-8")


def read_decisions(path, kind):
    """{title: decision code} for the rows with a decision in one Excel."""
    if not path.exists():
        return {}
    yes, no, yes_code, no_code = final.DECISION_WORDS[kind]
    sheet = pd.read_excel(path)
    words = sheet["החלטה"].astype(str).str.strip()
    codes = words.map({yes: yes_code, no: no_code})
    return dict(zip(sheet.loc[codes.notna(), "כותרת"], codes.dropna()))


def main():
    rep = Path("summaries") / final.OUT
    new = {**read_decisions(rep / "review_pages.xlsx", "review"), **read_decisions(rep / "cleanup_pages.xlsx", "cleanup")}
    earlier = final.load_decisions()
    changed = {t: d for t, d in new.items() if earlier.get(t) != d}
    if not changed:
        print("no new decisions in the Excels")
        return
    final.record_decisions(changed)
    counts = pd.Series(changed).value_counts().to_dict()
    print(f"recorded {len(changed)} decisions in {final.DECISIONS}: {counts}; rebuilding...")
    final.main()


if __name__ == "__main__":
    main()
