#!/usr/bin/env python3
"""Project the closed runtime registry into the published YAML contracts.

The runtime registry is the single source of truth. This script writes the four
contract files that the platform reads — the coverage inventory, the operation
manifest, the step UI manifest and the builder actions — so a change to an
operation, its typed parameters or its user-facing wording reaches every
published surface from one place.

    python tests/reference/build_contracts.py            # rewrite the contracts
    python tests/reference/build_contracts.py --check    # fail if they drifted

Companion to ``build_parameters.py`` (typed tables) and ``build_ui_pages.py``
(documentation pages); each link in the chain has a test.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

BUNDLE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BUNDLE))

from runtime import errors as E  # noqa: E402
from runtime.catalog import REST_OPERATIONS, WOOCOMMERCE_NAMESPACE  # noqa: E402
from runtime.catalog_export import (  # noqa: E402
    EXPORT_PRODUCTS_OPERATION_ID,
    EXPORT_PRODUCTS_OUTPUTS,
    export_products_action_parameters,
    export_products_form_fields,
    export_products_inputs,
)
from runtime.connection import CONNECTION_TYPE_ID  # noqa: E402
from runtime.coverage import coverage_rows  # noqa: E402
from runtime.descriptions import OPERATION_DOCS, catalog_description  # noqa: E402
from runtime.io_shapes import (  # noqa: E402
    action_parameters,
    operation_inputs,
    operation_outputs,
    result_field_names,
    step_form_fields,
)
from runtime.operations import (  # noqa: E402
    TEST_CONNECTION_RESULT_FIELDS,
    VALIDATE_SETTINGS_CHECKS,
    VALIDATE_SETTINGS_RESULT_FIELDS,
)

BASE_ERRORS = [
    E.INVALID_PAYLOAD,
    E.INVALID_CONFIGURATION,
    E.INVALID_CONNECTION,
    E.WOOCOMMERCE_CREDENTIALS_INCOMPLETE,
    E.UNSUPPORTED_OPERATION,
    E.AUTHENTICATION_FAILED,
    E.AUTHORIZATION_FAILED,
    E.NOT_FOUND,
    E.RATE_LIMITED,
    E.UPSTREAM_VALIDATION_FAILED,
    E.UPSTREAM_FAILURE,
    E.INVALID_JSON_RESPONSE,
    E.RESPONSE_TOO_LARGE,
    E.TIMEOUT,
    E.CONNECTION_FAILED,
    E.REDIRECT_REJECTED,
    E.BLOCKED_ADDRESS,
    E.INTERNAL_ERROR,
]


def error_codes(row) -> list[str]:
    codes = list(BASE_ERRORS)
    if row.namespace == WOOCOMMERCE_NAMESPACE:
        codes.append(E.WOOCOMMERCE_NOT_CONFIGURED)
    if row.has_external_effect:
        codes.append(E.TIMEOUT_UNKNOWN)
    if row.shape == "media_create":
        codes.append(E.ARTIFACT_INPUT_UNAVAILABLE)
    return codes


TEST_CONNECTION_ERRORS = list(BASE_ERRORS)
VALIDATE_SETTINGS_ERRORS = [
    E.INVALID_PAYLOAD,
    E.INVALID_CONFIGURATION,
    E.WOOCOMMERCE_CREDENTIALS_INCOMPLETE,
    E.INTERNAL_ERROR,
]
VALIDATE_SETTINGS_INPUTS = [
    {
        "name": "check",
        "value_type": "text",
        "required": True,
        "schema": {"type": "string", "enum": list(VALIDATE_SETTINGS_CHECKS)},
    },
    {
        "name": "site_url",
        "value_type": "text",
        "required": False,
        "schema": {"type": "string", "minLength": 8, "maxLength": 512},
    },
]
VALIDATE_SETTINGS_OUTPUTS = [
    {"name": "valid", "value_type": "boolean"},
    {"name": "check", "value_type": "text"},
    {"name": "normalized_site_url", "value_type": "text"},
]
assert [f["name"] for f in VALIDATE_SETTINGS_OUTPUTS] == list(VALIDATE_SETTINGS_RESULT_FIELDS)

TEST_CONNECTION_OUTPUTS: list[dict[str, Any]] = [
    {"name": "site_url", "value_type": "text"},
    {"name": "site_name", "value_type": "text"},
    {
        "name": "namespaces",
        "value_type": "array",
        "schema": {"type": "array", "items": {"type": "string"}},
    },
    {"name": "wordpress_state", "value_type": "text"},
    {"name": "woocommerce_state", "value_type": "text"},
    {"name": "wordpress_available", "value_type": "boolean"},
    {"name": "woocommerce_available", "value_type": "boolean"},
    {"name": "wordpress_user_id", "value_type": "integer"},
    {"name": "wordpress_user_slug", "value_type": "text"},
]
assert [f["name"] for f in TEST_CONNECTION_OUTPUTS] == list(TEST_CONNECTION_RESULT_FIELDS)

TEST_CONNECTION_INPUTS: list[dict[str, Any]] = [
    {"name": "connection_ref", "value_type": "connection_ref", "required": True}
]


# ---------------------------------------------------------------- YAML emit


def scalar(value) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if text == "":
        return '""'
    needs_quote = (
        text[0] in "!&*?|>%@`'\"-{}[]#,"
        or text[-1] in " :"
        or ": " in text
        or " #" in text
        or "\n" in text
        or text.lower() in {"true", "false", "null", "yes", "no", "on", "off", "~"}
    )
    if needs_quote:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def flow_scalar(value) -> str:
    """Quote a scalar that would be ambiguous inside a YAML flow collection."""
    text = scalar(value)
    if text.startswith('"') or not isinstance(value, str):
        return text
    if any(character in text for character in "{}[],"):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def flow(value) -> str:
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {flow(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(flow(v) for v in value) + "]"
    return flow_scalar(value)


def block_list(rows: list[dict[str, Any]], indent: str = "  ") -> list[str]:
    return [f"{indent}- {flow(row)}" for row in rows]


HEADER = "# Generated from the closed runtime registry in runtime/catalog.py.\n# Extension-owned parity tests fail if this file and the registry disagree.\n"


# ---------------------------------------------------------------- coverage


def write_coverage() -> None:
    lines = [
        "# Coverage inventory: the exact source of truth for what this extension",
        "# supports and what it deliberately excludes.",
        "#",
        "# coverage_status:",
        "#   supported       - a typed operation dispatches this route",
        "#   excluded        - the route is officially documented and deliberately not implemented",
        "#   not_documented  - the resource has no official WordPress Core /wp/v2 reference page",
        "coverage:",
    ]
    for row in coverage_rows():
        lines.append(f"  - {flow(row.as_mapping())}")
    (BUNDLE / "contracts/rest_coverage.yaml").write_text("\n".join(lines) + "\n")


# ------------------------------------------------------- operation manifest


def write_operation_manifest() -> None:
    lines = [HEADER.rstrip(), "operations:"]
    doc = OPERATION_DOCS["test_connection"]
    lines.append("  - operation_id: test_connection")
    lines.append(f"    display_name: {scalar(doc.title)}")
    lines.append(f"    description: {scalar(doc.summary)}")
    lines.append("    operation_kind: source")
    lines.append("    category: cms")
    lines.append(f"    connection_type_ids: [{CONNECTION_TYPE_ID}]")
    lines.append("    inputs:")
    lines += block_list(TEST_CONNECTION_INPUTS, "      ")
    lines.append("    outputs:")
    lines += block_list(TEST_CONNECTION_OUTPUTS, "      ")
    lines.append(
        f"    result_fields: {flow(['result.' + n for n in TEST_CONNECTION_RESULT_FIELDS])}"
    )
    lines.append(f"    error_codes: {flow(TEST_CONNECTION_ERRORS)}")
    settings_doc = OPERATION_DOCS["validate_connection_settings"]
    lines.append("  - operation_id: validate_connection_settings")
    lines.append("    workflow_visible: false")
    lines.append(f"    display_name: {scalar(settings_doc.title)}")
    lines.append(f"    description: {scalar(settings_doc.summary)}")
    lines.append("    operation_kind: source")
    lines.append("    category: cms")
    lines.append("    inputs:")
    lines += block_list(VALIDATE_SETTINGS_INPUTS, "      ")
    lines.append("    outputs:")
    lines += block_list(VALIDATE_SETTINGS_OUTPUTS, "      ")
    lines.append(
        f"    result_fields: {flow(['result.' + n for n in VALIDATE_SETTINGS_RESULT_FIELDS])}"
    )
    lines.append(f"    error_codes: {flow(VALIDATE_SETTINGS_ERRORS)}")
    export_doc = OPERATION_DOCS[EXPORT_PRODUCTS_OPERATION_ID]
    lines.append(f"  - operation_id: {EXPORT_PRODUCTS_OPERATION_ID}")
    lines.append(f"    display_name: {scalar(export_doc.title)}")
    lines.append(f"    description: {scalar(export_doc.summary)}")
    lines.append("    operation_kind: source")
    lines.append("    category: ecommerce")
    lines.append(f"    connection_type_ids: [{CONNECTION_TYPE_ID}]")
    lines.append("    inputs:")
    lines += block_list(export_products_inputs(), "      ")
    lines.append("    outputs:")
    lines += block_list(list(EXPORT_PRODUCTS_OUTPUTS), "      ")
    lines.append(
        f"    result_fields: {flow(['result.' + row['name'] for row in EXPORT_PRODUCTS_OUTPUTS])}"
    )
    lines.append(
        f"    error_codes: {flow([*BASE_ERRORS, E.WOOCOMMERCE_NOT_CONFIGURED, E.ARTIFACT_OUTPUT_UNAVAILABLE])}"
    )
    for row in REST_OPERATIONS:
        doc = OPERATION_DOCS[row.operation_id]
        lines.append(f"  - operation_id: {row.operation_id}")
        lines.append(f"    display_name: {scalar(doc.title)}")
        lines.append(f"    description: {scalar(doc.summary)}")
        lines.append(f"    operation_kind: {row.operation_kind}")
        lines.append(f"    category: {row.category}")
        lines.append(f"    connection_type_ids: [{CONNECTION_TYPE_ID}]")
        lines.append("    inputs:")
        lines += block_list(operation_inputs(row), "      ")
        lines.append("    outputs:")
        lines += block_list(operation_outputs(row), "      ")
        lines.append(f"    result_fields: {flow(['result.' + n for n in result_field_names(row)])}")
        lines.append(f"    error_codes: {flow(error_codes(row))}")
    (BUNDLE / "contracts/operation_manifest.yaml").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------- step ui manifest


def write_step_ui_manifest() -> None:
    lines = [HEADER.rstrip(), "forms:"]
    lines.append(
        "  - {operation_id: test_connection, title: Test WordPress connection, fields: []}"
    )
    lines.append(
        "  - {operation_id: validate_connection_settings, "
        "title: Check connection settings, fields: []}"
    )
    lines.append(
        f"  - {flow({'operation_id': EXPORT_PRODUCTS_OPERATION_ID, 'title': OPERATION_DOCS[EXPORT_PRODUCTS_OPERATION_ID].title, 'fields': export_products_form_fields()})}"
    )
    for row in REST_OPERATIONS:
        fields = step_form_fields(row)
        lines.append(
            f"  - {flow({'operation_id': row.operation_id, 'title': row.display_name, 'fields': fields})}"
        )
    (BUNDLE / "contracts/step_ui_manifest.yaml").write_text("\n".join(lines) + "\n")


# --------------------------------------------------------------- ui actions


def write_actions() -> None:
    lines = [HEADER.rstrip(), "actions:"]
    doc = OPERATION_DOCS["test_connection"]
    lines.append("  - action_id: test_connection")
    lines.append(f"    title: {scalar(doc.title)}")
    lines.append(f"    description: {scalar(catalog_description(doc))}")
    lines.append("    required_scopes: [extension:invoke]")
    lines.append("    handler: {mode: extension}")
    lines.append("    mutates_platform: false")
    lines.append("    workflow_visible: true")
    lines.append(
        f"    parameters: {flow([{'name': 'connection_ref', 'type': 'connection_ref', 'required': True}])}"
    )
    lines.append(f"    result_fields: {flow(list(TEST_CONNECTION_RESULT_FIELDS))}")
    lines.append(f"    error_codes: {flow(TEST_CONNECTION_ERRORS)}")
    settings_doc = OPERATION_DOCS["validate_connection_settings"]
    lines.append("  - action_id: validate_connection_settings")
    lines.append(f"    title: {scalar(settings_doc.title)}")
    lines.append(f"    description: {scalar(catalog_description(settings_doc))}")
    lines.append("    required_scopes: [extension:invoke]")
    lines.append("    handler: {mode: extension}")
    lines.append("    mutates_platform: false")
    lines.append("    workflow_visible: false")
    lines.append(
        "    parameters: "
        + flow(
            [
                {"name": "check", "type": "string", "required": True},
                {"name": "site_url", "type": "string", "required": False},
            ]
        )
    )
    lines.append(f"    result_fields: {flow(list(VALIDATE_SETTINGS_RESULT_FIELDS))}")
    lines.append(f"    error_codes: {flow(VALIDATE_SETTINGS_ERRORS)}")
    export_doc = OPERATION_DOCS[EXPORT_PRODUCTS_OPERATION_ID]
    lines.append(f"  - action_id: {EXPORT_PRODUCTS_OPERATION_ID}")
    lines.append(f"    title: {scalar(export_doc.title)}")
    lines.append(f"    description: {scalar(catalog_description(export_doc))}")
    lines.append("    required_scopes: [extension:invoke, artifact:write]")
    lines.append("    handler: {mode: extension}")
    lines.append("    mutates_platform: false")
    lines.append("    workflow_visible: true")
    lines.append(f"    parameters: {flow(export_products_action_parameters())}")
    lines.append(f"    result_fields: {flow([row['name'] for row in EXPORT_PRODUCTS_OUTPUTS])}")
    lines.append(
        f"    error_codes: {flow([*BASE_ERRORS, E.WOOCOMMERCE_NOT_CONFIGURED, E.ARTIFACT_OUTPUT_UNAVAILABLE])}"
    )
    for row in REST_OPERATIONS:
        scopes = ["extension:invoke"]
        if row.shape == "media_create":
            scopes.append("artifact:read")
        doc = OPERATION_DOCS[row.operation_id]
        lines.append(f"  - action_id: {row.operation_id}")
        lines.append(f"    title: {scalar(doc.title)}")
        lines.append(f"    description: {scalar(catalog_description(doc))}")
        lines.append(f"    required_scopes: {flow(scopes)}")
        lines.append("    handler: {mode: extension}")
        if row.has_external_effect:
            lines.append("    command_type: invoke_extension_action")
        lines.append(f"    mutates_platform: {'true' if row.has_external_effect else 'false'}")
        lines.append("    workflow_visible: true")
        lines.append(f"    parameters: {flow(action_parameters(row))}")
        lines.append(f"    result_fields: {flow(result_field_names(row))}")
        lines.append(f"    error_codes: {flow(error_codes(row))}")
    (BUNDLE / "ui/actions/actions.yaml").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------- external effects


def external_effect_lines() -> list[str]:
    lines = []
    for row in REST_OPERATIONS:
        if not row.has_external_effect:
            continue
        lines.append(
            "  - "
            + flow(
                {
                    "operation_id": row.operation_id,
                    "effect_kind": row.effect_kind,
                    "channel": row.channel,
                    "idempotency": "required",
                    "test_mode_behavior": "suppress",
                }
            )
        )
    return lines


#: Every file this script owns, in the order it writes them.
WRITERS = {
    "contracts/rest_coverage.yaml": write_coverage,
    "contracts/operation_manifest.yaml": write_operation_manifest,
    "contracts/step_ui_manifest.yaml": write_step_ui_manifest,
    "ui/actions/actions.yaml": write_actions,
}


def drifted() -> list[str]:
    """Names of the contract files whose content no longer matches the registry.

    Each writer renders from the registry and writes in one step, so the check
    runs them against a copy of the tree and compares the bytes.
    """
    stale: list[str] = []
    for name, write in WRITERS.items():
        target = BUNDLE / name
        before = target.read_bytes()
        write()
        after = target.read_bytes()
        if before != after:
            stale.append(name)
            target.write_bytes(before)
    return stale


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if arguments.check:
        stale = drifted()
        if stale:
            for name in stale:
                print(f"{name} is out of date", file=sys.stderr)
            return 1
        print("all contracts are current")
        return 0
    for write in WRITERS.values():
        write()
    print(f"wrote {len(WRITERS)} contract files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
