# Dashboard spec reference (v1)

Generated from [`dashboards/schema/dashboard.schema.json`](../dashboards/schema/dashboard.schema.json) by `scripts/dashspec docs`; do not edit by hand. The guide is [dashboards.md](dashboards.md).

### The file

A dashboard is one YAML file, `dashboards/<id>.yml`.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `spec` | `1` | yes | The spec version. Always `1`. |
| `id` | id | yes | The dashboard's id: lowercase letters, digits, `-` and `_`. It is the file name (`<id>.yml`) and the address (`/d/<id>`). |
| `title` | string | yes | The page title and the heading. |
| `description` | string |  | One line under the title, and on the list page (`/d/`). |
| `locale` | string |  | Number and date formats, month names, and the language of the page's own words (buttons, "All", status): `en` and `tr` exist, any other language shows English. Default `en-US`. |
| `currency` | string |  | The currency sign on screen and in Excel files, an ISO code such as `USD` or `TRY`. Display only: nothing is converted. Default `USD`. |
| `roles` | list of `admin` \| `manager` \| `rep` \| `purchasing` \| `marketing` (1+) |  | Who may open the page: `admin`, `manager`, `rep`, `purchasing`, `marketing`. It decides what `/d/` lists; what each role can read is Cube's decision, and the validator rejects a page that would fail for a listed role. Default: everyone. |
| `theme` | object |  | The dashboard's look (all optional). |
| `time` | object | yes | The time axis of the dashboard. |
| `filters` | list of filter |  | Selects above the panels. A filter applies to every panel whose measures can join to its dimension (see `ignore_filters`). |
| `panels` | list of panel (1+) | yes | The panels, in any order; `layout` places them. |
| `layout` | list of rows (lists of `{panel-id: columns}`) | yes | Rows from top to bottom. A row is a list of `panel-id: columns` pairs that adds up to 12 (`- [trend: 8, lines: 4]`). Every panel is placed exactly once. Below 900 px every panel takes a full row. |

### `theme`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `name` | string |  | A small label above the title (the organisation). |
| `logo` | string |  | An image in the header: a path on this site (`/assets/logo.svg`) or an `https://` URL. |
| `colors` | object |  | Replaces theme tokens, in both the light and the dark theme. |

### `theme.colors`

Each value is `#rrggbb`.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `internet` | `#rrggbb` |  | First series colour (and the blue in `color: internet`). |
| `reseller` | `#rrggbb` |  | Second series colour (`color: reseller`). |
| `focus` | `#rrggbb` |  | Selection and focus outlines, filters that are set. |
| `live` | `#rrggbb` |  | The status dot when the data is current. |
| `good` | `#rrggbb` |  | Positive change. |
| `bad` | `#rrggbb` |  | Negative change. |
| `warn` | `#rrggbb` |  | Warnings and errors. |

### `time`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `dimension` | member (`cube.name`) | yes | The time dimension of the dashboard's fact data (for example `dates.full_date`). Time charts and KPI sparklines group by it. Must be a `time` dimension. |
| `fiscal_year_start` | integer 1-12 |  | The month a fiscal year starts (1-12), used when a click on a time chart sets a fiscal-year filter. A fiscal year is named after the year it ends in (July start: Jul 2020 is FY2021). Default 1. |

### A filter

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | id | yes | The filter's id: the URL parameter (`?fy=2021`) and what `ignore_filters` and `on_click` refer to. |
| `dimension` | member (`cube.name`) | yes | The Cube dimension the filter selects on (an `equals` filter on one value). Its values are read from the data. |
| `label` | string |  | The label above the select. Default: the id. |
| `parent` | member (`cube.name`) |  | A dimension that groups this filter's options (`optgroup`s). If the dashboard has a filter on that dimension, choosing a value there also narrows this filter's options. |

### A KPI measure (`kpi.measures[]`)

Exactly one of `member`, `sum` (with `label`) or `ratio` (with `label`). `ratio` is `{ num: [measures], den: [measures] }`.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `member` | member (`cube.name`) |  | A single Cube measure. |
| `sum` | list of member (`cube.name`) (2+) |  | Two or more measures added together, typically the same measure of two fact cubes (Cube cannot join two fact cubes in one query, so each is queried separately and the results added). Needs a `label`. |
| `ratio` | object |  | The sum of the `num` measures divided by the sum of the `den` measures (a margin over both channels: gross profit over revenue). Needs a `label`. Format it as `pct`. |
| `label` | string |  | The tile's or series' name. Default for a `member`: the measure's name, capitalised. |
| `format` | `money` \| `int` \| `decimal` \| `pct` \| `number` |  | How the value is shown. Default `number`. |

### A time-chart series (`timeseries.series[]`)

Like a KPI measure (`member`, `sum` or `ratio`), plus a colour.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `member` | member (`cube.name`) |  | A single Cube measure. |
| `sum` | list of member (`cube.name`) (2+) |  | Two or more measures added together (needs a `label`). |
| `ratio` | ratio |  | A ratio of sums, as for a KPI (needs a `label`). |
| `label` | string |  | The series' name in the legend and tooltip. |
| `color` | string |  | A theme token (`internet`, `reseller`, ...), a `#rrggbb` colour or nothing (a palette is used in order). |
| `format` | `money` \| `int` \| `decimal` \| `pct` \| `number` |  | How values are shown on the axis, in the tooltip and in the Table view. Default `number`. |

### A table column (`table.columns[]`)

Either a member string, or an object with these fields.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `member` | member (`cube.name`) | yes | A Cube measure or dimension. |
| `label` | string |  | The column heading. Default: the member's name, capitalised. |
| `format` | `money` \| `int` \| `decimal` \| `pct` \| `number` |  | How the value is shown. A measure defaults to `number`; a dimension is shown as text unless it has a format (a numeric dimension, `int`) or is a time dimension (shown as a date and time). |

### `on_click`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `set_filter` | object | yes | A filter id, or a list of up to two. A click on a mark sets those filters from what was clicked; a second click undoes it and restores what the filters held before. The panel that was clicked does not narrow itself with these filters. See the click rules below. |

## Panels

### Every panel

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | id | yes | The panel's id; `layout` and `ignore_filters` refer to it. |
| `type` | `kpi` \| `timeseries` \| `bar` \| `pie` \| `treemap` \| `table` \| `pivot` \| `text` | yes | `kpi`, `timeseries`, `bar`, `pie`, `treemap`, `table`, `pivot` or `text`. |
| `title` | string |  | The card heading. |
| `ignore_filters` | list of id |  | Filters this panel does not apply, for a panel whose measures cannot join to the filter's dimension (an inventory panel under a territory filter). The reserved id `period` is the date range a drill-down sets. |

### `kpi`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `measures` | list of measure (1+) | yes | One tile per measure, up to 8. Each tile loads on its own, so a slow measure does not hold back the others. |
| `sparkline` | object |  | A small trend line under each value, grouped by this granularity. |

### `timeseries`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `series` | list of series (1+) | yes | The measures drawn, one series each; measures of several cubes are queried separately and merged on the time axis. |
| `granularity` | `hour` \| `day` \| `week` \| `month` \| `quarter` \| `year` | yes | The time grouping: `hour`, `day`, `week`, `month`, `quarter` or `year`. |
| `granularities` | list of `hour` \| `day` \| `week` \| `month` \| `quarter` \| `year` (2+) |  | Offers a switch between these granularities in the card header (at least two, and it must include `granularity`). Only this panel reloads. |
| `drill` | list of `hour` \| `day` \| `week` \| `month` \| `quarter` \| `year` (2+) |  | A drill-down: the chart starts at the first level and a click on a point opens the next, finer one for that period (`[year, month, day]`; levels go from coarse to fine: year, quarter, month, week, day, hour). The click also filters every other panel to that period (they follow it unless they list `period` in `ignore_filters`), and a trail above the chart goes back up. The first level must be `granularity`; not with `granularities` or `on_click`. Years are calendar years. |
| `style` | `line` \| `area` \| `stacked-area` \| `bar` \| `stacked-bar` |  | `line`, `area`, `stacked-area`, `bar` (grouped) or `stacked-bar`. Default `line`. |
| `on_click` | on_click |  | A click on a period sets a filter on a `fiscal_year` or `calendar_year` dimension. |

### `bar`

Exactly one of `measure` or `stack`.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `measure` | member (`cube.name`) |  | The measure ranked. Use this or `stack`. |
| `label` | string |  | The measure's name in tooltips, the Table view and Excel (with `measure`). Default: the measure's name, capitalised (English): write it in your language. |
| `by_label` | string |  | The name of the `by` dimension in the Table view and Excel. Default: the dimension's name, capitalised. |
| `stack` | list of object (2+) |  | Two or more measures stacked in one bar (internet and reseller revenue), ranked by their total after merging the per-cube results. |
| `by` | member (`cube.name`) | yes | The dimension each bar stands for. |
| `split` | member (`cube.name`) |  | Splits each bar by another dimension (with `measure`, not with `stack`). |
| `sort` | `asc` \| `desc` |  | `desc` (default) or `asc`. |
| `limit` | integer 1-1000 |  | How many bars. Default 10. |
| `orientation` | `horizontal` \| `vertical` |  | `horizontal` (ranked rows, default) or `vertical` (columns, for a few categories). |
| `format` | `money` \| `int` \| `decimal` \| `pct` \| `number` |  | How values are shown. Default `number`. |
| `on_click` | on_click |  | A click on a bar sets one filter, on the dimension in `by`. |

### `pie`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `measure` | member (`cube.name`) |  | The measure each slice stands for. Use this or `sum`. |
| `sum` | list of member (`cube.name`) (2+) |  | Two or more measures added together, typically the same measure of both sales facts (each is queried separately and the slices are added up by name). Needs a `label`. Each cube contributes its top 100 slices. |
| `label` | string |  | The measure's name in the tooltip, the Table view and Excel. Default: the measure's name, capitalised (English): write it in your language. |
| `by` | member (`cube.name`) | yes | The dimension a slice stands for. |
| `by_label` | string |  | The name of the `by` dimension in the Table view and Excel. Default: the dimension's name, capitalised. |
| `limit` | integer 2-30 |  | How many slices before the rest is grouped as one "Other" slice (2-30). Default 8. |
| `style` | `pie` \| `donut` |  | `pie` or `donut` (a ring with the total in the middle). Default `donut`. |
| `format` | `money` \| `int` \| `decimal` \| `pct` \| `number` |  | How values are shown. Default `number`. |
| `on_click` | on_click |  | A click on a slice sets one filter, on the dimension in `by`; click again to undo. |

### `treemap`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `measure` | member (`cube.name`) | yes | The measure that sets each tile's area. |
| `label` | string |  | The measure's name in tooltips, the Table view and Excel. Default: the measure's name, capitalised (English). |
| `group` | list of member (`cube.name`) (1+) | yes | One dimension (tiles) or two (tiles grouped under headings, as category and subcategory). |
| `group_labels` | list of string (1+) |  | The names of the `group` dimensions (one per dimension) in the Table view and Excel. |
| `format` | `money` \| `int` \| `decimal` \| `pct` \| `number` |  | How values are shown. Default `number`. |
| `on_click` | on_click |  | A click on a tile sets the filters in `group` order (a heading sets only the first). Name the filters in the order of the group. |

### `table`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `columns` | list of column (1+) | yes | The columns, up to 20: members or `{ member, label, format }`. With measures, the dimension columns are the grouping. |
| `order` | object |  | The order the table opens in: `{ member: asc | desc }`, members that are columns. Without it the rows are sorted by every dimension column, left to right, ascending. Viewers re-sort by clicking a column title (measures: descending, ascending, none; dimensions: ascending, descending, none; none is the dimension order above). |
| `limit` | integer 1-1000 |  | How many rows. Default 100. |
| `totals` | `header` \| `footer` |  | `header` or `footer`: a bold total row, frozen while the rows scroll. Dimension cells are empty; each measure is aggregated over all matching rows (not only the ones shown), so a ratio is the ratio of the totals. Needs a measure column. |
| `on_click` | on_click |  | A click on a row sets each named filter from the row's value of that filter's dimension (the dimension must be one of the shown columns). |

### `pivot`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `rows` | list of member (`cube.name`) (1+) | yes | One or two dimensions down the side. With two, the first groups the second: a group row with its own figures, then its rows. |
| `columns` | member (`cube.name`) | yes | One dimension across the top (a different one from `rows`). The first `limit.columns` values by name are shown. |
| `measures` | list of column (1+) | yes | One to three measures in the cells: members or `{ member, label, format }`. With several, each column shows all of them. |
| `totals` | `both` \| `rows` \| `columns` \| `none` |  | `both` (default): a total for every row and every column, and a grand total. `rows`: only the total for every row (a last column). `columns`: only the total for every column (a last row). `none`: no totals and no group figures. Totals are asked from Cube over the whole filtered set, so a ratio is the ratio of the totals and they stay true when `limit` hides rows or columns. |
| `order` | object |  | How the rows are ordered: `{ by: total | label, dir: asc | desc }`. `total` (default, `desc`) orders by the first measure's row total; `label` orders by the row names (`asc` unless said). |
| `limit` | object |  | `{ rows, columns }`: how many rows (default 25, at most 200) and columns (default 12, at most 24) are shown. The panel says when more exist. |
| `on_click` | on_click |  | A click on a cell sets the filters named, from the row's and the column's values (each filter's dimension must be one of `rows` or `columns`; up to two filters). |

### `text`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `markdown` | string | yes | A short note: paragraphs, `**bold**`, `` `code` ``, `[links](https://...)` and `- ` lists. Everything else is shown as text. |

## Rules the validator enforces

- Every member exists in the Cube model, a measure is used as a measure and a dimension as a dimension, `time.dimension` is a time dimension.
- Filter ids, panel ids and layout cells are unique and refer to things that exist; every layout row adds up to 12; every panel is placed once.
- A measure is only combined with dimensions its cube can join to (including the filters it applies): otherwise add the filter to `ignore_filters`.
- **Click rules:** a bar sets a filter on its `by` (one filter); a treemap's filters follow its `group` in order; a table row sets filters on the
  dimension columns it shows; a pivot cell sets filters on its `rows` and `columns` dimensions; a time chart sets a filter on a `fiscal_year` or `calendar_year` dimension (one filter).
- `granularities` contains `granularity`; a `stack` is not combined with `split`.
- **Roles:** a role in `roles` must be able to read every member the page uses: `rep` has no profit or margin members (`gross_profit`,
  `margin_pct`, `product_cost`); `purchasing` and `marketing` read inventory data only (`inventory_health`, `offer_performance` for marketing,
  and `products`), `marketing` no supplier or order members; `manager` and `rep` no inventory data and nobody but `admin` customer data.
  These rules mirror `cube/cube.js`; a test keeps them equal.
