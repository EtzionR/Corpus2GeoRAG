"""The selector: decides how related a page is to the corpus (the Russia-Ukraine war, military focus).

    page text -> paragraphs -> E5 vectors -> logistic regression -> a probability per paragraph
              -> page score = share of paragraphs whose probability >= PARAGRAPH_THRESHOLD   (0..1)
              -> three zones:  score >= ACCEPT_THRESHOLD  -> "accept"  (enters the corpus)
                               (optional quantity rule: also "accept" when a page has at least
                                MIN_RELATED_PARAGRAPHS related paragraphs, for long pages with a military section)
                               score <  REJECT_THRESHOLD  -> "reject"  (listed in the report)
                               in between                 -> "review"  (listed in the report for a manual decision)

Trained on paragraphs of 20 hand-picked pages (data/selector/paragraphs.csv): 10 clearly related (label 1)
and 10 not related (label 0): close in topic but not military, or military but not this war.
The thresholds are chosen by testing on the existing corpus.
"""
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression

from selector.build_training_set import split_paragraphs

E5_MODEL = "intfloat/multilingual-e5-large"
# Chosen on the v2 run (2026-10-18): AUC was best at a paragraph threshold of 0.7 (0.834);
# the two page thresholds leave a "review" zone between them.
PARAGRAPH_THRESHOLD = 0.7   # a paragraph counts as related from this probability
ACCEPT_THRESHOLD = 0.30     # a page with at least this share of related paragraphs enters
REJECT_THRESHOLD = 0.10     # a page below this share is rejected; in between = manual review
# Quantity rule (chosen 2026-10-18 for new pages): a long page with >= 7 related paragraphs enters even if their
# share is low (e.g. a city page with a battle section). None = off.
MIN_RELATED_PARAGRAPHS = 7


class Selector:
    def __init__(self, encoder, model_name=E5_MODEL, paragraph_threshold=PARAGRAPH_THRESHOLD,
                 accept_threshold=ACCEPT_THRESHOLD, reject_threshold=REJECT_THRESHOLD,
                 min_related_paragraphs=MIN_RELATED_PARAGRAPHS, clf=None):
        self.encoder = encoder              # a sentence_transformers.SentenceTransformer (E5)
        self.model_name = model_name
        self.paragraph_threshold = paragraph_threshold
        self.accept_threshold = accept_threshold
        self.reject_threshold = reject_threshold
        self.min_related_paragraphs = min_related_paragraphs
        self.clf = clf

    # ---------------------------------------------------------------- vectors
    def embed(self, texts, batch_size=64, show_progress_bar=False):
        """E5 vectors; E5 expects the "query: " prefix for this kind of task."""
        return self.encoder.encode(["query: " + t for t in texts], batch_size=batch_size,
                                   normalize_embeddings=True, show_progress_bar=show_progress_bar)

    # ---------------------------------------------------------------- training
    def fit(self, paragraphs, labels, vectors=None):
        """Logistic regression on the paragraph vectors. class_weight="balanced" evens out the
        different number of paragraphs in the two groups."""
        x = self.embed(paragraphs, show_progress_bar=True) if vectors is None else vectors
        self.clf = LogisticRegression(C=10, max_iter=2000, class_weight="balanced").fit(x, labels)
        return self

    # ---------------------------------------------------------------- scoring
    def paragraph_scores(self, paragraphs, vectors=None):
        """Probability (0..1) that each paragraph is related."""
        if vectors is None:
            if not paragraphs:
                return np.array([])
            vectors = self.embed(paragraphs)
        return self.clf.predict_proba(vectors)[:, 1]

    def page_score(self, paragraph_probs, paragraph_threshold=None):
        """Share of the page's paragraphs that count as related (0..1)."""
        t = self.paragraph_threshold if paragraph_threshold is None else paragraph_threshold
        return float(np.mean(np.asarray(paragraph_probs) >= t)) if len(paragraph_probs) else 0.0

    def decision(self, score, related=0):
        """"accept", "review" or "reject" for a page score (and its number of related paragraphs)."""
        if score >= self.accept_threshold or (self.min_related_paragraphs and related >= self.min_related_paragraphs):
            return "accept"
        return "reject" if score < self.reject_threshold else "review"

    def score_page(self, text):
        """Everything for one page's raw text: {"score", "decision", "paragraphs", "related_paragraphs"}."""
        paragraphs = [p for _, p in split_paragraphs(text)]
        probs = self.paragraph_scores(paragraphs)
        score = self.page_score(probs)
        related = int((probs >= self.paragraph_threshold).sum())
        return {"score": round(score, 3), "decision": self.decision(score, related), "paragraphs": len(paragraphs),
                "related_paragraphs": related}

    # ---------------------------------------------------------------- save / load
    def save(self, folder):
        """The classifier and the settings; the E5 model itself is downloaded by name when loading."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.clf, folder / "selector_logreg.joblib")
        (folder / "selector_config.json").write_text(json.dumps({
            "model_name": self.model_name, "paragraph_threshold": self.paragraph_threshold,
            "accept_threshold": self.accept_threshold, "reject_threshold": self.reject_threshold,
            "min_related_paragraphs": self.min_related_paragraphs}, indent=2),
            encoding="utf-8")

    @classmethod
    def load(cls, folder, encoder=None):
        folder = Path(folder)
        config = json.loads((folder / "selector_config.json").read_text(encoding="utf-8"))
        if encoder is None:
            from sentence_transformers import SentenceTransformer
            encoder = SentenceTransformer(config["model_name"])
        return cls(encoder, clf=joblib.load(folder / "selector_logreg.joblib"), **config)
