"""Tests for CI/linting configuration files.

Verifies that pyproject.toml, .pre-commit-config.yaml, and
.github/workflows/ci.yml are present and structurally correct.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent


class TestPyprojectRuffConfig:
    """pyproject.toml contains the required ruff sections."""

    def _toml_text(self) -> str:
        return (ROOT / "pyproject.toml").read_text()

    def test_ruff_section_present(self):
        assert "[tool.ruff]" in self._toml_text()

    def test_ruff_lint_section_present(self):
        assert "[tool.ruff.lint]" in self._toml_text()

    def test_ruff_line_length_set(self):
        assert "line-length = 100" in self._toml_text()

    def test_ruff_target_version_set(self):
        assert 'target-version = "py311"' in self._toml_text()

    def test_ruff_select_includes_core_codes(self):
        text = self._toml_text()
        for code in ("E", "F", "W", "I", "N", "UP"):
            assert code in text

    def test_ruff_in_dev_dependencies(self):
        assert "ruff>=" in self._toml_text()

    def test_mypy_strict_true(self):
        assert "strict = true" in self._toml_text()


class TestPreCommitConfig:
    """`.pre-commit-config.yaml` exists and references required hooks."""

    def _yaml_text(self) -> str:
        path = ROOT / ".pre-commit-config.yaml"
        assert path.exists(), ".pre-commit-config.yaml not found"
        return path.read_text()

    def test_file_exists(self):
        assert (ROOT / ".pre-commit-config.yaml").exists()

    def test_ruff_pre_commit_repo_referenced(self):
        assert "astral-sh/ruff-pre-commit" in self._yaml_text()

    def test_ruff_hook_present(self):
        assert "id: ruff" in self._yaml_text()

    def test_ruff_format_hook_present(self):
        assert "id: ruff-format" in self._yaml_text()

    def test_pre_commit_hooks_repo_referenced(self):
        assert "pre-commit/pre-commit-hooks" in self._yaml_text()

    def test_trailing_whitespace_hook_present(self):
        assert "id: trailing-whitespace" in self._yaml_text()

    def test_end_of_file_fixer_hook_present(self):
        assert "id: end-of-file-fixer" in self._yaml_text()

    def test_check_yaml_hook_present(self):
        assert "id: check-yaml" in self._yaml_text()

    def test_check_json_hook_present(self):
        assert "id: check-json" in self._yaml_text()


class TestCIWorkflow:
    """`.github/workflows/ci.yml` exists and has the required steps."""

    def _yaml_text(self) -> str:
        path = ROOT / ".github" / "workflows" / "ci.yml"
        assert path.exists(), ".github/workflows/ci.yml not found"
        return path.read_text()

    def test_file_exists(self):
        assert (ROOT / ".github" / "workflows" / "ci.yml").exists()

    def test_triggers_on_push(self):
        assert "push:" in self._yaml_text()

    def test_triggers_on_pull_request(self):
        assert "pull_request:" in self._yaml_text()

    def test_uses_ubuntu_latest(self):
        assert "ubuntu-latest" in self._yaml_text()

    def test_python_version_311(self):
        assert '3.11' in self._yaml_text()

    def test_lint_step_present(self):
        assert "ruff check" in self._yaml_text()

    def test_test_step_present(self):
        assert "pytest" in self._yaml_text()

    def test_install_step_present(self):
        assert "pip install" in self._yaml_text()


class TestCIWorkflowYAMLParsed:
    """Parse ci.yml as structured YAML and assert on the object graph.

    These complement the string-matching tests above with structural checks
    that survive whitespace/formatting changes.
    """

    def _parsed(self) -> dict:
        import yaml  # PyYAML is always available in the dev venv

        path = ROOT / ".github" / "workflows" / "ci.yml"
        with open(path) as fh:
            return yaml.safe_load(fh)

    def _steps(self) -> list:
        return self._parsed()["jobs"]["test"]["steps"]

    def test_on_push_trigger_present(self):
        """The workflow triggers on push events.

        PyYAML parses the bare `on:` key as boolean True (YAML 1.1 compat).
        """
        parsed = self._parsed()
        triggers = parsed.get("on") or parsed.get(True)  # handle both representations
        assert triggers is not None and "push" in triggers

    def test_on_pull_request_trigger_present(self):
        """The workflow triggers on pull_request events."""
        parsed = self._parsed()
        triggers = parsed.get("on") or parsed.get(True)
        assert triggers is not None and "pull_request" in triggers

    def test_steps_contain_ruff_check(self):
        """At least one step runs `ruff check`."""
        run_cmds = [s.get("run", "") for s in self._steps()]
        assert any("ruff check" in cmd for cmd in run_cmds)

    def test_steps_contain_pytest(self):
        """At least one step runs `pytest`."""
        run_cmds = [s.get("run", "") for s in self._steps()]
        assert any("pytest" in cmd for cmd in run_cmds)

    def test_python_version_is_311(self):
        """The setup-python step pins Python 3.11."""
        for step in self._steps():
            with_block = step.get("with", {})
            if "python-version" in with_block:
                assert str(with_block["python-version"]) == "3.11"
                return
        raise AssertionError("No step sets python-version")
