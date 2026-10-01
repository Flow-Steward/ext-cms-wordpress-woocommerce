# WordPress & WooCommerce

A curated, automation-safe subset of the WordPress Core and WooCommerce REST APIs, typed and
scoped to one project-scoped WordPress site.

"Automation-safe" rather than "non-destructive": no HTTP `DELETE` is exposed and no record can be
binned by changing its status, with one deliberate exception. Moderating a comment may set it to
`spam` or `trash`, because that is what moderation is. See
[What it does not do](#what-it-does-not-do).

- Extension ID: `flowsteward.wordpress-woocommerce`
- Version: `1.0.0`
- Billing: free
- Vendor: Flow Steward

The extension exposes exactly the operations declared in `contracts/rest_coverage.yaml`. That file
is the coverage source of truth: every supported route, and every documented route deliberately
left out, with the reason. Nothing is discovered at runtime from `/wp-json/`, `OPTIONS`, installed
plugins, or site configuration, and there is no generic request, raw request, arbitrary method and
path executor, or API explorer.

Each operation is a typed contract, not a passthrough. Its inputs are exactly the query and body
parameters the official reference documents for that one route, each with its own type,
enumeration, and required flag; nested structures such as an order's `billing` or `line_items` are
modelled too, and responses carry the documented record shape. An undocumented top-level field —
`acf`, `lang`, a SEO plugin key, anything a plugin might add — is refused before a request is
built, including inside each item of a batch payload. That boundary is what keeps this free
extension separate from the future ACF, WPML, Polylang, and SEO extensions.

## Where to look

The extension carries its own pages inside Flow Steward:

| Page | Use it to |
| --- | --- |
| **Setup Guide** | Create the WordPress Application Password and the WooCommerce API key, fill in the connection, and read the troubleshooting and security guidance. Available before any connection exists. |
| **Connection** | Add and manage the project-scoped connection to one WordPress site. |
| **WordPress API** | Browse every WordPress operation, grouped by resource, with what each one needs and returns — and what is deliberately unavailable. |
| **WooCommerce API** | The same for the WooCommerce store operations. |
| **Changelog** | What changed in each release. Also kept in [CHANGELOG.md](CHANGELOG.md). |

## What it does

This is a curated, automation-safe subset of the native APIs, not an implementation of every
official operation and field. What it leaves out, it leaves out on purpose, and
`contracts/rest_coverage.yaml` lists every route either way with the reason.

- One project-scoped connection to a single WordPress site.
- Connection health testing with independent WordPress and WooCommerce states.
- 78 typed WordPress Core operations under `/wp/v2`.
- 114 typed WooCommerce operations under `/wc/v3`.
- Five extension-owned declarative pages: `Setup Guide`, `Connection`, `WordPress API`,
  `WooCommerce API`, `Changelog`.

## What it does not do

**User identity is read-only.** Users can be listed and read, but creating or changing a user
account is not available: that is account administration rather than content automation, and a
mistake in a workflow can lock somebody out or grant more access than intended.

**Passwords are not carried.** The protected-content password on posts, pages and reusable
blocks, and the account password on WooCommerce customers, are neither accepted nor returned.
Supplying one is refused rather than quietly ignored. This is a narrow rule about those documented
fields: WordPress `meta`, WooCommerce `meta_data`, a WooCommerce setting whose own type happens to
be `password`, and ordinary content are all untouched, and the connection's own WordPress
Application Password is a stored connection secret that none of this affects.

**WooCommerce webhooks are configured by hand.** All five `/webhooks` routes are excluded, because
where a store sends its data is not something an automation should change on your behalf. The
`Setup Guide` page explains the two-minute manual flow: add a webhook trigger to a workflow, copy
the URL it gives you, and paste it into `WooCommerce → Settings → Advanced → Webhooks`. The
extension registers, lists, changes and synchronises nothing, and adds no trigger, callback
service, admin page or signature verification of its own.

**Comment moderation stays available.** Marking a comment as `spam`, or moving one to `trash`, is
what moderation is, so those states remain selectable on the supported comment operations. That is
the one approved route by which anything reaches `trash`.

No HTTP `DELETE` operation is exposed and no batch payload may carry a `delete` member. Also
excluded: refund creation, change and deletion; WooCommerce system-status tool execution; and
WordPress plugin, theme and Application Password lifecycle management.

The extension ships no workflows, agents, skills, datasets, saved queries, guardrails, triggers,
callbacks, scheduled jobs, or example automations. There is no enrichment, translation,
synchronization, reconciliation, mapping, or other business logic; a stock or price operation
issues only the native product, variation, or documented batch update you asked for.

ACF, WPML, Polylang, TranslatePress, SEO plugins and other plugin APIs are out of scope and are
planned as separate extensions that depend on this one.

## Setup

This is the same procedure the `Setup Guide` page renders in the UI, repeated here so it is
available outside Flow Steward.

### 1. WordPress

The WordPress REST API is part of WordPress Core. A standard site does not need a separate plugin
to expose it.

- WordPress 5.6 or later is required, because that is the release that added native Application
  Passwords.
- The site should use HTTPS. This extension only connects over HTTPS.
- The REST API must not be disabled or blocked. A security plugin, a hosting firewall, or a custom
  configuration can block it.
- Create or select a least-privilege WordPress service account that holds only the permissions the
  operations you intend to run actually require.

Create the Application Password:

1. Sign in to WordPress as the service account, or as an administrator editing that account.
2. Navigate to `WordPress Admin → Users → Profile`.
3. Scroll to the `Application Passwords` section.
4. Enter a recognizable application name, such as `Flow Steward`.
5. Select the button that generates the Application Password.
6. Copy the generated password as soon as it is displayed. WordPress may not display it again.

Use the WordPress username, not the email address, unless the two are identical and the site
accepts the email address as a username. Do not use the user's normal WordPress login password:
this extension authenticates only with an Application Password.

### 2. WooCommerce (optional)

WooCommerce credentials are optional. Leave both fields empty if you only need WordPress
operations; every WordPress operation still works without them.

- WooCommerce must be installed and active on the site.
- Pretty permalinks must be enabled. The WooCommerce REST API does not work with plain permalinks.

Create the API key:

1. Navigate to `WooCommerce → Settings → Advanced → REST API`.
2. Select `Add key`.
3. Enter a recognizable description, such as `Flow Steward`.
4. Select the WordPress user whose permissions the API key will use.
5. Select `Read/Write` permissions to reach the complete supported API surface.
6. Select the button that generates the API key.
7. Copy both the Consumer Key and the Consumer Secret as soon as they are displayed.
   The secret may not be shown again.

### 3. Complete the Flow Steward connection

Open the `Connection` page in this extension and fill in the form.

1. **Site URL** - the base site URL, for example `https://example.com`. Do not append `/wp-json`,
   `/wp/v2`, or `/wc/v3`.
2. **WordPress username** - the username of the service account.
3. **WordPress Application Password** - the value copied from `Users → Profile`.
4. **WooCommerce Consumer Key** and **WooCommerce Consumer Secret** - optional, but supply both or
   neither. One alone is rejected before Flow Steward contacts WooCommerce.
5. Save the connection.
6. Run `Test connection`.

### 4. Reading the result

`Test connection` reports WordPress and WooCommerce independently.

WordPress state:

- `wordpress_ready` - the site answered, `/wp/v2` is published, and the Application Password
  authenticated.
- `wordpress_unavailable` - the site did not answer, or it does not publish `/wp/v2`.
- `wordpress_authentication_failed` - the site answered but rejected the username and Application
  Password.

WooCommerce state:

- `woocommerce_ready` - `/wc/v3` is published and the Consumer Key and Consumer Secret
  authenticated.
- `woocommerce_not_installed` - no `/wc/v3` namespace was detected at the site.
- `woocommerce_not_configured` - `/wc/v3` is published, but this connection carries no WooCommerce
  credentials. WordPress operations still work.
- `woocommerce_authentication_failed` - `/wc/v3` is published and credentials were supplied, but
  WooCommerce rejected them.

## Troubleshooting

**REST API blocked or unavailable.** Open `https://your-site/wp-json/` in a browser. If it does not
return JSON, a security plugin, a hosting firewall, or a custom rule is blocking the REST API.

**Pretty permalinks disabled.** Set `Settings → Permalinks` to any option other than `Plain`.

**Incorrect username or Application Password.** Confirm you entered the WordPress username rather
than the display name or email address, and that the Application Password was pasted whole.

**Application Passwords disabled by hosting or security policy.** If the `Application Passwords`
section is missing from `Users → Profile`, the site or its host has disabled the feature. This
extension supports no alternative authentication.

**Missing WordPress user capabilities.** An `authorization_failed` result means the site
authenticated the account but the account may not perform that operation.

**WooCommerce not installed.** Confirm WooCommerce is active, then confirm
`https://your-site/wp-json/` lists `wc/v3` among its namespaces.

**Incorrect WooCommerce key permissions.** A key created with `Read` permissions cannot run a
WooCommerce create, update, or batch operation. Create a new key with `Read/Write` permissions.

**Consumer Key or Consumer Secret missing.** Supplying one WooCommerce secret without the other
fails validation before any WooCommerce request is sent.

**Authorization headers stripped by the web server or proxy.** Some Apache and CGI setups drop the
`Authorization` header. Ask the host to pass the header through.

**TLS certificate validation failure.** Flow Steward verifies the site certificate and does not skip
verification.

**Private or local WordPress site rejected.** The default Flow Steward network policy refuses
private, loopback, link-local, and other reserved addresses, and this extension adds no exception.
See "Known platform gap" below for the one address class the shipped policy does not yet refuse.

## Security

- Use HTTPS. This extension refuses any site URL that is not `https`.
- Use a dedicated least-privilege service user wherever that is practical.
- Store credentials only in the Flow Steward secret fields on the `Connection` page.
- Do not place credentials in URLs. Flow Steward sends them as an HTTPS Basic `Authorization`
  header and rejects a site URL that carries credentials.
- Revoke the Application Password and the WooCommerce keys when the access is no longer required.
- Rotate credentials if they may have been exposed, then update the connection.

## Official documentation

- [WordPress Application Passwords](https://developer.wordpress.org/rest-api/reference/application-passwords/)
- [WordPress REST API authentication](https://developer.wordpress.org/rest-api/using-the-rest-api/authentication/)
- [WooCommerce REST API authentication](https://developer.woocommerce.com/docs/apis/rest-api/authentication/)
- [WooCommerce REST API v3 reference](https://developer.woocommerce.com/docs/apis/rest-api/v3/)

## Extending this integration

`flowsteward.wordpress-woocommerce` is the dependency target for future paid extensions that add
ACF, WPML, Polylang, SEO plugin, or other custom functionality. Those extensions declare a
versioned dependency on this extension ID; none of that lives here, and this bundle ships no
paid-feature, billing, subscription, marketplace, or entitlement artifact.

## Layout

| Path | Purpose |
| --- | --- |
| `extension.yaml` | Manifest, external-effect declarations, artifact policy |
| `contracts/rest_coverage.yaml` | Coverage source of truth |
| `contracts/rest_reference.yaml` | Committed snapshot of the official reference pages |
| `runtime/parameters.py` | Typed query, body, and response fields per operation |
| `contracts/connection_types.yaml` | The single project-scoped connection type |
| `contracts/operation_manifest.yaml` | Typed operation contracts |
| `contracts/step_ui_manifest.yaml` | Declarative step forms |
| `contracts/artifact_policies.yaml` | The media input artifact grant |
| `runtime/catalog.py` | The closed runtime operation registry |
| `runtime/coverage.py` | Supported and excluded coverage rows |
| `runtime/transport.py` | Shared transport, built on the public extension SDK |
| `tests/` | Extension-owned tests, all with mocked transports |
| `runtime/descriptions.py` | The plain-language text behind the API pages and builder actions |
| `ui/` | The five extension-owned declarative pages |
| `CHANGELOG.md` | Release history, rendered by the Changelog page |
| `tests/reference/` | The generators that rebuild the snapshot, the typed tables and the pages |

## Development

```
python -m ruff check --fix extensions/flowsteward_wordpress_woocommerce
python -m ruff format extensions/flowsteward_wordpress_woocommerce
python -m pytest extensions/flowsteward_wordpress_woocommerce/tests -x -v
```

The test suite is fully offline. No test requires a live WordPress or WooCommerce instance.

### Refreshing the documentation snapshot

The coverage inventory and the typed parameter tables are derived from the official references,
not hand-written. Run these from the bundle root when the upstream documentation changes; only the
first one uses the network:

```
python tests/reference/refresh_reference.py    # the only one that uses the network
python tests/reference/build_parameters.py
python tests/reference/build_contracts.py
python tests/reference/build_ui_pages.py
```

`--check` on any of the three generators fails instead of writing, which is what the test suite
runs. If the upstream references gain a route or a parameter, `refresh_reference.py` picks it up
and the conformance tests fail until the registry is updated to match.

The chain runs one way, and nothing downstream is edited by hand:

```
official references
  -> contracts/rest_reference.yaml          (refresh_reference.py, network)
     -> runtime/parameters.py               (build_parameters.py)
        -> contracts/rest_coverage.yaml     (build_contracts.py)
           contracts/operation_manifest.yaml
           contracts/step_ui_manifest.yaml
           ui/actions/actions.yaml
        -> ui/pages/wordpress-api.yaml      (build_ui_pages.py)
           ui/pages/woocommerce-api.yaml
           ui/pages/changelog.yaml
```

The sources of truth are `runtime/catalog.py` (which operations exist), `runtime/coverage.py`
(why a route is excluded), `runtime/field_policy.py` (which documented fields are refused),
`runtime/descriptions.py` (the human wording) and `CHANGELOG.md`. Everything in the diagram below
a `->` is generated from them.

## Known platform gap

The public extension SDK derives its address policy from `ipaddress.is_global`, which classifies
IPv4 and IPv6 multicast literals as global and therefore does not refuse them up front. This
extension uses the SDK guard unchanged and adds no local override, so the gap is reported rather
than worked around. A TCP connection to a multicast literal cannot complete, so no request is
dispatched in practice.
