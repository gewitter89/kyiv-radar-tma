"""Read-only monitor must run after a successful Pages publish and daily."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "public-health.yml"


def test_live_checks_run_after_successful_pages_publish_without_secrets():
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert 'workflows: ["pages build and deployment"]' in raw
    assert "types: [completed]" in raw
    assert "branches: [main]" in raw
    assert "github.event.workflow_run.conclusion == 'success'" in raw
    assert "contents: read" in raw
    assert "run: python scripts/monitor_public_health.py" in raw
    for forbidden in ("secrets.", "contents: write", "pull_request_target:",
                      "deploy-pages", "sudo ", "DIM_RIA_API_KEY", "BOT_TOKEN"):
        assert forbidden not in raw


def test_daily_and_manual_readonly_paths_preserved():
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in raw
    assert "schedule:" in raw
    assert "17 06 * * *" in raw
