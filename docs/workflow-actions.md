# WordPress and WooCommerce workflow actions

Select a project **WordPress site** connection on each action. Configure the
public HTTPS site base URL, WordPress username and that user's Application
Password. For store actions, also add the site's WooCommerce consumer key and
secret with the required read/write access. Run **Test the connection** first;
it reports WordPress and WooCommerce separately. See the extension's Setup Guide
for the complete connection procedure.

Action IDs below identify existing workflow actions. Examples show action inputs;
select the connection in the builder, and bind real IDs and files from earlier
steps. These examples do not supply or change defaults.

## Publish approved content

1. Choose **Create a post** (`wp_create_post`), set **Title** to
   `Summer collection`, **Content** to `<p>Explore our summer collection.</p>`,
   and **Status** to `draft` for review.
2. Save the returned post ID. After approval, choose **Update a post**
   (`wp_update_post`) with that ID and **Status** `publish`.
3. To include an image, run **Upload a media file** (`wp_create_media`) first.
   Bind the file handle from an earlier file-producing step, use filename
   `blue-mug.jpg`, MIME type `image/jpeg` and meaningful alt text. Bind its returned
   media ID to **Featured media** on the post. A URL or local path is not a file
   handle. The upload does not resize or convert the image.

The page and reusable-block families follow the same create/read/update pattern.
Revisions and autosaves address a parent content item plus its revision ID when
required. Search finds content; it does not publish it. Moderating comments uses
**Update a comment** and a supported status such as `approved` or `hold`.

## Update a store product's price and stock

1. Use **List products** (`wc_list_products`) with **SKU** `MUG-BLUE-01`.
   Read the matching product's numeric ID from the result.
2. Run **Update a product** (`wc_update_product`) with that ID and the fields:

   ```json
   {"regular_price":"19.90","manage_stock":true,"stock_quantity":24}
   ```

   Prices are decimal strings in the store currency. Stock quantity is an
   absolute count. Omitted update fields keep their native current values.
3. Read the product again to check the saved state. Variation actions need the
   parent product ID and the variation ID, not an SKU in an ID field.

For multiple existing products, **Create or update several products** (`wc_batch_products`) accepts
**Update items** such as:

```json
[{"id":1042,"regular_price":"19.90"},{"id":1043,"regular_price":"24.90"}]
```

Replace example IDs with IDs from this store. Create items use the corresponding
resource's create fields. Inspect each returned batch member for errors; the
batch is not a promise that every entry succeeded. Batch capabilities vary by
resource, and setting-option batches only update existing settings.

## Export records and continue through lists

Native list actions return one page. **Page** starts at 1; **Per page** controls
that page's size. Follow the returned pagination with the same connection and
filters until there are no more pages. **Include** and **Exclude** are JSON
arrays of numeric record IDs, for example `[1042,1043]`.

For a complete product file choose **Export every matching WooCommerce product**
(`wc_export_products`). For example, filter **SKU** to `MUG-BLUE-01`, or leave
filters empty for the full matching catalog. The export follows all matching
pages and returns a JSONL file handle and item count for later workflow steps.
It does not take a starting page or offset.

## Choose the resource family

| Need | Actions and input meaning |
| --- | --- |
| Publish content or maintain taxonomy | WordPress posts, pages, categories, tags and blocks. Existing IDs come from their own list or lookup actions. |
| Maintain store catalog | WooCommerce products, variations, categories, attributes, terms, tags, shipping classes and reviews. Nested actions also require their parent IDs. |
| Process orders and customers | Read/create/update orders, order notes, customers and coupons using the typed fields in the form. Setting an order paid can trigger WooCommerce payment-complete behavior. |
| Notify a customer | Dedicated order email actions send real email. Supply the order ID and, where offered, a template ID from the store. |
| Inspect refunds | Read or preview supported refunds. A refund preview does not create a refund. |
| Inspect site/store setup | Supported settings, reports, shipping, tax and reference actions use their own named fields. Read-only reference actions do not alter configuration. |

Write actions use the connection's permissions and are suppressed in test mode.
If a dispatched write times out with an unknown outcome, inspect the site before
repeating it. The in-app WordPress API and WooCommerce API pages describe every
operation's required inputs, returned fields and endpoint-specific limitations.
