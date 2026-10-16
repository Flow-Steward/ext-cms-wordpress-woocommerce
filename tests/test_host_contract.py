"""The envelope the platform actually sends, not the one the tests invent.

Every other suite builds its own request payload, so an envelope the host sends
and the extension refuses passes all of them. These fixtures are written from
the host's own request builder
(``core/infrastructure/extension_runtime/extension_runtime_entrypoints.py``) and
are deliberately not derived from the extension's code.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import (
    CONNECTION_ID,
    FOR_EACH_STEP_SCOPE,
    GROUP_STEP_SCOPE,
    HOST_CONTRACT_VERSION,
    ROOT_STEP_SCOPE,
    SITE_URL,
    json_response,
    sample_input,
)
from dispatcher import dispatch_runtime
from flowsteward_extension_sdk import runtime_context_from_payload
from runtime import errors
from runtime.catalog import REST_OPERATIONS
from runtime.operations import handle_runtime

#: The exact keys the host puts in an action envelope.
HOST_ACTION_KEYS = ("action_id", "page_id", "component_id", "context", "target", "input")

#: The exact top-level keys of a host request.
HOST_REQUEST_KEYS = ("contract_version", "mode", "host", "action", "runtime_context")

#: A call outside any workflow run (the connection form): all four scope keys null.
NO_RUN_SCOPE: dict[str, Any] = {
    "group_id": None,
    "for_each_id": None,
    "step_id": None,
    "step_execution_id": None,
}


def _host_block(scope: dict[str, Any]) -> dict[str, Any]:
    """The `host` block: who calls, for which project, and from which execution."""
    return {
        "contract_version": HOST_CONTRACT_VERSION,
        "operation": "command",
        "scope": {
            "account_id": "account-1",
            "project_id": "project-1",
            "job_id": None if scope == NO_RUN_SCOPE else "job-1",
            **scope,
        },
        "principal": {"user_id": "user-1"},
    }


WOO: dict[str, Any] = {"consumer_key": "ck", "consumer_secret": "cs"}  # pragma: allowlist secret


def host_payload(
    operation_id: str,
    operation_input: dict[str, Any],
    *,
    page_id: str | None = "wordpress-api",
    component_id: str | None = "wordpress_api_content",
    consumer_key: str = "",
    consumer_secret: str = "",
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A request shaped exactly the way the platform builds one."""
    scope = dict(ROOT_STEP_SCOPE if scope is None else scope)
    secrets: dict[str, str] = {"wordpress_application_password": "abcd EFGH"}
    if consumer_key:
        secrets["woocommerce_consumer_key"] = consumer_key
    if consumer_secret:
        secrets["woocommerce_consumer_secret"] = consumer_secret
    return {
        "contract_version": HOST_CONTRACT_VERSION,
        "mode": "action",
        "host": _host_block(scope),
        "action": {
            "action_id": operation_id,
            "page_id": page_id,
            "component_id": component_id,
            "context": {"project_id": "project-1"},
            "target": {
                "connection": {
                    "connection_id": CONNECTION_ID,
                    "connection_type_id": "wordpress_site",
                    "config": {"site_url": SITE_URL, "wordpress_username": "svc"},
                    "secrets": secrets,
                }
            },
            "input": {"connection_ref": CONNECTION_ID, **operation_input},
        },
        "runtime_context": {"job_id": "job-1", **scope},
    }


def test_the_fixture_matches_the_documented_host_envelope() -> None:
    payload = host_payload("wp_list_posts", {})
    assert tuple(payload) == HOST_REQUEST_KEYS
    assert tuple(payload["action"]) == HOST_ACTION_KEYS


def test_a_host_shaped_request_is_accepted(http, transport_factory) -> None:
    """This is the call that failed in the platform with `invalid_payload`."""
    http.queue(json_response([{"id": 1}]))
    response = handle_runtime(
        host_payload("wp_list_posts", {}), transport_factory=transport_factory
    )
    assert response["ok"] is True, response.get("error")
    assert len(http.requests) == 1


def test_test_connection_works_through_the_host_envelope(http, transport_factory) -> None:
    """Reproduces the Test button in the connection form."""
    http.queue(
        json_response({"name": "Shop", "namespaces": ["wp/v2", "wc/v3"]}),
        json_response({"id": 7, "slug": "svc"}),
    )
    response = handle_runtime(
        host_payload(
            "test_connection", {}, page_id="connection", component_id="wordpress_site_connection"
        ),
        transport_factory=transport_factory,
    )
    assert response["ok"] is True, response.get("error")
    assert response["result"]["wordpress_state"] == "wordpress_ready"


@pytest.mark.parametrize("row", REST_OPERATIONS, ids=lambda row: row.operation_id)
def test_every_operation_accepts_the_host_envelope(http, transport_factory, row) -> None:
    if row.shape == "media_create":
        pytest.skip("needs an artifact grant; covered by the media suite")
    http.responses.clear()
    http.queue(json_response([] if row.shape == "list" else {"id": 1}))
    response = handle_runtime(
        host_payload(row.operation_id, sample_input(row), **WOO),
        transport_factory=transport_factory,
    )
    assert response["ok"] is True, (row.operation_id, response.get("error"))


@pytest.mark.parametrize("omitted", HOST_ACTION_KEYS)
def test_an_envelope_missing_an_optional_host_key_still_works(
    http, transport_factory, omitted: str
) -> None:
    """The host omits page_id and component_id when nothing invoked from a page."""
    if omitted in {"action_id", "input", "target"}:
        pytest.skip("not optional")
    payload = host_payload("wp_list_posts", {})
    del payload["action"][omitted]
    http.queue(json_response([]))
    assert handle_runtime(payload, transport_factory=transport_factory)["ok"] is True


def test_null_page_and_component_ids_are_accepted(http, transport_factory) -> None:
    """The host sends null when the action came from a workflow, not a page."""
    http.queue(json_response([]))
    response = handle_runtime(
        host_payload("wp_list_posts", {}, page_id=None, component_id=None),
        transport_factory=transport_factory,
    )
    assert response["ok"] is True, response.get("error")


def test_an_envelope_key_the_host_never_sends_is_still_refused(http, transport_factory) -> None:
    """The envelope stays closed: this is not a licence to accept anything."""
    payload = host_payload("wp_list_posts", {})
    payload["action"]["smuggled"] = {"method": "DELETE"}
    response = handle_runtime(payload, transport_factory=transport_factory)

    assert response["ok"] is False
    assert response["error_code"] == errors.INVALID_PAYLOAD
    assert http.requests == []


# -- The connection form's pre-save validation ---------------------------


def _pre_save(check: str, **values: Any) -> dict[str, Any]:
    """A pre-save action request, shaped the way the connection form builds one."""
    return {
        "contract_version": HOST_CONTRACT_VERSION,
        "mode": "action",
        "host": _host_block(NO_RUN_SCOPE),
        "action": {
            "action_id": "validate_connection_settings",
            "page_id": "connection",
            "component_id": "wordpress_site_connection",
            "context": {"project_id": "project-1"},
            "target": {},
            "input": {"check": check, **values},
        },
        "runtime_context": dict(NO_RUN_SCOPE),
    }


def test_the_form_declares_a_pre_save_check_for_each_unenforced_rule() -> None:
    """`dependentRequired` and https-only are declared but not run at save."""
    from pathlib import Path

    import yaml

    component = yaml.safe_load(
        (
            Path(__file__).resolve().parents[1] / "ui/components/wordpress_connection_form.yaml"
        ).read_text()
    )
    actions = component["data"]["pre_save_actions"]
    assert [action["action_id"] for action in actions] == ["validate_connection_settings"] * 3
    checks = [action["data"]["check"] for action in actions]
    assert checks == ["site_url", "woocommerce_pair", "woocommerce_pair"]

    # The two credential checks are triggered by browser-side conditions, so no
    # secret is ever placed in an action payload.
    for action in actions[1:]:
        assert action["run_when"]
        assert "values_fields" not in action
    assert actions[0]["values_fields"] == ["site_url"]


@pytest.mark.parametrize(
    "site_url",
    ["https://example.com", "https://example.com/blog", "example.com"],
)
def test_a_usable_site_url_passes_the_pre_save_check(site_url: str) -> None:
    response = handle_runtime(_pre_save("site_url", site_url=site_url))
    assert response["ok"] is True
    assert response["result"]["normalized_site_url"].startswith("https://")


@pytest.mark.parametrize(
    "site_url",
    [
        "http://example.com",
        "",
        "ftp://example.com",
        "https://user:pw@example.com",  # pragma: allowlist secret
    ],
)
def test_an_unusable_site_url_blocks_the_save(site_url: str) -> None:
    """This is what the UI let through: http:// saved without complaint."""
    response = handle_runtime(_pre_save("site_url", site_url=site_url))
    assert response["ok"] is False
    assert response["error_code"] == errors.INVALID_CONFIGURATION


def test_a_half_configured_credential_pair_blocks_the_save() -> None:
    """The other thing the UI let through: a Consumer Key with no Secret."""
    response = handle_runtime(_pre_save("woocommerce_pair"))
    assert response["ok"] is False
    assert response["error_code"] == errors.WOOCOMMERCE_CREDENTIALS_INCOMPLETE


def test_the_pre_save_check_never_reaches_the_network(http, transport_factory) -> None:
    handle_runtime(_pre_save("site_url", site_url="https://example.com"))
    handle_runtime(_pre_save("woocommerce_pair"))
    assert http.requests == []


def test_the_pre_save_check_refuses_an_unknown_check() -> None:
    response = handle_runtime(_pre_save("something_else"))
    assert response["error_code"] == errors.INVALID_PAYLOAD


@pytest.mark.parametrize(
    "site_url",
    [
        "http://example.com",
        "",
        "ftp://example.com",
        "https://user:pw@example.com",  # pragma: allowlist secret
        "https://example.com?a=1",
        "https://example.com/a/../b",
    ],
)
def test_a_refused_site_url_explains_itself_without_naming_a_wire_field(site_url: str) -> None:
    """The form shows this message verbatim, so it has to read as a correction.

    A message such as `site_url must use https` tells somebody who is looking at
    a field labelled "Site URL" nothing they can act on, and names an internal
    field they never see.
    """
    response = handle_runtime(_pre_save("site_url", site_url=site_url))
    assert response["ok"] is False
    message = response["error"]
    assert message
    assert "_" not in message, message
    assert message[0].isupper(), message
    assert len(message.split()) >= 4, message


def test_the_woocommerce_pair_check_names_both_halves() -> None:
    response = handle_runtime(_pre_save("woocommerce_pair"))
    assert response["ok"] is False
    assert "consumer key" in response["error"]
    assert "consumer secret" in response["error"]


# -- The final execution scope ---------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" * 10


def _route_with(monkeypatch: pytest.MonkeyPatch, **fakes: Any) -> None:
    """Let ``dispatch_runtime`` reach the real runtime with fake I/O."""
    import dispatcher

    monkeypatch.setattr(
        dispatcher, "handle_runtime", lambda payload: handle_runtime(payload, **fakes)
    )


def _media_request(scope: dict[str, Any]) -> dict[str, Any]:
    """A media upload as the host sends it: envelope, scope and artifact grant."""
    from test_media_upload import _grant

    payload = host_payload(
        "wp_create_media",
        {"artifact_handle": "artifact-1", "filename": "photo.png", "title": "Spring"},
        scope=scope,
    )
    payload.update(_grant(PNG))
    return payload


def test_the_host_envelopes_pass_the_sdk_contract_check() -> None:
    for payload in (host_payload("wp_list_posts", {}), _pre_save("woocommerce_pair")):
        context = runtime_context_from_payload(payload)
        assert context.contract_version == HOST_CONTRACT_VERSION


@pytest.mark.parametrize(
    "scope",
    [ROOT_STEP_SCOPE, GROUP_STEP_SCOPE, FOR_EACH_STEP_SCOPE],
    ids=["root", "group", "for_each"],
)
def test_the_catalog_export_writes_its_artifact_for_every_owner(
    http, transport_factory, monkeypatch: pytest.MonkeyPatch, scope: dict[str, Any]
) -> None:
    http.queue(json_response([{"id": 1}], headers={"X-WP-Total": "1", "X-WP-TotalPages": "1"}))
    written: list[dict[str, Any]] = []

    def artifact_writer(payload: Any, chunks: Any, **kwargs: Any) -> dict[str, Any]:
        body = b"".join(chunks)
        written.append({"scope": dict(payload["runtime_context"]), "body": body})
        return {"artifact_handle": "artifact:catalog", "size_bytes": len(body), "sha256": "x"}

    _route_with(monkeypatch, transport_factory=transport_factory, artifact_writer=artifact_writer)

    response = dispatch_runtime(host_payload("wc_export_products", {}, scope=scope, **WOO))

    assert response["ok"] is True, response.get("error")
    assert response["result"]["artifact_handle"] == "artifact:catalog"
    assert response["result"]["item_count"] == 1
    assert len(written) == 1
    assert {key: written[0]["scope"][key] for key in scope} == scope
    assert b'"id":1' in written[0]["body"].replace(b" ", b"")


@pytest.mark.parametrize(
    "scope",
    [ROOT_STEP_SCOPE, GROUP_STEP_SCOPE, FOR_EACH_STEP_SCOPE],
    ids=["root", "group", "for_each"],
)
def test_the_media_upload_reads_its_artifact_for_every_owner(
    http, transport_factory, monkeypatch: pytest.MonkeyPatch, scope: dict[str, Any]
) -> None:
    http.queue(json_response({"id": 501, "source_url": "https://shop.example/x.png"}, status=201))
    reads: list[str] = []

    def artifact_streamer(*_args: Any, **_kwargs: Any) -> Any:
        reads.append(scope["step_execution_id"])
        return iter([PNG])

    _route_with(
        monkeypatch, transport_factory=transport_factory, artifact_streamer=artifact_streamer
    )

    response = dispatch_runtime(_media_request(scope))

    assert response["ok"] is True, response.get("error")
    assert response["result"]["data"]["id"] == 501
    assert reads == [scope["step_execution_id"]]
    assert len(http.requests) == 1
    assert PNG in http.last["body"]


@pytest.mark.parametrize(
    ("contract_version", "scope", "reason"),
    [
        ("extension_host_v1", FOR_EACH_STEP_SCOPE, "Unsupported host contract"),
        ("1.0", FOR_EACH_STEP_SCOPE, "Unsupported host contract"),
        ("", FOR_EACH_STEP_SCOPE, "Unsupported host contract"),
        (
            HOST_CONTRACT_VERSION,
            {k: v for k, v in FOR_EACH_STEP_SCOPE.items() if k != "for_each_id"},
            "misses execution scope",
        ),
        (
            HOST_CONTRACT_VERSION,
            {**FOR_EACH_STEP_SCOPE, "group_id": "prepare_catalog"},
            "both a Group and a For each",
        ),
        (
            HOST_CONTRACT_VERSION,
            {**ROOT_STEP_SCOPE, "step_execution_id": None},
            "without its logical execution",
        ),
    ],
    ids=["v1", "legacy_1_0", "no_contract", "missing_key", "two_owners", "step_no_execution"],
)
def test_a_foreign_or_incomplete_envelope_is_refused_before_any_effect(
    http,
    monkeypatch: pytest.MonkeyPatch,
    contract_version: str,
    scope: dict[str, Any],
    reason: str,
) -> None:
    touched: list[str] = []

    def forbidden(name: str) -> Any:
        def call(*_args: Any, **_kwargs: Any) -> Any:
            touched.append(name)
            raise AssertionError(f"{name} ran for a refused envelope")

        return call

    _route_with(
        monkeypatch,
        transport_factory=forbidden("transport"),
        artifact_streamer=forbidden("artifact_streamer"),
        artifact_writer=forbidden("artifact_writer"),
    )
    payload = _media_request(ROOT_STEP_SCOPE)
    payload["contract_version"] = contract_version
    payload["runtime_context"] = dict(scope)

    response = dispatch_runtime(payload)

    assert response["ok"] is False
    assert response["error_code"] == errors.INVALID_HOST_ENVELOPE
    assert reason in response["error"]
    assert response["definitely_no_external_effect"] is True
    assert touched == []
    assert http.requests == []
