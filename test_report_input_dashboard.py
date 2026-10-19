"""
Unit tests for the pure, non-GUI logic in report_input_dashboard.py:
date validation, local credential loading, and CLI command construction.
Tkinter/PyQt widgets are not instantiated here.
"""
import json
import os

import pytest

import report_input_dashboard as dash


# ---------------------------------------------------------------------------
# is_valid_date
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-08-17", True),
        ("2026-13-01", False),  # invalid month
        ("2026-02-30", False),  # invalid day
        ("17-08-2026", False),  # wrong format
        ("", False),
        ("not-a-date", False),
    ],
)
def test_is_valid_date(value, expected):
    assert dash.is_valid_date(value) == expected


def test_is_valid_date_handles_none_without_crashing():
    """Regression: DATE_PATTERN.match(None) used to raise TypeError."""
    assert dash.is_valid_date(None) is False


def test_is_valid_date_handles_non_string_without_crashing():
    assert dash.is_valid_date(20260817) is False


# ---------------------------------------------------------------------------
# is_credential_value
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        ("real-token-value", True),
        ("your-email@example.com", False),
        ("paste-your-token-here", False),
        ("changeme", False),
        ("replace-me", False),
        ("", False),
        (None, False),
    ],
)
def test_is_credential_value(value, expected):
    assert dash.is_credential_value(value) == expected


# ---------------------------------------------------------------------------
# load_local_credentials
# ---------------------------------------------------------------------------

@pytest.fixture
def patched_credential_paths(tmp_path, monkeypatch):
    json_path = tmp_path / "credentials.json"
    text_path = tmp_path / "credentials.txt"
    monkeypatch.setattr(dash, "LOCAL_CREDENTIALS_FILE", str(json_path))
    monkeypatch.setattr(dash, "LOCAL_CREDENTIALS_TEXT_FILE", str(text_path))
    for name in ("JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_AUTH_MODE", "TEST_GUIDE_TOKEN", "TEST_GUIDE_AUTH_KEY"):
        monkeypatch.delenv(name, raising=False)
    return json_path, text_path


def test_load_local_credentials_reads_json(patched_credential_paths, monkeypatch):
    json_path, _ = patched_credential_paths
    json_path.write_text(
        json.dumps({"jira": {"email": "user@example.com", "api_token": "real-token"}}),
        encoding="utf-8",
    )

    dash.load_local_credentials()

    assert os.environ["JIRA_EMAIL"] == "user@example.com"
    assert os.environ["JIRA_API_TOKEN"] == "real-token"


def test_load_local_credentials_skips_placeholder_values(patched_credential_paths):
    json_path, _ = patched_credential_paths
    json_path.write_text(
        json.dumps({"jira": {"email": "your-email@example.com", "api_token": "changeme"}}),
        encoding="utf-8",
    )

    dash.load_local_credentials()

    assert "JIRA_EMAIL" not in os.environ
    assert "JIRA_API_TOKEN" not in os.environ


def test_load_local_credentials_does_not_overwrite_existing_env(patched_credential_paths, monkeypatch):
    json_path, _ = patched_credential_paths
    json_path.write_text(
        json.dumps({"jira": {"api_token": "from-file"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_API_TOKEN", "from-env")

    dash.load_local_credentials()

    assert os.environ["JIRA_API_TOKEN"] == "from-env"


def test_load_local_credentials_missing_files_do_not_crash(patched_credential_paths):
    dash.load_local_credentials()  # neither file exists; should not raise


def test_load_local_credentials_reads_text_fallback(patched_credential_paths):
    _, text_path = patched_credential_paths
    text_path.write_text(
        "# comment\nJIRA_API_TOKEN=text-token\nJUNK_LINE\n",
        encoding="utf-8",
    )

    dash.load_local_credentials()

    assert os.environ["JIRA_API_TOKEN"] == "text-token"


def test_load_local_credentials_handles_malformed_json(patched_credential_paths):
    json_path, _ = patched_credential_paths
    json_path.write_text("{not valid json", encoding="utf-8")

    dash.load_local_credentials()  # should not raise


# ---------------------------------------------------------------------------
# resolve_report_interpreter
# ---------------------------------------------------------------------------

def test_resolve_report_interpreter_prefers_venv_python(tmp_path):
    script_path = tmp_path / "test_execution_report.py"
    script_path.write_text("", encoding="utf-8")
    venv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")

    assert dash.resolve_report_interpreter(str(script_path)) == str(venv_python)


def test_resolve_report_interpreter_falls_back_to_sys_executable(tmp_path):
    import sys

    script_path = tmp_path / "test_execution_report.py"
    script_path.write_text("", encoding="utf-8")

    assert dash.resolve_report_interpreter(str(script_path)) == sys.executable


# ---------------------------------------------------------------------------
# build_command
# ---------------------------------------------------------------------------

def _base_command_args(**overrides):
    args = dict(
        script_path="report.py",
        start_date="2026-08-17",
        end_date="2026-08-23",
        test_projects="All",
        domain="All",
        cycle_type="both",
        variant="All",
        defect_projects="All",
        defect_domain="All",
        defect_assigned_ecu="All",
        closure_projects="All",
        closure_team="All",
        resolution_start_date="2026-08-17",
        resolution_end_date="2026-08-23",
    )
    args.update(overrides)
    return args


def test_build_command_includes_required_dates_and_cycle_type():
    cmd = dash.build_command(**_base_command_args())
    assert "--start-date" in cmd
    assert "2026-08-17" in cmd
    assert "--cycle-type" in cmd
    assert "both" in cmd


def test_build_command_omits_all_value_filters():
    cmd = dash.build_command(**_base_command_args())
    assert "--projects" not in cmd
    assert "--domain" not in cmd
    assert "--variant" not in cmd
    assert "--defect-projects" not in cmd


def test_build_command_includes_specific_filters():
    cmd = dash.build_command(**_base_command_args(domain="Telematics", test_projects="ABPI"))
    assert "--domain" in cmd
    assert "Telematics" in cmd
    assert "--projects" in cmd
    assert "ABPI" in cmd


def test_build_command_omits_invalid_resolution_dates():
    cmd = dash.build_command(**_base_command_args(resolution_start_date="bad-date", resolution_end_date=""))
    assert "--resolution-start-date" not in cmd
    assert "--resolution-end-date" not in cmd


def test_build_command_includes_valid_resolution_dates():
    cmd = dash.build_command(**_base_command_args())
    assert "--resolution-start-date" in cmd
    assert "--resolution-end-date" in cmd


def test_build_command_report_scopes_and_adhoc_domains():
    cmd = dash.build_command(
        **_base_command_args(report_scopes="test,adhoc", adhoc_domains="Telematics")
    )
    assert "--report-scopes" in cmd
    assert "test,adhoc" in cmd
    assert "--adhoc-domains" in cmd
    assert "Telematics" in cmd


def test_build_command_omits_default_adhoc_domain_all():
    cmd = dash.build_command(**_base_command_args(adhoc_domains="All"))
    assert "--adhoc-domains" not in cmd
