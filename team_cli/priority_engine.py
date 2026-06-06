"""Priority heuristics for ProjectMessage routing.

Priority scale: 1=Low, 2=Normal, 3=Feature, 4=Follow-up, 5=Urgent
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .embedding_classifier import EmbeddingClassifier

if TYPE_CHECKING:
    from .models import Project, ProjectMessage

PRIORITY_LABELS: dict[int, str] = {
    1: "Low",
    2: "Normal",
    3: "Feature",
    4: "Follow-up",
    5: "Urgent",
}

PRIORITY_COLORS: dict[int, str] = {
    1: "#6c757d",
    2: "#0d6efd",
    3: "#ffc107",
    4: "#fd7e14",
    5: "#dc3545",
}

_URGENT_KEYWORDS = {"bug", "erreur", "error", "fix", "corriger", "crash", "broken", "urgent"}
_FEATURE_KEYWORDS = {"nouvelle fonctionnalité", "new feature", "feature", "feat:", "ajout", "ajouter"}

_embedding_classifier = EmbeddingClassifier()
EMBEDDING_AVAILABLE: bool = _embedding_classifier.is_available()


def calculate_priority(message: "ProjectMessage", project: "Project | None" = None) -> int:
    """Return a priority 1–5 for *message* based on content heuristics.

    Precedence (highest wins):
    1. Urgent keywords (bug/error/fix/crash…) → 5
    2. Linked follow-up message            → 4
    3. Feature keywords                    → 3
    4. Embedding classifier (if available) → 2–5
    5. Default                             → 2
    """
    text = message.content.lower()

    if any(kw in text for kw in _URGENT_KEYWORDS):
        return 5

    if message.linked_message_id is not None:
        return 4

    if any(kw in text for kw in _FEATURE_KEYWORDS):
        return 3

    # Heuristics returned the default — try embedding for finer classification
    if EMBEDDING_AVAILABLE:
        embedded = _embedding_classifier.classify(message.content)
        if embedded != 0:
            return embedded

    return 2


def promote_priority(current_priority: int) -> int:
    """Increment priority by one, capped at 5."""
    return min(current_priority + 1, 5)
