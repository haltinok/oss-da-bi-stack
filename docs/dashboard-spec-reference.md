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
| `tags` | list of string |  | Up to 5 short labels for finding and grouping dashboards on the list page: lower case, 1 to 24 characters, letters (of any language), digits, spaces and hyphens, no repeats. Put the most important first. Tags are visible to everyone who can see the dashboard, so they must not carry anything sensitive. |
| `locale` | string |  | Number and date formats, month names, and the language of the page's own words (buttons, "All", status): `en` and `tr` exist, any other language shows English. Default `en-US`. |
| `currency` | string |  | The currency sign on screen and in Excel files, an ISO code such as `USD` or `TRY`. Display only: nothing is converted. Default `USD`. |
| `roles` | list of `admin` \| `manager` \| `rep` \| `purchasing` \| `marketing` (1+) |  | Who may open the page: `admin`, `manager`, `rep`, `purchasing`, `marketing`. It decides what `/d/` lists; what each role can read is Cube's decision, and the validator rejects a page that would fail for a listed role. Default: everyone. |
| `theme` | object |  | The dashboard's look (all optional). |
| `time` | object | yes | The time axis of the dashboard. |
| `filters` | list of filter |  | Selects above the panels. A filter applies to every panel whose measures can join to its dimension (see `ignore_filters`). |
| `panels` | list of panel (1+) | yes | The panels, in any order; `layout` places them. |
| `layout` | list of rows (lists of `{panel-id: columns}`) |  | Rows from top to bottom. A row is a list of `panel-id: columns` pairs that adds up to 12 (`- [trend: 8, lines: 4]`). Every panel is placed exactly once. Below 900 px every panel takes a full row. Use `layout` or `tabs`, not both. |
| `tabs` | list of object (2+) |  | Pages, 2 to 8, instead of `layout`: the header and the filters stay, the tab bar switches the panels below. Filters and the drill-down period are shared by all tabs; only the open tab loads its panels. `panels` stays one flat list and each panel is placed in exactly one tab. Use `layout` or `tabs`, not both. |

### A tab (`tabs[]`)

A file has `layout` **or** `tabs` (2 to 8 tabs). Every panel is placed once in all, not once per tab.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | id | yes | The tab's id, used in the address (`?tab=products`). |
| `title` | string | yes | The tab's name, up to 40 characters. |
| `layout` | list of rows (lists of `{panel-id: columns}`) | yes | The tab's rows, as in `layout`. |

### `theme`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `name` | string |  | A small label above the title (the organisation). |
| `logo` | string |  | An image in the header: a path on this site (`/assets/logo.svg`), an `https://` URL, or the image itself as `data:image/png;base64,...` (also `jpeg` or `webp`, at most 20,000 characters, about 15 KB, which leaves room for the rest of the file in the 30,000-character limit; the designer shrinks an uploaded file to fit). The bytes must really be that image type; SVG is not accepted inline. |
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
| `type` | `select` \| `multiselect` \| `text` \| `number` \| `date` |  | `select` (one value; the default), `multiselect` (several values, or everything except them), `text` (contains, starts with, ends with...), `number` (equals, greater than, between...) or `date` (before, after, between, and dynamic dates like `last_30_days`). `text`, `number` and `date` need a string, number and time dimension. A click rule can only set a `select` filter. |
| `default` | string |  | The value the page opens with, in the form the address carries: `Bikes` for a select; `in:Bikes,Clothing`, `not:Clothing`, `contains:bike`, `gte:100`, `between:10..20`, `between:2024-01-01..2024-03-31`, `rel:last_30_days`, `set:` or `unset:` for the others. Reset goes back to it. Dynamic dates: `today`, `yesterday`, `tomorrow`, `this_`/`last_`/`next_` + `week`, `month`, `quarter`, `year` (also `fiscal_quarter`, `fiscal_year`), `week_to_date`, `month_to_date`, `quarter_to_date`, `year_to_date`, `fiscal_year_to_date`, `all_time`, and `last_N_`/`next_N_`/`past_N_` + `days`, `weeks`, `months`, `quarters`, `years` (`last_30_days` is the 30 complete days before today, `past_7_days` the 7 days ending today). |
| `scope` | `dashboard` \| `page` \| `panel` |  | Where the filter applies: `dashboard` (the default: every panel on every tab, drawn in the header), `page` (one tab: drawn above that tab's panels, narrows only them; needs `tab`) or `panel` (one panel: drawn on its card, narrows only it; needs `panel`). A filter that applies to a panel is ANDed with the others that do. |
| `tab` | id |  | For `scope: page`: the id of the tab the filter belongs to. |
| `panel` | id |  | For `scope: panel`: the id of the panel the filter belongs to (not a text panel). |
| `visible` | boolean |  | `true` (the default): the reader sees the filter and changes it. `false`: hidden; it always applies with its `default` and is not in the address, not cleared by Reset, and not set by clicks. **A hidden filter is not a security boundary**: its value is in the page's own queries, so anyone with the browser's developer tools can read it; who may read which data is the role rules' job in Cube. |
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
| `rules` | list of rules (1-4) |  | Up to 4 colour rules, checked in order; the first that matches wins: `{ when: below | above | at_most | at_least, value: <number>, tone: good | warn | bad }` (for a `pct` measure the value is a fraction: `0.25` is 25%). The tone is shown as the theme's good, warning or bad colour **and** a symbol (✓ ! ✕) with a hidden text for screen readers, so colour is never the only signal. |

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
| `aggregate` | aggregate |  | Makes a dimension column a **value** summarised over the rows of each group, as Power BI does: `sum` and `avg` (number fields only), `max`, `min`, `count` (rows with a value), `count_distinct`, `first` and `last` (in the order of the cube's primary key). Dimension columns without it are the groups. A measure has its aggregation built in and cannot have this; all aggregated fields come from one cube, which needs a primary key; the page fetches up to 20,000 rows to aggregate and says when it reaches that. The default label is e.g. `Sum Unit cost`. |
| `rules` | list of rules (1-4) |  | On a measure column of a table (not on a total row). Up to 4 colour rules, checked in order; the first that matches wins: `{ when: below | above | at_most | at_least, value: <number>, tone: good | warn | bad }` (for a `pct` measure the value is a fraction: `0.25` is 25%). The tone is shown as the theme's good, warning or bad colour **and** a symbol (✓ ! ✕) with a hidden text for screen readers, so colour is never the only signal. |

### `on_click`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `set_filter` | id \| list of id (1+) | yes | A filter id, or a list of up to two. A click on a mark sets those filters from what was clicked; a second click undoes it and restores what the filters held before. The panel that was clicked does not narrow itself with these filters. See the click rules below. |

## Panels

### Every panel

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | id | yes | The panel's id; `layout` and `ignore_filters` refer to it. |
| `type` | `kpi` \| `timeseries` \| `bar` \| `pie` \| `treemap` \| `table` \| `pivot` \| `text` \| `slicer` | yes | `kpi`, `timeseries`, `bar`, `pie`, `treemap`, `table`, `pivot`, `text` or `slicer`. |
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
| `cross_filter` | cross_filter |  | `true`: a click on a mark filters the other panels, with no filter to write. The page adds a filter for each field the mark carries (the bar's or pie's `by`; a treemap's group; a table row's dimension columns, at most two) and the panel's own click rule; a visible `select` filter that already exists on that field is used instead. `page` (needs `tabs`): only the panels of this panel's tab are filtered. A panel it cannot join to is skipped. Not together with `on_click`. The chosen values show in a bar above the panels with a remove button on each (and in the address), and a click on the chosen mark again undoes it. |
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
| `cross_filter` | cross_filter |  | `true`: a click on a mark filters the other panels, with no filter to write. The page adds a filter for each field the mark carries (the bar's or pie's `by`; a treemap's group; a table row's dimension columns, at most two) and the panel's own click rule; a visible `select` filter that already exists on that field is used instead. `page` (needs `tabs`): only the panels of this panel's tab are filtered. A panel it cannot join to is skipped. Not together with `on_click`. The chosen values show in a bar above the panels with a remove button on each (and in the address), and a click on the chosen mark again undoes it. |
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
| `cross_filter` | cross_filter |  | `true`: a click on a mark filters the other panels, with no filter to write. The page adds a filter for each field the mark carries (the bar's or pie's `by`; a treemap's group; a table row's dimension columns, at most two) and the panel's own click rule; a visible `select` filter that already exists on that field is used instead. `page` (needs `tabs`): only the panels of this panel's tab are filtered. A panel it cannot join to is skipped. Not together with `on_click`. The chosen values show in a bar above the panels with a remove button on each (and in the address), and a click on the chosen mark again undoes it. |
| `measure` | member (`cube.name`) | yes | The measure that sets each tile's area. |
| `label` | string |  | The measure's name in tooltips, the Table view and Excel. Default: the measure's name, capitalised (English). |
| `group` | list of member (`cube.name`) (1+) | yes | One dimension (tiles) or two (tiles grouped under headings, as category and subcategory). |
| `group_labels` | list of string (1+) |  | The names of the `group` dimensions (one per dimension) in the Table view and Excel. |
| `format` | `money` \| `int` \| `decimal` \| `pct` \| `number` |  | How values are shown. Default `number`. |
| `on_click` | on_click |  | A click on a tile sets the filters in `group` order (a heading sets only the first). Name the filters in the order of the group. |

### `table`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `cross_filter` | cross_filter |  | `true`: a click on a mark filters the other panels, with no filter to write. The page adds a filter for each field the mark carries (the bar's or pie's `by`; a treemap's group; a table row's dimension columns, at most two) and the panel's own click rule; a visible `select` filter that already exists on that field is used instead. `page` (needs `tabs`): only the panels of this panel's tab are filtered. A panel it cannot join to is skipped. Not together with `on_click`. The chosen values show in a bar above the panels with a remove button on each (and in the address), and a click on the chosen mark again undoes it. |
| `columns` | list of column (1+) | yes | The columns, up to 20: members or `{ member, label, format }`. With measures, the dimension columns are the grouping. |
| `order` | object |  | The order the table opens in: `{ member: asc | desc }`, members that are columns. Without it the rows are sorted by every dimension column, left to right, ascending. Viewers re-sort by clicking a column title (measures: descending, ascending, none; dimensions: ascending, descending, none; none is the dimension order above). |
| `limit` | integer 1-1000 |  | How many rows. Default 100. |
| `totals` | `header` \| `footer` |  | `header` or `footer`: a bold total row, frozen while the rows scroll. Dimension cells are empty; each measure is aggregated over all matching rows (not only the ones shown), so a ratio is the ratio of the totals. Needs a measure column. |
| `on_click` | on_click |  | A click on a row sets each named filter from the row's value of that filter's dimension (the dimension must be one of the shown columns). |

### `pivot`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `rows` | list of member (`cube.name`) (1+) | yes | One or two dimensions down the side. With two, the first groups the second: a group row with its own figures, then its rows. |
| `columns` | member (`cube.name`) \| object | yes | One dimension across the top (a different one from `rows`), or `{ member, granularity }`: a time dimension grouped by that granularity (months across, say). The first `limit.columns` values in order are shown. |
| `measures` | list of column (1+) | yes | One to three measures in the cells: members or `{ member, label, format }`. With several, each column shows all of them. |
| `show` | `value` \| `share_of_row` \| `share_of_column` \| `share_of_total` |  | What the cells show. `value` (default) or a share: `share_of_row` (each cell over its row's total), `share_of_column` (over its column's total), `share_of_total` (over the grand total), as percentages. A share is computed from the totals Cube returned, so `totals` must ask for the one it divides by, and every measure must be a `sum` or `count` (a ratio or a distinct count does not add up). Totals show as shares too (a row's total is 100% under `share_of_row`). |
| `heat` | object |  | `{ measure }`: shade the cells of one of the `measures` from light (the smallest cell) to strong (the largest); totals are not shaded and every cell still shows its number. |
| `totals` | `both` \| `rows` \| `columns` \| `none` |  | `both` (default): a total for every row and every column, and a grand total. `rows`: only the total for every row (a last column). `columns`: only the total for every column (a last row). `none`: no totals and no group figures. Totals are asked from Cube over the whole filtered set, so a ratio is the ratio of the totals and they stay true when `limit` hides rows or columns. |
| `order` | object |  | How the rows are ordered: `{ by: total | label, dir: asc | desc }`. `total` (default, `desc`) orders by the first measure's row total; `label` orders by the row names (`asc` unless said). |
| `limit` | object |  | `{ rows, columns }`: how many rows (default 25, at most 200) and columns (default 12, at most 24) are shown. The panel says when more exist. |
| `on_click` | on_click |  | A click on a cell sets the filters named, from the row's and the column's values (each filter's dimension must be one of `rows`, or the `columns` dimension when it is a plain dimension: a time column carries no filter; up to two filters). |

### `slicer`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `filter` | id | yes | The id of the filter this slicer draws, in the layout instead of the header (or tab bar, or card). The filter keeps its type, scope and default and still narrows the panels it applies to; the slicer only decides where it is drawn. A filter has at most one slicer; it must be visible; a page filter's slicer sits on its own tab. |
| `display` | `list` \| `chips` \| `dropdown` |  | How a `select` or `multiselect` filter is drawn: `list` (every option shown, ticked or picked; the default), `chips` (the options as buttons) or `dropdown` (the usual control). A text, number or date filter always shows its usual control. The options are narrowed by the other filters that apply to the slicer (the dashboard's, its tab's, its own pane filters) and by a drill-down's period, never by its own filter, and a chosen value stays chosen even when the others narrow it away. |

### `text`

| Field | Type | Required | Meaning |
|---|---|---|---|
| `markdown` | string | yes | A short note: paragraphs, `**bold**`, `` `code` ``, `[links](https://...)` and `- ` lists. Everything else is shown as text. |

## Rules the validator enforces

- Every member exists in the Cube model, a measure is used as a measure and a dimension as a dimension, `time.dimension` is a time dimension.
- Filter ids, panel ids and layout cells are unique and refer to things that exist; every layout row adds up to 12; every panel is placed once (across all the tabs, when there are tabs; a tab id is used once).
- A measure is only combined with dimensions its cube can join to (including the filters it applies): otherwise add the filter to `ignore_filters`.
- **Click rules:** a bar sets a filter on its `by` (one filter); a treemap's filters follow its `group` in order; a table row sets filters on the
  dimension columns it shows; a pivot cell sets filters on its `rows` and `columns` dimensions; a time chart sets a filter on a `fiscal_year` or `calendar_year` dimension (one filter).
- `granularities` contains `granularity`; a `stack` is not combined with `split`.
- **Roles:** a role in `roles` must be able to read every member the page uses: `rep` has no profit or margin members (`gross_profit`,
  `margin_pct`, `product_cost`); `purchasing` and `marketing` read inventory data only (`inventory_health`, `offer_performance` for marketing,
  and `products`), `marketing` no supplier or order members; `manager` and `rep` no inventory data and nobody but `admin` customer data.
  These rules mirror `cube/cube.js`; a test keeps them equal.
