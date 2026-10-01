# Changelog

All notable changes to the WordPress & WooCommerce extension are recorded here.

Entries use these sections where they apply: **Added**, **Changed**, **Deprecated**,
**Removed**, **Fixed**, **Security**. When an entry adds or changes an endpoint it names the
capability in plain language and the technical endpoint, so both a store owner and an integrator
can read it:

```markdown
## 1.1.0

### Added

- Added the ability to retrieve refunds for an order.
  Endpoint: `GET /orders/{id}/refunds`.
```

## Unreleased

### Changed

- **The supported surface is now a curated automation-safe subset.**
  WordPress covers 78 operations and WooCommerce 114 operations, down from 81 and 119.
  Every withdrawn route is still listed in `contracts/rest_coverage.yaml` with the reason it
  was withdrawn.
- **`Preview a refund` now uses the endpoint's own contract.** It was published with the
  create-a-refund request and response by mistake. A preview line names `line_item_id`,
  `quantity` and an optional `refund_total`, and the result is the documented `breakdown`,
  `subtotal`, `tax`, `total` and `max_refundable` rather than a created refund.
  Endpoint: `POST /orders/{id}/refunds/preview`. Requires WooCommerce 11.1 or newer.
- **`List a customer's downloads` now returns downloads.** It was published with the
  customer-list filters and the customer record. It now takes only the customer and an optional
  `context`, and returns the documented download fields.
  Endpoint: `GET /customers/{id}/downloads`.

### Removed

- **Creating and changing WordPress users.** `POST /users`, `POST /users/{id}` and
  `POST /users/me` are withdrawn: account administration is not content automation, and a
  mistake in a workflow can lock somebody out or grant more access than intended. Reading users
  is unchanged.
- **Adding and changing WooCommerce webhooks.** All five `/webhooks` routes are withdrawn. Where
  a store sends its data is configured by hand; the Setup Guide explains how to point a
  WooCommerce webhook at a workflow's own trigger URL.
- **Password fields.** The protected-content password on posts, pages and reusable blocks, and
  the account password on WooCommerce customers, are no longer accepted or returned. Supplying
  one is refused rather than quietly ignored. The connection's own WordPress Application
  Password is unaffected, and nothing touches `meta`, `meta_data` or settings metadata.

### Fixed

- **Required fields are marked as required.** WordPress states this as `Required: 1` in prose
  and only WooCommerce's `MANDATORY` was ever read, so fields such as the name of a new category
  or tag, and the sidebar of a new widget, were published as optional.
- **Fields the reference says are never returned no longer appear in a response model** —
  WooCommerce `WRITE-ONLY` and WordPress `never included`.

## 1.0.0

First release.

### Added

- **WordPress content and settings over the official `/wp/v2` REST API** — 81 operations across 28
  resources: posts, pages and their revisions and autosaves, media, comments, categories, tags,
  taxonomies, users, post types, post statuses, site settings, themes, search, block types,
  reusable blocks and their revisions, the block and pattern directories, block patterns and
  pattern categories, rendered blocks, menu locations, sidebars, widget types, widgets, and
  plugins.
- **WooCommerce store data over the official `/wc/v3` REST API** — 119 operations across 30
  resources: products and variations, product attributes and their terms, product categories,
  tags, shipping classes, custom field names and reviews, orders, order notes, the non-destructive
  order actions, refunds, customers, coupons, taxes and tax classes, shipping zones with their
  locations and methods, shipping methods, settings and setting options, payment gateways,
  webhooks, reports, system status and store data.
- **One connection for both** — a single project-scoped connection holding the site URL, the
  WordPress username and an Application Password, plus an optional WooCommerce Consumer Key and
  Consumer Secret. WordPress operations work without the WooCommerce keys; the two WooCommerce
  keys must be supplied together or not at all.
  Endpoint used to verify it: `GET /wp-json/`.
- **Connection testing that reports each provider separately** — WordPress and WooCommerce each
  get their own readiness state, so a WooCommerce problem never hides a working WordPress
  connection.
- **The ability to preview a refund without creating one.**
  Endpoint: `POST /orders/{id}/refunds/preview`.
- **Typed contracts for every operation** — each operation accepts exactly the query and body
  fields the official reference documents for its route, with types, enumerations, required flags
  and nested structures, and returns the documented record fields.
- **Setup Guide, Connection, WordPress API, WooCommerce API and Changelog pages** inside the
  extension.
- **Workflow-builder wording that reads like the documentation** — every operation has its own
  title, every action names the endpoint it calls, and every step field shows a readable label
  rather than the wire name.

### Security

- Credentials travel only in an HTTPS Basic `Authorization` header, never in a URL or query
  string, and never appear in an error message or log line.
- Only `https` site URLs are accepted. Redirects are refused rather than followed, so credentials
  are never forwarded to another host.
- Responses are size-bounded and upstream error bodies are classified rather than echoed.
- Undocumented fields are refused before any outbound request, including inside batch items, so a
  plugin-specific parameter such as `acf` or `lang` cannot reach the site through this extension.

### Intentionally not included

These are excluded by design in this release, not missing by accident. The
`Not available in this version` section of each API page explains every one of them, and
`contracts/rest_coverage.yaml` lists them route by route.

- **Every HTTP `DELETE`** — 34 documented delete routes across both providers. Nothing this
  extension can dispatch destroys a record.
- **Batch deletion** — a batch request creates and updates only; the native payload's `delete`
  member cannot be declared or sent.
- **Refund creation, change and deletion** — refunds move money. They can be read and previewed.
- **WordPress plugin and theme lifecycle** — installing, updating, activating, deactivating and
  deleting change the code the site runs. Plugins and themes can be listed and read.
- **WordPress Application Password management** — this extension signs in with one; it never
  creates, inspects, rotates or deletes them.
- **WooCommerce system status tool execution** — those tools change store data. The tool list and
  the status report can be read.
- **Routes outside `/wp/v2` and `/wc/v3`** — including WordPress Site Health and the Core batch
  controller.
- **WordPress resources with no official REST reference page** — global styles, navigation, menus,
  menu items, templates and template parts. This release does not guess at an undocumented
  contract.
- **Plugin functionality** — ACF, WPML, Polylang, TranslatePress, SEO plugins and the like are out
  of scope for this free extension and are planned as separate extensions that depend on it.
