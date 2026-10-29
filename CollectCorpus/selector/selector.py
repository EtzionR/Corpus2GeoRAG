"""The selector: decides how related a page is to the corpus (the Russia-Ukraine war, military focus).

    page text -> paragraphs -> vectors (EmbeddingGemma 2) -> logistic regression -> a probability per paragraph
              -> page score = share of paragraphs whose probability >= PARAGRAPH_THRESHOLD   (0..1)
              -> three zones:  score >= ACCEPT_THRESHOLD  -> "accept"  (enters the corpus)
                               (optional quantity rule: also "accept" when a page has at least
                                MIN_RELATED_PARAGRAPHS related paragraphs, for long pages with a military section)
                               score <  REJECT_THRESHOLD  -> "reject"  (listed in the report)
                               in between                 -> "review"  (listed in the report for a manual decision)

v3 (2026-10-23) is trained on the paragraphs of 40 hand-picked pages (selector/training_pages_v3.csv): 20 clearly
related (label 1) and 20 not related (label 0): close in topic but not military, or military but not this war.
Paragraphs that contradict their page's label were removed after cross-validation (selector/flag_paragraphs.py).
The thresholds are chosen by testing on the existing corpus.
"""
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression

from selector.build_training_set import split_paragraphs

E5_MODEL = "intfloat/multilingual-e5-large"
GEMMA_MODEL = "google/embeddinggemma-2"
# Chosen 2026-10-23 (CompareEmbeddings.ipynb): same accuracy as E5 (exam AUC 0.868 vs 0.864, accept precision 92.3%
# for both), more related pages accepted (1,456 vs 1,372), ~1.6x faster, 768 numbers per vector instead of 1024.
MODEL = GEMMA_MODEL
# Chosen on the v2 run (2026-10-18): AUC was best at a paragraph threshold of 0.7 (0.834);
# the two page thresholds leave a "review" zone between them.
PARAGRAPH_THRESHOLD = 0.7   # a paragraph counts as related from this probability
ACCEPT_THRESHOLD = 0.30     # a page with at least this share of related paragraphs enters
REJECT_THRESHOLD = 0.10     # a page below this share is rejected; in between = manual review
# Quantity rule (chosen 2026-10-18 for new pages): a long page with >= 7 related paragraphs enters even if their
# share is low (e.g. a city page with a battle section). None = off.
MIN_RELATED_PARAGRAPHS = 7


def load_encoder(model_name=MODEL, device=None):
    """The embedding model. EmbeddingGemma 2 is loaded text-only (no image/audio parts), in float32 as its card says."""
    from sentence_transformers import SentenceTransformer
    if model_name == GEMMA_MODEL:
        import torch
        encoder = SentenceTransformer(model_name, device=device,
                                      config_kwargs={"vision_config": None, "audio_config": None},
                                      model_kwargs={"torch_dtype": torch.float32})
        encoder.max_seq_length = 2048
        return encoder
    return SentenceTransformer(model_name, device=device)


class Selector:
    def __init__(self, encoder, model_name=MODEL, paragraph_threshold=PARAGRAPH_THRESHOLD,
                 accept_threshold=ACCEPT_THRESHOLD, reject_threshold=REJECT_THRESHOLD,
                 min_related_paragraphs=MIN_RELATED_PARAGRAPHS, clf=None):
        self.encoder = encoder              # a sentence_transformers.SentenceTransformer (load_encoder)
        self.model_name = model_name
        self.paragraph_threshold = paragraph_threshold
        self.accept_threshold = accept_threshold
        self.reject_threshold = reject_threshold
        self.min_related_paragraphs = min_related_paragraphs
        self.clf = clf

    # ---------------------------------------------------------------- vectors
    def embed(self, texts, batch_size=32, show_progress_bar=False):
        """Paragraph vectors, with each model's own prompt: E5 expects "query: ", Gemma its classification prompt."""
        if self.model_name == E5_MODEL:
            return self.encoder.encode(["query: " + t for t in texts], batch_size=batch_size,
                                       normalize_embeddings=True, show_progress_bar=show_progress_bar)
        return self.encoder.encode(texts, prompt_name="Classification", batch_size=batch_size,
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
        """The classifier and the settings; the embedding model itself is downloaded by name when loading."""
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
            encoder = load_encoder(config["model_name"])
        return cls(encoder, clf=joblib.load(folder / "selector_logreg.joblib"), **config)
