"""The shipped contract conforms to the committed snapshot of the official docs.

``contracts/rest_reference.yaml`` is produced by ``tests/reference/refresh_reference.py``
straight from developer.wordpress.org and developer.woocommerce.com. These tests
replay it offline and prove three things:

* every documented route appears in the coverage inventory, supported or
  excluded with a reason;
* no route is claimed as supported that the documentation does not publish;
* every typed parameter table is exactly what the builder derives from the
  snapshot, so the types were read from the docs rather than invented.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml
from runtime.catalog import REST_OPERATIONS_BY_ID
from runtime.coverage import STATUS_SUPPORTED, coverage_rows

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = BUNDLE_ROOT / "contracts" / "rest_reference.yaml"
BUILDER = BUNDLE_ROOT / "tests" / "reference" / "build_parameters.py"

#: Routes the extension publishes that no reference page lists as one of its own
#: endpoints. Each is a deliberate inventory entry rather than a claimed route.
SYNTHETIC_ROWS = {
    ("POST", "/wp-json/batch/v1"),
    ("POST", "/wp-json/wc/v3/<resource>/batch#delete"),
}


def _snapshot() -> dict:
    return yaml.safe_load(SNAPSHOT.read_text(encoding="utf-8"))


def _normalise(route: str) -> str:
    return re.sub(r"[<{][^>}]*[>}]", "{}", route.replace("/wp-json", ""))


def _documented_routes() -> set[tuple[str, str]]:
    return {
        (method, _normalise(route))
        for page in _snapshot()["pages"]
        for method, route in page["routes"]
    }


def _inventory_routes() -> set[tuple[str, str]]:
    return {
        (row.method, _normalise(row.route_pattern))
        for row in coverage_rows()
        if row.method and (row.method, row.route_pattern) not in SYNTHETIC_ROWS
    }


def test_the_snapshot_covers_every_official_reference_page() -> None:
    snapshot = _snapshot()
    pages = {(page["provider"], page["slug"]) for page in snapshot["pages"]}
    assert len([p for p in pages if p[0] == "wordpress"]) == 30
    assert len([p for p in pages if p[0] == "woocommerce"]) == 30
    for page in snapshot["pages"]:
        assert page["url"].startswith("https://developer.")
        assert page["routes"], page["slug"]


def test_every_documented_route_appears_in_the_coverage_inventory() -> None:
    missing = sorted(_documented_routes() - _inventory_routes())
    assert missing == [], f"documented but absent from rest_coverage.yaml: {missing}"


def test_no_supported_route_is_absent_from_the_documentation() -> None:
    documented = _documented_routes()
    claimed = {
        (row.method, _normalise(row.route_pattern))
        for row in coverage_rows()
        if row.coverage_status == STATUS_SUPPORTED
    }
    invented = sorted(claimed - documented)
    assert invented == [], f"claimed as supported but undocumented: {invented}"


def test_every_supported_route_resolves_to_a_registered_operation() -> None:
    for row in coverage_rows():
        if row.coverage_status != STATUS_SUPPORTED:
            continue
        operation = REST_OPERATIONS_BY_ID[row.operation_id]
        assert operation.route_pattern == row.route_pattern
        assert operation.method == row.method


def test_the_documentation_snapshot_names_the_page_each_operation_cites() -> None:
    pages = {(page["provider"], page["slug"]) for page in _snapshot()["pages"]}
    for operation in REST_OPERATIONS_BY_ID.values():
        assert (operation.provider, operation.doc_slug) in pages, operation.operation_id


def test_the_typed_tables_are_exactly_what_the_snapshot_yields() -> None:
    """runtime/parameters.py is derivable from the committed documentation."""
    result = subprocess.run(
        [sys.executable, str(BUILDER), "--check"],
        cwd=str(BUNDLE_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_parameter_generator_keeps_shared_model_references_named() -> None:
    import build_parameters

    tables = build_parameters.build()
    rendered = build_parameters.render(tables)
    namespace: dict[str, object] = {}
    exec(compile(rendered, str(BUILDER), "exec"), namespace)

    assert namespace["QUERY_FIELDS"] == tables["query"]
    assert namespace["BODY_FIELDS"] == tables["body"]
    for value in build_parameters._shared_model_literals(tables):
        assert rendered.count(repr(value)) == 1


def test_every_typed_field_traces_to_a_documented_parameter() -> None:
    from runtime.parameters import BODY_FIELDS, QUERY_FIELDS

    documented: dict[str, set[str]] = {}
    for page in _snapshot()["pages"]:
        names = documented.setdefault(f"{page['provider']}:{page['slug']}", set())
        for section in page.get("sections", []):
            names.update(field["name"] for field in section["fields"])
        for table in page.get("properties", []):
            names.update(field["name"] for field in table["fields"])

    # WooCommerce documents these action payloads in its request examples only.
    example_sourced = {"template_id", "email", "force_email_update"}

    for operation in REST_OPERATIONS_BY_ID.values():
        key = f"{operation.provider}:{operation.doc_slug}"
        declared = {
            field["name"]
            for field in QUERY_FIELDS[operation.operation_id] + BODY_FIELDS[operation.operation_id]
        }
        unsourced = declared - documented[key] - example_sourced
        assert unsourced == set(), (operation.operation_id, sorted(unsourced))


def test_the_refresh_script_is_shipped_and_offline_safe() -> None:
    script = (BUNDLE_ROOT / "tests" / "reference" / "refresh_reference.py").read_text()
    assert "--check" in script
    assert "developer.wordpress.org" in script
    assert "developer.woocommerce.com" in script
    # The tests never reach the network; only the refresh script does.
    network_calls = ("urlopen(", "urllib.request", "requests.get", "socket.create_connection")
    for path in sorted((BUNDLE_ROOT / "tests").glob("test_*.py")):
        body = "\n".join(
            line for line in path.read_text().splitlines() if "network_calls" not in line
        )
        for call in network_calls:
            assert call not in body, (path.name, call)
