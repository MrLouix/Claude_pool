"""Tests for EmbeddingClassifier and the updated calculate_priority() integration."""

import sys
from unittest.mock import MagicMock

import pytest

from team_cli.embedding_classifier import EmbeddingClassifier
from team_cli.models import Project, ProjectMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _message(content: str, linked_id: str | None = None) -> ProjectMessage:
    return ProjectMessage(
        id="msg-test",
        project_id="proj-test",
        content=content,
        role="user",
        linked_message_id=linked_id,
    )


def _project() -> Project:
    return Project(id="proj-test", name="Test", directory="/tmp")


# ---------------------------------------------------------------------------
# EmbeddingClassifier.is_available()
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_returns_bool(self):
        classifier = EmbeddingClassifier()
        result = classifier.is_available()
        assert isinstance(result, bool)

    def test_returns_false_when_sentence_transformers_not_installed(self, monkeypatch):
        """Simulate missing package by injecting None into sys.modules."""
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        classifier = EmbeddingClassifier()
        assert classifier.is_available() is False

    def test_returns_true_when_installed(self):
        """Only runs when sentence_transformers is actually importable."""
        try:
            import sentence_transformers  # noqa: F401
            installed = True
        except ImportError:
            installed = False

        classifier = EmbeddingClassifier()
        assert classifier.is_available() == installed


# ---------------------------------------------------------------------------
# EmbeddingClassifier.classify() — unavailability path
# ---------------------------------------------------------------------------

class TestClassifyFallback:
    def test_returns_0_when_is_available_false(self, monkeypatch):
        """classify() returns 0 (fallback signal) when model is unavailable."""
        classifier = EmbeddingClassifier()
        monkeypatch.setattr(classifier, "is_available", lambda: False)
        assert classifier.classify("fix the bug") == 0

    def test_returns_0_when_sentence_transformers_missing(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        classifier = EmbeddingClassifier()
        assert classifier.classify("new feature request") == 0

    def test_returns_0_when_model_load_raises(self, monkeypatch):
        """classify() returns 0 if the model raises during load."""
        def bad_load(self):
            self._model = None

        monkeypatch.setattr(EmbeddingClassifier, "_load_model", bad_load)

        classifier = EmbeddingClassifier()
        # Make is_available return True but model stays None
        monkeypatch.setattr(classifier, "is_available", lambda: True)
        assert classifier.classify("hello world") == 0

    def test_returns_0_when_encode_raises(self, monkeypatch):
        """classify() catches exceptions from model.encode() and returns 0."""
        bad_model = MagicMock()
        bad_model.encode.side_effect = RuntimeError("GPU OOM")

        classifier = EmbeddingClassifier()
        classifier._model = bad_model
        monkeypatch.setattr(classifier, "is_available", lambda: True)
        assert classifier.classify("anything") == 0


# ---------------------------------------------------------------------------
# EmbeddingClassifier.classify() — happy path (requires sentence_transformers)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not EmbeddingClassifier().is_available(),
    reason="sentence_transformers not installed",
)
class TestClassifyHappyPath:
    def setup_method(self):
        self.classifier = EmbeddingClassifier()

    def test_returns_int(self):
        result = self.classifier.classify("help me with something")
        assert isinstance(result, int)

    def test_returns_priority_in_range_2_to_5(self):
        for text in [
            "fix the crash in production",
            "can you follow up on my last question",
            "add a new export feature",
            "what does this function do",
        ]:
            result = self.classifier.classify(text)
            assert 2 <= result <= 5, f"Expected 2–5 for {text!r}, got {result}"

    def test_does_not_return_0(self):
        result = self.classifier.classify("general question about the project")
        assert result != 0

    def test_bug_text_scores_toward_urgent(self):
        """Urgent-sounding text should score ≥ normal priority."""
        urgent = self.classifier.classify("critical bug crash production broken")
        normal = self.classifier.classify("what is the weather today")
        assert urgent >= normal

    def test_prototype_embeddings_cached(self):
        """Second classify() call uses cached prototype embeddings."""
        self.classifier.classify("first call")
        cache_after_first = self.classifier._prototype_embeddings
        self.classifier.classify("second call")
        assert self.classifier._prototype_embeddings is cache_after_first

    def test_model_loaded_lazily(self):
        """Model is None before first classify(), loaded after."""
        fresh = EmbeddingClassifier()
        assert fresh._model is None
        fresh.classify("trigger load")
        assert fresh._model is not None


# ---------------------------------------------------------------------------
# calculate_priority() integration
# ---------------------------------------------------------------------------

class TestCalculatePriorityKeywords:
    """Keyword heuristics are unchanged regardless of embedding availability."""

    def test_bug_keyword_always_returns_5(self):
        from team_cli.priority_engine import calculate_priority
        msg = _message("there is a bug in the login flow")
        assert calculate_priority(msg) == 5

    def test_crash_keyword_returns_5(self):
        from team_cli.priority_engine import calculate_priority
        assert calculate_priority(_message("app crash on startup")) == 5

    def test_fix_keyword_returns_5(self):
        from team_cli.priority_engine import calculate_priority
        assert calculate_priority(_message("please fix the form validation")) == 5

    def test_urgent_keyword_returns_5(self):
        from team_cli.priority_engine import calculate_priority
        assert calculate_priority(_message("urgent: deploy is broken")) == 5

    def test_linked_message_returns_4(self):
        from team_cli.priority_engine import calculate_priority
        msg = _message("continuing from earlier", linked_id="prev-msg-id")
        assert calculate_priority(msg) == 4

    def test_feature_keyword_returns_3(self):
        from team_cli.priority_engine import calculate_priority
        assert calculate_priority(_message("add a new feature for exports")) == 3

    def test_keyword_takes_precedence_over_embedding(self, monkeypatch):
        """Even if embedding is available, keywords win."""
        from team_cli import priority_engine
        mock_classifier = MagicMock()
        mock_classifier.is_available.return_value = True
        mock_classifier.classify.return_value = 2

        monkeypatch.setattr(priority_engine, "_embedding_classifier", mock_classifier)
        monkeypatch.setattr(priority_engine, "EMBEDDING_AVAILABLE", True)

        msg = _message("fix the critical bug now")
        from team_cli.priority_engine import calculate_priority
        assert calculate_priority(msg) == 5
        mock_classifier.classify.assert_not_called()


class TestCalculatePriorityEmbeddingFallback:
    """Behavior when EMBEDDING_AVAILABLE is False."""

    def test_falls_back_to_2_when_embedding_unavailable(self, monkeypatch):
        from team_cli import priority_engine
        monkeypatch.setattr(priority_engine, "EMBEDDING_AVAILABLE", False)

        from team_cli.priority_engine import calculate_priority
        msg = _message("some general question without keywords")
        assert calculate_priority(msg) == 2

    def test_embedding_not_called_when_unavailable(self, monkeypatch):
        from team_cli import priority_engine
        mock_classifier = MagicMock()
        monkeypatch.setattr(priority_engine, "_embedding_classifier", mock_classifier)
        monkeypatch.setattr(priority_engine, "EMBEDDING_AVAILABLE", False)

        from team_cli.priority_engine import calculate_priority
        calculate_priority(_message("neutral text"))
        mock_classifier.classify.assert_not_called()

    def test_falls_back_to_2_when_classify_returns_0(self, monkeypatch):
        """If classify() returns 0 (model error), heuristic default (2) is used."""
        from team_cli import priority_engine
        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = 0
        monkeypatch.setattr(priority_engine, "_embedding_classifier", mock_classifier)
        monkeypatch.setattr(priority_engine, "EMBEDDING_AVAILABLE", True)

        from team_cli.priority_engine import calculate_priority
        assert calculate_priority(_message("something neutral")) == 2


class TestCalculatePriorityEmbeddingActive:
    """Embedding result is used when available and heuristics return default."""

    def test_embedding_result_used_when_heuristic_returns_default(self, monkeypatch):
        from team_cli import priority_engine
        mock_classifier = MagicMock()
        mock_classifier.classify.return_value = 3
        monkeypatch.setattr(priority_engine, "_embedding_classifier", mock_classifier)
        monkeypatch.setattr(priority_engine, "EMBEDDING_AVAILABLE", True)

        from team_cli.priority_engine import calculate_priority
        result = calculate_priority(_message("neutral text without keywords"))
        assert result == 3
        mock_classifier.classify.assert_called_once()

    def test_embedding_not_called_when_feature_keyword_matched(self, monkeypatch):
        """Feature keyword short-circuits before embedding is tried."""
        from team_cli import priority_engine
        mock_classifier = MagicMock()
        monkeypatch.setattr(priority_engine, "_embedding_classifier", mock_classifier)
        monkeypatch.setattr(priority_engine, "EMBEDDING_AVAILABLE", True)

        from team_cli.priority_engine import calculate_priority
        calculate_priority(_message("add a new feature to the app"))
        mock_classifier.classify.assert_not_called()


# ---------------------------------------------------------------------------
# EMBEDDING_AVAILABLE constant
# ---------------------------------------------------------------------------

class TestEmbeddingAvailableConstant:
    def test_is_bool(self):
        from team_cli.priority_engine import EMBEDDING_AVAILABLE
        assert isinstance(EMBEDDING_AVAILABLE, bool)

    def test_matches_classifier_is_available(self):
        from team_cli.priority_engine import EMBEDDING_AVAILABLE
        classifier = EmbeddingClassifier()
        assert EMBEDDING_AVAILABLE == classifier.is_available()
