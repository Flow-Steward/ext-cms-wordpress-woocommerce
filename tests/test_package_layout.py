"""Bundle layout, the subprocess entrypoint, and the health command."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml
from health import check_health
from runtime.catalog import REST_OPERATIONS

BUNDLE_ROOT = Path(__file__).resolve().parents[1]


def _run_entrypoint(payload: object) -> tuple[int, dict]:
    process = subprocess.run(
        [sys.executable, "main.py"],
        cwd=str(BUNDLE_ROOT),
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        check=False,
    )
    return process.returncode, json.loads(process.stdout.decode("utf-8"))


def test_every_task_owned_file_lives_inside_this_bundle() -> None:
    expected_top_level = {
        "README.md",
        "CHANGELOG.md",
        "__init__.py",
        "contracts",
        "dev-wheels",
        "dispatcher.py",
        "health.py",
        "main.py",
        "requirements-dev.txt",
        "runtime",
        "tests",
        "ui",
    }
    actual = {
        entry.name
        for entry in BUNDLE_ROOT.iterdir()
        if not entry.name.startswith(".") and entry.name != "__pycache__"
    }
    assert actual - {"extension.yaml"} == expected_top_level
    assert (BUNDLE_ROOT / "extension.yaml").is_file()


def test_the_health_command_reports_the_declared_surface() -> None:
    health = check_health()
    assert health["extension_id"] == "flowsteward.wordpress-woocommerce"
    assert health["ok"] is True
    assert health["status"] == "healthy"
    assert health["declared_operations"] == len(REST_OPERATIONS) + 1


def test_the_health_command_runs_as_a_subprocess() -> None:
    process = subprocess.run(
        [sys.executable, "health.py"],
        cwd=str(BUNDLE_ROOT),
        capture_output=True,
        check=True,
    )
    assert json.loads(process.stdout.decode("utf-8"))["ok"] is True


def test_the_entrypoint_refuses_an_unknown_operation() -> None:
    code, response = _run_entrypoint(
        {"mode": "action", "action": {"action_id": "wp_delete_post", "input": {}}}
    )
    assert code == 2
    assert response["ok"] is False
    assert response["error_code"] == "unsupported_operation"


def test_the_entrypoint_refuses_a_non_json_request() -> None:
    process = subprocess.run(
        [sys.executable, "main.py"],
        cwd=str(BUNDLE_ROOT),
        input=b"{not json",
        capture_output=True,
        check=False,
    )
    response = json.loads(process.stdout.decode("utf-8"))
    assert response["ok"] is False
    assert response["error_code"] == "invalid_payload"


def test_the_entrypoint_and_health_commands_match_the_manifest() -> None:
    manifest = yaml.safe_load((BUNDLE_ROOT / "extension.yaml").read_text())
    assert manifest["entrypoint"]["command"] == ["python3", "main.py"]
    assert manifest["health"]["command"] == ["python3", "health.py"]
    assert manifest["python_requirements"] == []


def test_no_generated_contract_is_missing_from_the_bundle() -> None:
    for relative in (
        "contracts/rest_coverage.yaml",
        "contracts/connection_types.yaml",
        "contracts/operation_manifest.yaml",
        "contracts/step_ui_manifest.yaml",
        "contracts/artifact_policies.yaml",
        "contracts/rest_reference.yaml",
        "runtime/parameters.py",
        "tests/reference/refresh_reference.py",
        "tests/reference/build_parameters.py",
        "ui/ui_manifest.yaml",
        "ui/actions/actions.yaml",
        "ui/pages/setup-guide.yaml",
        "ui/pages/connection.yaml",
        "ui/pages/wordpress-api.yaml",
        "ui/pages/woocommerce-api.yaml",
        "ui/components/wordpress_connection_form.yaml",
    ):
        assert (BUNDLE_ROOT / relative).is_file(), relative
