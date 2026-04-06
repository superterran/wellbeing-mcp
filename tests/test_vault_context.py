"""Tests for vault context readers — coach agent and skill metadata."""

from unittest.mock import patch

import pytest


@pytest.fixture()
def vault_context(tmp_path):
    """Patch vault context paths to a temp directory."""
    import wellbeing_mcp.vault as vault_module

    context_dir = tmp_path / "Context"
    context_dir.mkdir()
    coach_path = context_dir / "Coach Agent.md"
    skill_dir = context_dir / "skills" / "wellbeing"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"

    with (
        patch.object(vault_module, "COACH_AGENT_PATH", coach_path),
        patch.object(vault_module, "WELLBEING_SKILL_PATH", skill_path),
    ):
        yield vault_module, coach_path, skill_path


def test_read_coach_agent_returns_empty_when_missing(vault_context):
    vault_module, _coach_path, _skill_path = vault_context
    result = vault_module.read_coach_agent()
    assert result == ""


def test_read_coach_agent_reads_file(vault_context):
    vault_module, coach_path, _skill_path = vault_context
    coach_path.write_text("# Coach Agent\n\nBe supportive, not preachy.")
    result = vault_module.read_coach_agent()
    assert "Coach Agent" in result
    assert "supportive" in result


def test_read_skill_metadata_returns_none_when_missing(vault_context):
    vault_module, _coach_path, _skill_path = vault_context
    result = vault_module.read_skill_metadata()
    assert result is None


def test_read_skill_metadata_reads_file(vault_context):
    vault_module, _coach_path, skill_path = vault_context
    skill_path.write_text("Always read wellbeing://current first.")
    result = vault_module.read_skill_metadata()
    assert result is not None
    assert "wellbeing://current" in result
