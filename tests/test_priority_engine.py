"""Tests for team_cli/priority_engine.py (Phase 4 Step 2)."""

from team_cli.models import ProjectMessage
from team_cli.priority_engine import (
    PRIORITY_COLORS,
    PRIORITY_LABELS,
    calculate_priority,
    promote_priority,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg(content: str, linked_message_id: str | None = None) -> ProjectMessage:
    return ProjectMessage(
        id="msg_test",
        project_id="proj_test",
        content=content,
        role="user",
        linked_message_id=linked_message_id,
    )


# ---------------------------------------------------------------------------
# calculate_priority — urgent keywords → 5
# ---------------------------------------------------------------------------

class TestUrgentKeywords:
    def test_bug_returns_5(self):
        assert calculate_priority(_msg("there is a bug in the login")) == 5

    def test_fix_returns_5(self):
        assert calculate_priority(_msg("please fix the payment flow")) == 5

    def test_erreur_returns_5(self):
        assert calculate_priority(_msg("une erreur survient au démarrage")) == 5

    def test_error_returns_5(self):
        assert calculate_priority(_msg("error loading config")) == 5

    def test_corriger_returns_5(self):
        assert calculate_priority(_msg("il faut corriger ce comportement")) == 5

    def test_crash_returns_5(self):
        assert calculate_priority(_msg("the app crash on startup")) == 5

    def test_broken_returns_5(self):
        assert calculate_priority(_msg("the API is broken")) == 5

    def test_urgent_returns_5(self):
        assert calculate_priority(_msg("urgent: deploy is failing")) == 5

    def test_case_insensitive_Bug(self):
        assert calculate_priority(_msg("Bug in production")) == 5

    def test_case_insensitive_FIX(self):
        assert calculate_priority(_msg("FIX the login issue")) == 5

    def test_case_insensitive_ERROR(self):
        assert calculate_priority(_msg("ERROR: null pointer")) == 5

    def test_bug_keyword_beats_linked_message_id(self):
        # Both conditions met — urgent wins
        assert calculate_priority(_msg("bug in the API", linked_message_id="msg_parent")) == 5


# ---------------------------------------------------------------------------
# calculate_priority — follow-up (linked) → 4
# ---------------------------------------------------------------------------

class TestFollowUp:
    def test_linked_message_id_returns_4(self):
        assert calculate_priority(_msg("can you elaborate?", linked_message_id="msg_abc")) == 4

    def test_linked_with_feature_content_returns_4(self):
        # linked_message_id takes precedence over feature keyword
        assert calculate_priority(_msg("add a new feature here", linked_message_id="msg_xyz")) == 4

    def test_no_linked_id_does_not_return_4(self):
        assert calculate_priority(_msg("can you elaborate?")) != 4


# ---------------------------------------------------------------------------
# calculate_priority — feature keywords → 3
# ---------------------------------------------------------------------------

class TestFeatureKeywords:
    def test_feature_returns_3(self):
        assert calculate_priority(_msg("add a dark mode feature")) == 3

    def test_new_feature_returns_3(self):
        assert calculate_priority(_msg("implement new feature: export to PDF")) == 3

    def test_feat_colon_returns_3(self):
        assert calculate_priority(_msg("feat: add user avatar upload")) == 3

    def test_ajout_returns_3(self):
        assert calculate_priority(_msg("ajout d'un tableau de bord")) == 3

    def test_ajouter_returns_3(self):
        assert calculate_priority(_msg("ajouter une option d'export")) == 3

    def test_nouvelle_fonctionnalite_returns_3(self):
        assert calculate_priority(_msg("nouvelle fonctionnalité : dark mode")) == 3

    def test_case_insensitive_feature(self):
        assert calculate_priority(_msg("FEATURE request: better UX")) == 3


# ---------------------------------------------------------------------------
# calculate_priority — default → 2
# ---------------------------------------------------------------------------

class TestDefaultPriority:
    def test_generic_message_returns_2(self):
        assert calculate_priority(_msg("how do I reset my password?")) == 2

    def test_empty_content_returns_2(self):
        assert calculate_priority(_msg("")) == 2

    def test_no_keywords_no_linked_id_returns_2(self):
        assert calculate_priority(_msg("please update the documentation")) == 2


# ---------------------------------------------------------------------------
# promote_priority
# ---------------------------------------------------------------------------

class TestPromotePriority:
    def test_promote_1_to_2(self):
        assert promote_priority(1) == 2

    def test_promote_2_to_3(self):
        assert promote_priority(2) == 3

    def test_promote_3_to_4(self):
        assert promote_priority(3) == 4

    def test_promote_4_to_5(self):
        assert promote_priority(4) == 5

    def test_promote_5_stays_5(self):
        assert promote_priority(5) == 5


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_priority_labels_has_all_5_entries(self):
        assert set(PRIORITY_LABELS.keys()) == {1, 2, 3, 4, 5}

    def test_priority_labels_values(self):
        assert PRIORITY_LABELS[1] == "Low"
        assert PRIORITY_LABELS[2] == "Normal"
        assert PRIORITY_LABELS[3] == "Feature"
        assert PRIORITY_LABELS[4] == "Follow-up"
        assert PRIORITY_LABELS[5] == "Urgent"

    def test_priority_colors_has_all_5_entries(self):
        assert set(PRIORITY_COLORS.keys()) == {1, 2, 3, 4, 5}

    def test_priority_colors_are_css_hex(self):
        for color in PRIORITY_COLORS.values():
            assert color.startswith("#"), f"{color!r} is not a CSS hex color"
            assert len(color) in (4, 7), f"{color!r} has unexpected length"
