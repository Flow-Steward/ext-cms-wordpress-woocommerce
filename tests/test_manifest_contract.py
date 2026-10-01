"""Exact parity between the coverage inventory, the manifests, the UI, and the runtime."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import yaml
from dispatcher import OPERATION_REGISTRY
from runtime.catalog import (
    EFFECT_SHAPES,
    REST_OPERATIONS,
    REST_OPERATIONS_BY_ID,
    SUPPORTED_METHODS,
    SUPPORTED_NAMESPACES,
    TEST_CONNECTION_OPERATION_ID,
    VALIDATE_SETTINGS_OPERATION_ID,
)
from runtime.catalog_export import EXPORT_PRODUCTS_OPERATION_ID
from runtime.connection import CONNECTION_TYPE_ID
from runtime.descriptions import OPERATION_DOCS, catalog_description
from runtime.errors import SAFE_ERROR_CODES
from runtime.io_shapes import (
    action_parameters,
    field_label,
    operation_inputs,
    operation_outputs,
    result_field_names,
    step_form_fields,
)
from runtime.operations import TEST_CONNECTION_RESULT_FIELDS

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_IDS = set(REST_OPERATIONS_BY_ID) | {
    TEST_CONNECTION_OPERATION_ID,
    VALIDATE_SETTINGS_OPERATION_ID,
    EXPORT_PRODUCTS_OPERATION_ID,
}


def _yaml(relative: str) -> dict:
    return yaml.safe_load((BUNDLE_ROOT / relative).read_text())


def test_every_surface_declares_exactly_the_closed_registry() -> None:
    operations = {
        row["operation_id"]: row for row in _yaml("contracts/operation_manifest.yaml")["operations"]
    }
    actions = {row["action_id"]: row for row in _yaml("ui/actions/actions.yaml")["actions"]}
    forms = {row["operation_id"]: row for row in _yaml("contracts/step_ui_manifest.yaml")["forms"]}
    coverage = _yaml("contracts/rest_coverage.yaml")["coverage"]
    supported = {row["operation_id"] for row in coverage if row["coverage_status"] == "supported"}

    assert set(operations) == EXPECTED_IDS
    assert set(actions) == EXPECTED_IDS
    assert set(forms) == EXPECTED_IDS
    assert set(OPERATION_REGISTRY) == EXPECTED_IDS
    assert supported == set(REST_OPERATIONS_BY_ID)


def test_each_rest_operation_matches_its_manifest_action_and_form() -> None:
    operations = {
        row["operation_id"]: row for row in _yaml("contracts/operation_manifest.yaml")["operations"]
    }
    actions = {row["action_id"]: row for row in _yaml("ui/actions/actions.yaml")["actions"]}
    forms = {row["operation_id"]: row for row in _yaml("contracts/step_ui_manifest.yaml")["forms"]}

    for row in REST_OPERATIONS:
        operation = operations[row.operation_id]
        action = actions[row.operation_id]
        form = forms[row.operation_id]

        assert operation["connection_type_ids"] == [CONNECTION_TYPE_ID]
        assert operation["operation_kind"] == row.operation_kind
        doc = OPERATION_DOCS[row.operation_id]
        assert operation["display_name"] == doc.title == action["title"]
        assert form["title"] == row.display_name
        assert operation["description"] == doc.summary
        # The builder shows only a title and a description, so the action's
        # description is the one place the endpoint can appear.
        assert action["description"] == catalog_description(doc)
        assert action["description"].endswith(f"Calls {doc.endpoint}.")
        assert operation["inputs"] == operation_inputs(row)
        assert operation["outputs"] == operation_outputs(row)
        assert operation["result_fields"] == [f"result.{name}" for name in result_field_names(row)]
        assert action["parameters"] == action_parameters(row)
        assert action["result_fields"] == result_field_names(row)
        assert action["error_codes"] == operation["error_codes"]
        assert action["handler"] == {"mode": "extension"}
        assert action["mutates_platform"] is row.has_external_effect
        assert form["fields"] == step_form_fields(row)


def test_test_connection_surfaces_agree() -> None:
    operations = {
        row["operation_id"]: row for row in _yaml("contracts/operation_manifest.yaml")["operations"]
    }
    actions = {row["action_id"]: row for row in _yaml("ui/actions/actions.yaml")["actions"]}
    operation = operations[TEST_CONNECTION_OPERATION_ID]
    action = actions[TEST_CONNECTION_OPERATION_ID]

    assert operation["connection_type_ids"] == [CONNECTION_TYPE_ID]
    assert [field["name"] for field in operation["inputs"]] == ["connection_ref"]
    assert [field["name"] for field in operation["outputs"]] == list(TEST_CONNECTION_RESULT_FIELDS)
    assert action["result_fields"] == list(TEST_CONNECTION_RESULT_FIELDS)
    assert action["error_codes"] == operation["error_codes"]
    assert action["mutates_platform"] is False


def test_external_effects_cover_every_mutation_and_nothing_else() -> None:
    manifest = _yaml("extension.yaml")
    declared = {row["operation_id"] for row in manifest["external_effects"]}
    expected = {row.operation_id for row in REST_OPERATIONS if row.has_external_effect}
    read_only = {row.operation_id for row in REST_OPERATIONS if not row.has_external_effect}

    assert declared == expected
    assert declared & read_only == set()
    assert TEST_CONNECTION_OPERATION_ID not in declared
    for row in manifest["external_effects"]:
        assert row["idempotency"] == "required"
        assert row["test_mode_behavior"] == "suppress"
        assert row["channel"] in {"wordpress_rest", "woocommerce_rest"}
        assert REST_OPERATIONS_BY_ID[row["operation_id"]].shape in EFFECT_SHAPES


def test_declared_error_codes_are_exactly_the_safe_vocabulary() -> None:
    operations = _yaml("contracts/operation_manifest.yaml")["operations"]
    declared = set().union(*(set(row["error_codes"]) for row in operations))
    assert declared == set(SAFE_ERROR_CODES)
    for row in operations:
        assert list(dict.fromkeys(row["error_codes"])) == row["error_codes"]


def test_manifest_declares_the_free_first_party_identity() -> None:
    manifest = _yaml("extension.yaml")
    assert manifest["extension_id"] == "flowsteward.wordpress-woocommerce"
    assert manifest["display_name"] == "WordPress & WooCommerce"
    assert manifest["version"] == "1.0.0"
    assert manifest["billing_mode"] == "free"
    assert manifest["vendor"]["name"] == "Flow Steward"
    assert manifest["account_scope"]["scope_type"] == "project"
    assert set(manifest["required_scopes"]) == {
        "extension:invoke",
        "artifact:read",
        "artifact:write",
    }


def test_manifest_bundles_no_global_or_event_driven_artifacts() -> None:
    manifest = _yaml("extension.yaml")
    for forbidden in (
        "workflows",
        "agents",
        "skills",
        "datasets",
        "saved_queries",
        "guardrails",
        "triggers",
        "callbacks",
        "scheduled_jobs",
        "event_subscriptions",
        "machine_auth",
        "query_manifest",
        "dependencies",
    ):
        assert forbidden not in manifest
    contract = manifest["runtime"]["extension_contract_v2"]
    assert set(contract) == {
        "connection_types",
        "operation_manifest",
        "step_ui_manifest",
        "artifact_policies",
    }


def test_connection_type_declares_one_project_scoped_site() -> None:
    connection = _yaml("contracts/connection_types.yaml")["connection_types"]
    assert len(connection) == 1
    row = connection[0]
    config = row["config_schema"]
    secrets = row["secret_schema"]

    assert row["connection_type_id"] == CONNECTION_TYPE_ID
    assert row["auth"] == {"type": "static_secret"}
    assert set(config["properties"]) == {"site_url", "wordpress_username"}
    assert set(config["required"]) == {"site_url", "wordpress_username"}
    assert set(secrets["properties"]) == {
        "wordpress_application_password",
        "woocommerce_consumer_key",
        "woocommerce_consumer_secret",
    }
    assert secrets["required"] == ["wordpress_application_password"]
    assert secrets["dependentRequired"] == {
        "woocommerce_consumer_key": ["woocommerce_consumer_secret"],
        "woocommerce_consumer_secret": ["woocommerce_consumer_key"],
    }
    assert config["additionalProperties"] is False
    assert secrets["additionalProperties"] is False


def test_artifact_grants_cover_media_input_and_complete_product_export() -> None:
    policies = _yaml("contracts/artifact_policies.yaml")["artifact_policies"]
    assert [row["operation_id"] for row in policies] == [
        "wp_create_media",
        EXPORT_PRODUCTS_OPERATION_ID,
    ]
    assert set(policies[0]) == {"operation_id", "inputs"}
    artifact_input = policies[0]["inputs"][0]
    assert artifact_input["binding_key"] == "wordpress_media_artifact"
    assert artifact_input["from_input"] == "artifact_handle"
    assert artifact_input.get("required", True) is True
    export_output = policies[1]["outputs"][0]
    assert export_output["binding_key"] == "woocommerce_products_export"
    assert export_output["content_type"] == "application/x-ndjson"
    assert export_output["max_size_bytes"] == 200 * 1024 * 1024
    assert export_output["max_size_env"] == "FS_EXTENSION_ARTIFACT_MAX_BYTES"
    assert export_output["retention_class"] == "run_window"
    assert _yaml("extension.yaml")["artifact_policies"] == policies


def test_ui_declares_exactly_the_five_extension_owned_pages() -> None:
    manifest = _yaml("ui/ui_manifest.yaml")
    pages = [_yaml(f"ui/{row['ref']}") for row in manifest["pages"]]
    assert [page["page_id"] for page in pages] == [
        "setup-guide",
        "connection",
        "wordpress-api",
        "woocommerce-api",
        "changelog",
    ]
    assert [page["title"] for page in pages] == [
        "Setup Guide",
        "Connection",
        "WordPress API",
        "WooCommerce API",
        "Changelog",
    ]


def test_extension_python_imports_no_core_or_third_party_runtime() -> None:
    forbidden_roots = {"core", "requests", "httpx", "aiohttp", "wordpress", "woocommerce"}
    for path in sorted(BUNDLE_ROOT.rglob("*.py")):
        if "dev-wheels" in path.parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {(node.module or "").split(".")[0]}
            else:
                continue
            assert not names & forbidden_roots, f"forbidden dependency in {path}"


def test_bundle_ships_no_forbidden_json_contract_files() -> None:
    for pattern in ("extension.json", "ui/ui_manifest.json", "ui/actions/actions.json"):
        assert not (BUNDLE_ROOT / pattern).exists()
    assert not list((BUNDLE_ROOT / "contracts").glob("*.json"))
    assert not list((BUNDLE_ROOT / "ui/pages").glob("*.json"))


def test_registry_routes_stay_inside_the_two_supported_namespaces() -> None:
    for row in REST_OPERATIONS:
        assert row.namespace in SUPPORTED_NAMESPACES
        assert row.method in SUPPORTED_METHODS
        assert row.route_pattern.startswith(f"/wp-json/{row.namespace}/")


def test_the_published_contracts_are_rebuilt_from_the_runtime_registry() -> None:
    """The four contract files are projections, so they must never be hand-edited.

    ``build_contracts.py --check`` re-renders each one from the registry and
    fails if the committed bytes differ, which is what keeps the manifests, the
    coverage inventory and the builder actions saying the same thing as the code.
    """
    builder = Path(__file__).resolve().parents[1] / "tests" / "reference" / "build_contracts.py"
    result = subprocess.run(
        [sys.executable, str(builder), "--check"],
        cwd=str(builder.parents[2]),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_every_step_form_field_carries_a_readable_label() -> None:
    """The builder falls back to the wire name when a field has no label.

    That is what put `featured_media` and `date_gmt` in front of workflow
    authors, so every field must publish a label, and no label may still read
    as an identifier.
    """
    forms = _yaml("contracts/step_ui_manifest.yaml")["forms"]
    assert forms
    for form in forms:
        for field in form["fields"]:
            label = field.get("label", "")
            assert label, f"{form['operation_id']}.{field['name']} has no label"
            assert "_" not in label, f"{form['operation_id']}.{field['name']} shows {label}"
            assert label[0].isupper(), f"{form['operation_id']}.{field['name']} shows {label}"


def test_a_field_label_keeps_the_acronyms_upright() -> None:
    assert field_label("parent_id") == "Parent ID"
    assert field_label("date_gmt") == "Date GMT"
    assert field_label("sku") == "SKU"
    assert field_label("featured_media") == "Featured media"
    assert field_label("_fields") == "Fields"
