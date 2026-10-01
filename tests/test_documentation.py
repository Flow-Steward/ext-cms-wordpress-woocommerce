"""The Setup Guide page and the README describe the same connection contract."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from runtime.connection import CONFIG_FIELDS, SECRET_FIELDS
from runtime.connection_test import CONNECTION_STATES

BUNDLE_ROOT = Path(__file__).resolve().parents[1]

OFFICIAL_LINKS = (
    "https://developer.wordpress.org/rest-api/reference/application-passwords/",
    "https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/",
    "https://developer.woocommerce.com/docs/apis/rest-api/authentication/",
    "https://developer.woocommerce.com/docs/apis/rest-api/v3/",
)

WORDPRESS_INSTRUCTIONS = (
    "WordPress REST API is part of WordPress Core",
    "WordPress 5.6 or later",
    "least-privilege",
    "WordPress Admin → Users → Profile",
    "Application Passwords",
    "Flow Steward",
    "may not display it again",
    "not the email address",
    "normal WordPress login password",
)
WOOCOMMERCE_INSTRUCTIONS = (
    "WooCommerce must be installed and active",
    "Pretty permalinks must be enabled",
    "WooCommerce → Settings → Advanced → REST API",
    "Add key",
    "Read/Write",
    "Consumer Key",
    "Consumer Secret",
    "may not be shown again",
)
FLOW_STEWARD_INSTRUCTIONS = (
    "https://example.com",
    "/wp-json",
    "/wp/v2",
    "/wc/v3",
    "WordPress username",
    "WordPress Application Password",
    "Save the connection",
    "Test connection",
)
TROUBLESHOOTING = (
    "REST API blocked or unavailable",
    "Pretty permalinks disabled",
    "Incorrect username or Application Password",
    "Application Passwords disabled by hosting or security policy",
    "Missing WordPress user capabilities",
    "WooCommerce not installed",
    "Incorrect WooCommerce key permissions",
    "Consumer Key or Consumer Secret missing",
    "Authorization headers stripped by the web server or proxy",
    "TLS certificate validation failure",
    "Private or local WordPress site rejected",
)
SECURITY = (
    "Use HTTPS",
    "least-privilege service user",
    "Flow Steward secret fields",
    "Do not place credentials in URLs",
    "Revoke the Application Password",
    "Rotate credentials",
)


def _setup_guide() -> dict:
    return yaml.safe_load((BUNDLE_ROOT / "ui/pages/setup-guide.yaml").read_text())


def _setup_guide_text() -> str:
    page = _setup_guide()
    return "\n".join(str(component.get("body") or "") for component in page["components"])


def _readme() -> str:
    return (BUNDLE_ROOT / "README.md").read_text()


def test_the_setup_guide_is_reachable_before_a_connection_exists() -> None:
    page = _setup_guide()
    assert page["page_id"] == "setup-guide"
    assert page["title"] == "Setup Guide"
    assert page["project_scoped"] is False


def test_the_setup_guide_uses_only_existing_declarative_components() -> None:
    page = _setup_guide()
    assert {component["type"] for component in page["components"]} == {"markdown"}
    for component in page["components"]:
        assert component["component_id"]
        assert component["title"]
        assert component["body"].strip()


@pytest.mark.parametrize("phrase", WORDPRESS_INSTRUCTIONS)
def test_the_setup_guide_carries_the_wordpress_instructions(phrase: str) -> None:
    assert phrase in _setup_guide_text()


@pytest.mark.parametrize("phrase", WOOCOMMERCE_INSTRUCTIONS)
def test_the_setup_guide_carries_the_woocommerce_instructions(phrase: str) -> None:
    assert phrase in _setup_guide_text()


@pytest.mark.parametrize("phrase", FLOW_STEWARD_INSTRUCTIONS)
def test_the_setup_guide_carries_the_flow_steward_instructions(phrase: str) -> None:
    assert phrase in _setup_guide_text()


@pytest.mark.parametrize("phrase", TROUBLESHOOTING)
def test_the_setup_guide_carries_the_troubleshooting_section(phrase: str) -> None:
    assert phrase in _setup_guide_text()


@pytest.mark.parametrize("phrase", SECURITY)
def test_the_setup_guide_carries_the_security_guidance(phrase: str) -> None:
    assert phrase in _setup_guide_text()


@pytest.mark.parametrize("link", OFFICIAL_LINKS)
def test_the_setup_guide_links_to_the_official_documentation(link: str) -> None:
    assert link in _setup_guide_text()


def test_the_setup_guide_explains_every_connection_state() -> None:
    text = _setup_guide_text()
    for state in CONNECTION_STATES:
        assert state in text


def test_the_setup_guide_never_prints_a_credential_value() -> None:
    """The guide explains where credentials go; it never contains one."""
    text = _setup_guide_text()
    for forbidden in (
        "Basic YWRt",
        "ck_",
        "cs_",
        "consumer_secret=",
        "application_password=",
        "Authorization: Basic",
    ):
        assert forbidden not in text


@pytest.mark.parametrize(
    "phrase",
    WORDPRESS_INSTRUCTIONS
    + WOOCOMMERCE_INSTRUCTIONS
    + FLOW_STEWARD_INSTRUCTIONS
    + TROUBLESHOOTING
    + SECURITY
    + OFFICIAL_LINKS,
)
def test_the_readme_repeats_the_complete_setup_procedure(phrase: str) -> None:
    assert phrase in _readme()


def test_the_readme_and_the_setup_guide_name_the_same_connection_fields() -> None:
    guide = _setup_guide_text()
    readme = _readme()
    labels = {
        "site_url": "Site URL",
        "wordpress_username": "WordPress username",
        "wordpress_application_password": "WordPress Application Password",  # pragma: allowlist secret
        "woocommerce_consumer_key": "WooCommerce Consumer Key",
        "woocommerce_consumer_secret": "WooCommerce Consumer Secret",  # pragma: allowlist secret
    }
    assert set(labels) == CONFIG_FIELDS | SECRET_FIELDS
    for label in labels.values():
        assert label in guide
        assert label in readme


def test_the_readme_and_the_setup_guide_describe_the_same_states() -> None:
    readme = _readme()
    for state in CONNECTION_STATES:
        assert state in readme


def test_the_connection_form_offers_exactly_the_declared_fields() -> None:
    component = yaml.safe_load(
        (BUNDLE_ROOT / "ui/components/wordpress_connection_form.yaml").read_text()
    )
    data = component["data"]
    assert component["type"] == "connection_form"
    assert data["connection_type"] == "wordpress_site"
    assert set(data["config_fields"]) == CONFIG_FIELDS
    assert set(data["secret_fields"]) == SECRET_FIELDS
    assert data["required_secret_fields"] == ["wordpress_application_password"]
    assert data["test_action"] == "test_connection"
    paths = {field["path"] for field in component["fields"]}
    assert paths >= (CONFIG_FIELDS | SECRET_FIELDS)


def test_the_api_pages_report_the_registry_they_describe() -> None:
    from runtime.catalog import WOOCOMMERCE_OPERATIONS, WORDPRESS_OPERATIONS

    wordpress = yaml.safe_load((BUNDLE_ROOT / "ui/pages/wordpress-api.yaml").read_text())
    woocommerce = yaml.safe_load((BUNDLE_ROOT / "ui/pages/woocommerce-api.yaml").read_text())

    assert (
        wordpress["components"][0]["title"] == f"{len(WORDPRESS_OPERATIONS)} operations available"
    )
    assert (
        woocommerce["components"][0]["title"]
        == f"{len(WOOCOMMERCE_OPERATIONS)} operations available"
    )
    combined = "\n".join(
        str(component.get("body") or "")
        for page in (wordpress, woocommerce)
        for component in page["components"]
    )
    assert "there is no general-purpose request action" in combined
    assert "there is no general-purpose request action" in combined
    # Webhook operations were withdrawn, so the page must not still describe them.
    assert "Webhook operations manage the webhook record" not in combined
    assert "Adding or changing WooCommerce webhooks" in combined
