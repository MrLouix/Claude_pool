"""Optional sentence-transformers embedding classifier for priority detection.

When sentence_transformers is not installed, all public methods degrade
gracefully: is_available() returns False and classify() returns 0.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


class EmbeddingClassifier:
    """Classify text into priority categories using cosine similarity.

    Lazily loads the SentenceTransformer model on first classify() call.
    Prototype embeddings are cached after the first encode.
    """

    MODEL_NAME = "all-MiniLM-L6-v2"

    CATEGORY_PROTOTYPES: dict[int, list[str]] = {
        5: ["fix bug crash error broken urgent critical"],
        4: ["follow up continuation clarification more detail"],
        3: ["new feature add implement create functionality"],
        2: ["general question help information"],
    }

    def __init__(self) -> None:
        """Initialise with no model loaded; loading is deferred to first classify() call."""
        self._model = None
        self._prototype_embeddings: dict[int, np.ndarray] | None = None

    def _load_model(self) -> None:
        """Lazily import and load the SentenceTransformer model."""
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import]
            self._model = SentenceTransformer(self.MODEL_NAME)
        except Exception:
            self._model = None

    def is_available(self) -> bool:
        """Return True if sentence_transformers is importable."""
        try:
            import sentence_transformers  # type: ignore[import]  # noqa: F401
            return True
        except (ImportError, Exception):
            return False

    def _get_prototype_embeddings(self) -> dict[int, np.ndarray]:
        """Encode prototype texts once and cache the results."""
        if self._prototype_embeddings is None:
            import numpy as np
            self._prototype_embeddings = {}
            for priority, texts in self.CATEGORY_PROTOTYPES.items():
                embeddings = self._model.encode(texts)  # type: ignore[union-attr]
                self._prototype_embeddings[priority] = np.mean(embeddings, axis=0)
        return self._prototype_embeddings

    def classify(self, text: str) -> int:
        """Return the best-matching priority (2–5) or 0 on failure/unavailability.

        A return value of 0 signals the caller to fall back to keyword heuristics.
        """
        if not self.is_available():
            return 0

        if self._model is None:
            self._load_model()

        if self._model is None:
            return 0

        try:
            import numpy as np

            text_emb = self._model.encode([text])[0]
            prototypes = self._get_prototype_embeddings()

            best_priority = 0
            best_sim = -1.0

            for priority, proto_emb in prototypes.items():
                norm = np.linalg.norm(text_emb) * np.linalg.norm(proto_emb)
                sim = float(np.dot(text_emb, proto_emb) / norm) if norm > 0 else 0.0
                if sim > best_sim:
                    best_sim = sim
                    best_priority = priority

            return best_priority
        except Exception:
            return 0
