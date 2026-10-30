"""`dashspec docs`: the spec reference (docs/dashboard-spec-reference.md), generated from dashboards/schema/dashboard.schema.json.
The schema says what is allowed; FIELD_DOCS says what each field means. A field without a description, or a description without a
field, fails the tests, so the reference cannot drift from the schema."""
import json
import pathlib

SCHEMA = json.loads((pathlib.Path(__file__).parent.parent / "schema" / "dashboard.schema.json").read_text())

D = {  # "<section>.<field>": meaning
    "dashboard.spec": "The spec version. Always `1`.",
    "dashboard.id": "The dashboard's id: lowercase letters, digits, `-` and `_`. It is the file name (`<id>.yml`) and the address (`/d/<id>`).",
    "dashboard.title": "The page title and the heading.",
    "dashboard.description": "One line under the title, and on the list page (`/d/`).",
    "dashboard.tags": "Up to 5 short labels for finding and grouping dashboards on the list page: lower case, 1 to 24 characters, letters (of any language), digits, spaces and hyphens, no repeats. Put the most important first. Tags are visible to everyone who can see the dashboard, so they must not carry anything sensitive.",
    "dashboard.locale": "Number and date formats, month names, and the language of the page's own words (buttons, \"All\", status): `en` and `tr` exist, any other language shows English. Default `en-US`.",
    "dashboard.currency": "The currency sign on screen and in Excel files, an ISO code such as `USD` or `TRY`. Display only: nothing is converted. Default `USD`.",
    "dashboard.roles": "Who may open the page: `admin`, `manager`, `rep`, `purchasing`, `marketing`. It decides what `/d/` lists; what each role can read is Cube's decision, and the validator rejects a page that would fail for a listed role. Default: everyone.",
    "dashboard.theme": "The dashboard's look (all optional).",
    "dashboard.time": "The time axis of the dashboard.",
    "dashboard.calculations": "Named formulas over measures, used like a measure as `calc.<id>` in any panel that takes a measure (a key figure, a series, a bar, a pie, a treemap, a table column, a pivot measure), also as the field a table or bar is sorted by. Up to 20. The formula reads in the browser on the numbers Cube returns, so it can mix measures of cubes that do not join (two fact cubes).",
    "calculation.id": "The calculation's id: lower case letters, digits and `_`. A panel uses it as `calc.<id>`.",
    "calculation.label": "The name a panel shows for it (the column heading, the legend), unless the panel gives its own `label`.",
    "calculation.formula": "`+ - * /`, brackets, numbers, measures (`cube.measure`) and `sum(a, b, ...)`, for example `sum(a.revenue, b.revenue) / sum(a.units, b.units)` or `(a.revenue + b.revenue) * 0.2` (`a` and `b` standing for cubes). A total is the formula over the totals of its parts (a ratio of sums, not an average of ratios). `+`, `-` and `sum` skip a part with no value; `*` and `/` give no value when a side has none, and `/` by zero gives none. A calculation cannot use another calculation.",
    "calculation.format": "How the value is shown wherever a panel does not say otherwise: money, int, decimal, pct, number. Default: number.",
    "dashboard.filters": "Selects above the panels. A filter applies to every panel whose measures can join to its dimension (see `ignore_filters`).",
    "dashboard.panels": "The panels, in any order; `layout` places them.",
    "dashboard.tabs": "Pages, 2 to 8, instead of `layout`: the header and the filters stay, the tab bar switches the panels below. Filters and the drill-down period are shared by all tabs; only the open tab loads its panels. `panels` stays one flat list and each panel is placed in exactly one tab. Use `layout` or `tabs`, not both.",
    "tab.id": "The tab's id, used in the address (`?tab=products`).",
    "tab.title": "The tab's name, up to 40 characters.",
    "tab.layout": "The tab's rows, as in `layout`.",
    "dashboard.layout": "Rows from top to bottom. A row is a list of `panel-id: columns` pairs that adds up to 12 (`- [trend: 8, lines: 4]`). Every panel is placed exactly once. Below 900 px every panel takes a full row. Use `layout` or `tabs`, not both.",
    "theme.name": "A small label above the title (the organisation).",
    "theme.logo": "An image in the header: a path on this site (`/assets/logo.svg`), an `https://` URL, or the image itself as `data:image/png;base64,...` (also `jpeg` or `webp`, at most 20,000 characters, about 15 KB, which leaves room for the rest of the file in the 30,000-character limit; the designer shrinks an uploaded file to fit). The bytes must really be that image type; SVG is not accepted inline.",
    "theme.colors": "Replaces theme tokens, in both the light and the dark theme.",
    "theme.colors.internet": "First series colour (and the blue in `color: internet`).",
    "theme.colors.reseller": "Second series colour (`color: reseller`).",
    "theme.colors.focus": "Selection and focus outlines, filters that are set.",
    "theme.colors.live": "The status dot when the data is current.",
    "theme.colors.good": "Positive change.",
    "theme.colors.bad": "Negative change.",
    "theme.colors.warn": "Warnings and errors.",
    "time.dimension": "The time dimension of the dashboard's fact data (for example `dates.full_date`). Time charts and KPI sparklines group by it. Must be a `time` dimension.",
    "time.fiscal_year_start": "The month a fiscal year starts (1-12), used when a click on a time chart sets a fiscal-year filter. A fiscal year is named after the year it ends in (July start: Jul 2020 is FY2021). Default 1.",
    "filter.id": "The filter's id: the URL parameter (`?fy=2021`) and what `ignore_filters` and `on_click` refer to.",
    "filter.dimension": "The Cube dimension the filter selects on (an `equals` filter on one value). Its values are read from the data.",
    "filter.label": "The label above the select. Default: the id.",
    "filter.type": "`select` (one value; the default), `multiselect` (several values, or everything except them), `text` (contains, starts with, ends with...), `number` (equals, greater than, between...) or `date` (before, after, between, and dynamic dates like `last_30_days`). `text`, `number` and `date` need a string, number and time dimension. A click rule can only set a `select` filter.",
    "filter.default": "The value the page opens with, in the form the address carries: `Bikes` for a select; `in:Bikes,Clothing`, `not:Clothing`, `contains:bike`, `gte:100`, `between:10..20`, `between:2024-01-01..2024-03-31`, `rel:last_30_days`, `set:` or `unset:` for the others. Reset goes back to it. Dynamic dates: `today`, `yesterday`, `tomorrow`, `this_`/`last_`/`next_` + `week`, `month`, `quarter`, `year` (also `fiscal_quarter`, `fiscal_year`), `week_to_date`, `month_to_date`, `quarter_to_date`, `year_to_date`, `fiscal_year_to_date`, `all_time`, and `last_N_`/`next_N_`/`past_N_` + `days`, `weeks`, `months`, `quarters`, `years` (`last_30_days` is the 30 complete days before today, `past_7_days` the 7 days ending today).",
    "filter.scope": "Where the filter applies: `dashboard` (the default: every panel on every tab, drawn in the header), `page` (one tab: drawn above that tab's panels, narrows only them; needs `tab`) or `panel` (one panel: drawn on its card, narrows only it; needs `panel`). A filter that applies to a panel is ANDed with the others that do.",
    "filter.tab": "For `scope: page`: the id of the tab the filter belongs to.",
    "filter.panel": "For `scope: panel`: the id of the panel the filter belongs to (not a text panel).",
    "filter.visible": "`true` (the default): the reader sees the filter and changes it. `false`: hidden; it always applies with its `default` and is not in the address, not cleared by Reset, and not set by clicks. **A hidden filter is not a security boundary**: its value is in the page's own queries, so anyone with the browser's developer tools can read it; who may read which data is the role rules' job in Cube.",
    "filter.parent": "A dimension that groups this filter's options (`optgroup`s). If the dashboard has a filter on that dimension, choosing a value there also narrows this filter's options.",
    "measure.member": "A single Cube measure.",
    "measure.sum": "Two or more measures added together, typically the same measure of two fact cubes (Cube cannot join two fact cubes in one query, so each is queried separately and the results added). Needs a `label`.",
    "measure.ratio": "The sum of the `num` measures divided by the sum of the `den` measures (a margin over both channels: gross profit over revenue). Needs a `label`. Format it as `pct`.",
    "measure.label": "The tile's or series' name. Default for a `member`: the measure's name, capitalised.",
    "measure.format": "How the value is shown. Default `number`.",
    "measure.rules": "Up to 4 colour rules, checked in order; the first that matches wins: `{ when: below | above | at_most | at_least, value: <number>, tone: good | warn | bad }` (for a `pct` measure the value is a fraction: `0.25` is 25%). The tone is shown as the theme's good, warning or bad colour **and** a symbol (✓ ! ✕) with a hidden text for screen readers, so colour is never the only signal.",
    "series.member": "A single Cube measure.",
    "series.sum": "Two or more measures added together (needs a `label`).",
    "series.ratio": "A ratio of sums, as for a KPI (needs a `label`).",
    "series.label": "The series' name in the legend and tooltip.",
    "series.color": "A theme token (`internet`, `reseller`, ...), a `#rrggbb` colour or nothing (a palette is used in order).",
    "series.format": "How values are shown on the axis, in the tooltip and in the Table view. Default `number`.",
    "column.member": "A Cube measure or dimension.",
    "column.label": "The column heading. Default: the member's name, capitalised.",
    "column.format": "How the value is shown. A measure defaults to `number`; a dimension is shown as text unless it has a format (a numeric dimension: `int`, or `year` for a year, which is shown without a thousands separator: 2024, not 2,024) or is a time dimension (shown as a date and time).",
    "column.aggregate": "Makes a dimension column a **value** summarised over the rows of each group, as Power BI does: `sum` and `avg` (number fields only), `max`, `min`, `count` (rows with a value), `count_distinct`, `first` and `last` (in the order of the cube's primary key). Dimension columns without it are the groups. A measure has its aggregation built in and cannot have this; all aggregated fields come from one cube, which needs a primary key; the page fetches up to 20,000 rows to aggregate and says when it reaches that. The default label is e.g. `Sum Unit cost`.",
    "column.hidden": "`true`: the field is queried but not shown (not in the table, the Excel sheet or the total row), so the table can be sorted or limited by it (`order`, `limit`): the last 20 orders by the order date, without the date column. Not together with `aggregate`; at least one column must be shown. A click on a row does not carry a hidden field.",
    "column.rules": "On a measure column of a table (not on a total row). Up to 4 colour rules, checked in order; the first that matches wins: `{ when: below | above | at_most | at_least, value: <number>, tone: good | warn | bad }` (for a `pct` measure the value is a fraction: `0.25` is 25%). The tone is shown as the theme's good, warning or bad colour **and** a symbol (✓ ! ✕) with a hidden text for screen readers, so colour is never the only signal.",
    "on_click.set_filter": "A filter id, or a list of up to two. A click on a mark sets those filters from what was clicked; a second click undoes it and restores what the filters held before. The panel that was clicked does not narrow itself with these filters. See the click rules below.",
    "panel.id": "The panel's id; `layout` and `ignore_filters` refer to it.",
    "panel.type": "`kpi`, `timeseries`, `bar`, `pie`, `treemap`, `table`, `pivot`, `text` or `slicer`.",
    "panel.title": "The card heading.",
    "panel.ignore_filters": "Filters this panel does not apply, for a panel whose measures cannot join to the filter's dimension (an inventory panel under a territory filter). The reserved id `period` is the date range a drill-down sets.",
    "kpi.time_dimension": "A time dimension of this panel's own, when it should follow another date than the dashboard's `time.dimension`: the ship date (`ship_dates.full_date`), the due date. The default is the dashboard's. A drill-down on this panel sets a period on **this date field**, which narrows the panels that use the same field and no others; the period's chip names the field. A click rule on the chart can only set a year filter of the same date field (`ship_dates.fiscal_year`). Used by the sparkline.",
    "kpi.measures": "One tile per measure, up to 8. Each tile loads on its own, so a slow measure does not hold back the others.",
    "kpi.sparkline": "A small trend line under each value, grouped by this granularity.",
    "kpi.sparkline.granularity": "The granularity of the sparkline.",
    "timeseries.cross_filter": "A click on a mark filters the other panels, **by default** (`page`: the panels of this panel's tab, or the whole dashboard when there are no tabs), with no filter to write. The page adds a filter for each field the mark carries (a bar's or pie's `by`; a treemap's groups; a table row's group columns; a pivot's first rows and plain column; a time chart's fiscal year; at most two, none of them a time field) and the panel's own click rule; a visible `select` filter that already exists on that field is used instead. `true`: every tab. `false`: this panel does not filter the others. A panel with an `on_click` of its own, a time chart that drills down, and key figures, notes and slicers are left out. A panel it cannot join to is skipped. Not together with `on_click`. The chosen values show in a bar above the panels with a remove button on each (and in the address), and a click on the chosen mark again undoes it.",
    "timeseries.time_dimension": "A time dimension of this panel's own, when it should follow another date than the dashboard's `time.dimension`: the ship date (`ship_dates.full_date`), the due date. The default is the dashboard's. A drill-down on this panel sets a period on **this date field**, which narrows the panels that use the same field and no others; the period's chip names the field. A click rule on the chart can only set a year filter of the same date field (`ship_dates.fiscal_year`).",
    "timeseries.series": "The measures drawn, one series each; measures of several cubes are queried separately and merged on the time axis.",
    "timeseries.granularity": "The time grouping: `hour`, `day`, `week`, `month`, `quarter` or `year`.",
    "timeseries.granularities": "Offers a switch between these granularities in the card header (at least two, and it must include `granularity`). Only this panel reloads.",
    "timeseries.drill": "A drill-down: the chart starts at the first level and a click on a point opens the next, finer one for that period (`[year, month, day]`; levels go from coarse to fine: year, quarter, month, week, day, hour). The click also filters every other panel to that period (they follow it unless they list `period` in `ignore_filters`), and a trail above the chart goes back up. The first level must be `granularity`; not with `granularities` or `on_click`. Years are calendar years.",
    "timeseries.style": "`line`, `area`, `stacked-area`, `bar` (grouped) or `stacked-bar`. Default `line`.",
    "timeseries.on_click": "A click on a period sets a filter on a `fiscal_year` or `calendar_year` dimension.",
    "bar.cross_filter": "A click on a mark filters the other panels, **by default** (`page`: the panels of this panel's tab, or the whole dashboard when there are no tabs), with no filter to write. The page adds a filter for each field the mark carries (a bar's or pie's `by`; a treemap's groups; a table row's group columns; a pivot's first rows and plain column; a time chart's fiscal year; at most two, none of them a time field) and the panel's own click rule; a visible `select` filter that already exists on that field is used instead. `true`: every tab. `false`: this panel does not filter the others. A panel with an `on_click` of its own, a time chart that drills down, and key figures, notes and slicers are left out. A panel it cannot join to is skipped. Not together with `on_click`. The chosen values show in a bar above the panels with a remove button on each (and in the address), and a click on the chosen mark again undoes it.",
    "bar.measure": "The measure ranked. Use this or `stack`.",
    "bar.label": "The measure's name in tooltips, the Table view and Excel (with `measure`). Default: the measure's name, capitalised (English): write it in your language.",
    "bar.by_label": "The name of the `by` dimension in the Table view and Excel. Default: the dimension's name, capitalised.",
    "bar.stack": "Two or more measures stacked in one bar (internet and reseller revenue), ranked by their total after merging the per-cube results.",
    "bar.by": "The dimension each bar stands for.",
    "bar.split": "Splits each bar by another dimension (with `measure`, not with `stack`).",
    "bar.sort": "`desc` (default) or `asc`.",
    "bar.limit": "How many bars. Default 10.",
    "bar.format": "How values are shown. Default `number`.",
    "bar.orientation": "`horizontal` (ranked rows, default) or `vertical` (columns, for a few categories).",
    "bar.on_click": "A click on a bar sets one filter, on the dimension in `by`.",
    "pie.cross_filter": "A click on a mark filters the other panels, **by default** (`page`: the panels of this panel's tab, or the whole dashboard when there are no tabs), with no filter to write. The page adds a filter for each field the mark carries (a bar's or pie's `by`; a treemap's groups; a table row's group columns; a pivot's first rows and plain column; a time chart's fiscal year; at most two, none of them a time field) and the panel's own click rule; a visible `select` filter that already exists on that field is used instead. `true`: every tab. `false`: this panel does not filter the others. A panel with an `on_click` of its own, a time chart that drills down, and key figures, notes and slicers are left out. A panel it cannot join to is skipped. Not together with `on_click`. The chosen values show in a bar above the panels with a remove button on each (and in the address), and a click on the chosen mark again undoes it.",
    "pie.measure": "The measure each slice stands for. Use this or `sum`.",
    "pie.sum": "Two or more measures added together, typically the same measure of both sales facts (each is queried separately and the slices are added up by name). Needs a `label`. Each cube contributes its top 100 slices.",
    "pie.label": "The measure's name in the tooltip, the Table view and Excel. Default: the measure's name, capitalised (English): write it in your language.",
    "pie.by_label": "The name of the `by` dimension in the Table view and Excel. Default: the dimension's name, capitalised.",
    "pie.by": "The dimension a slice stands for.",
    "pie.limit": "How many slices before the rest is grouped as one \"Other\" slice (2-30). Default 8.",
    "pie.style": "`pie` or `donut` (a ring with the total in the middle). Default `donut`.",
    "pie.format": "How values are shown. Default `number`.",
    "pie.on_click": "A click on a slice sets one filter, on the dimension in `by`; click again to undo.",
    "treemap.cross_filter": "A click on a mark filters the other panels, **by default** (`page`: the panels of this panel's tab, or the whole dashboard when there are no tabs), with no filter to write. The page adds a filter for each field the mark carries (a bar's or pie's `by`; a treemap's groups; a table row's group columns; a pivot's first rows and plain column; a time chart's fiscal year; at most two, none of them a time field) and the panel's own click rule; a visible `select` filter that already exists on that field is used instead. `true`: every tab. `false`: this panel does not filter the others. A panel with an `on_click` of its own, a time chart that drills down, and key figures, notes and slicers are left out. A panel it cannot join to is skipped. Not together with `on_click`. The chosen values show in a bar above the panels with a remove button on each (and in the address), and a click on the chosen mark again undoes it.",
    "treemap.measure": "The measure that sets each tile's area.",
    "treemap.label": "The measure's name in tooltips, the Table view and Excel. Default: the measure's name, capitalised (English).",
    "treemap.group_labels": "The names of the `group` dimensions (one per dimension) in the Table view and Excel.",
    "treemap.group": "One dimension (tiles) or two (tiles grouped under headings, as category and subcategory).",
    "treemap.format": "How values are shown. Default `number`.",
    "treemap.on_click": "A click on a tile sets the filters in `group` order (a heading sets only the first). Name the filters in the order of the group.",
    "table.cross_filter": "A click on a row filters the other panels when this is set: `page` (the panels of this panel's tab; on a dashboard without tabs use `true`) or `true` (every tab). **Off by default** for a table (its rows are details to read, and carry fields such as an order number that other panels cannot join to). There is no filter to write. The page adds a filter for each field the mark carries (every group column of the row, time fields included) and the panel's own click rule; a visible `select` filter that already exists on that field is used instead. `true`: every tab. `false`: the default. A panel with an `on_click` of its own, a time chart that drills down, and key figures, notes and slicers are left out. A panel it cannot join to is skipped. Not together with `on_click`. The chosen values show in a bar above the panels with a remove button on each (and in the address), and a click on the chosen mark again undoes it.",
    "table.columns": "The columns, up to 20: members or `{ member, label, format }`. With measures, the dimension columns are the grouping.",
    "table.order": "The order the table opens in: `{ member: asc | desc }`, members that are columns. Without it the rows are sorted by every dimension column, left to right, ascending. Viewers re-sort by clicking a column title (measures: descending, ascending, none; dimensions: ascending, descending, none; none is the dimension order above).",
    "table.limit": "How many rows. Default 100.",
    "table.totals": "`header` or `footer`: a bold total row, frozen while the rows scroll. Dimension cells are empty; each measure is aggregated over all matching rows (not only the ones shown), so a ratio is the ratio of the totals. Needs a measure column.",
    "table.on_click": "A click on a row sets each named filter from the row's value of that filter's dimension (the dimension must be one of the shown columns).",
    "pivot.rows": "One or two dimensions down the side. With two, the first groups the second: a group row with its own figures, then its rows.",
    "pivot.columns": "One dimension across the top (a different one from `rows`), or `{ member, granularity }`: a time dimension grouped by that granularity (months across, say). The first `limit.columns` values in order are shown.",
    "pivot.show": "What the cells show. `value` (default) or a share: `share_of_row` (each cell over its row's total), `share_of_column` (over its column's total), `share_of_total` (over the grand total), as percentages. A share is computed from the totals Cube returned, so `totals` must ask for the one it divides by, and every measure must be a `sum` or `count` (a ratio or a distinct count does not add up). Totals show as shares too (a row's total is 100% under `share_of_row`).",
    "pivot.heat": "`{ measure }`: shade the cells of one of the `measures` from light (the smallest cell) to strong (the largest); totals are not shaded and every cell still shows its number.",
    "pivot.measures": "One to three measures in the cells: members or `{ member, label, format }`. With several, each column shows all of them.",
    "pivot.totals": "`both` (default): a total for every row and every column, and a grand total. `rows`: only the total for every row (a last column). `columns`: only the total for every column (a last row). `none`: no totals and no group figures. Totals are asked from Cube over the whole filtered set, so a ratio is the ratio of the totals and they stay true when `limit` hides rows or columns.",
    "pivot.order": "How the rows are ordered: `{ by: total | label, dir: asc | desc }`. `total` (default, `desc`) orders by the first measure's row total; `label` orders by the row names (`asc` unless said).",
    "pivot.limit": "`{ rows, columns }`: how many rows (default 25, at most 200) and columns (default 12, at most 24) are shown. The panel says when more exist.",
    "pivot.cross_filter": "A click on a mark filters the other panels, **by default** (`page`: the panels of this panel's tab, or the whole dashboard when there are no tabs), with no filter to write. The page adds a filter for each field the mark carries (a bar's or pie's `by`; a treemap's groups; a table row's group columns; a pivot's first rows and plain column; a time chart's fiscal year; at most two, none of them a time field) and the panel's own click rule; a visible `select` filter that already exists on that field is used instead. `true`: every tab. `false`: this panel does not filter the others. A panel with an `on_click` of its own, a time chart that drills down, and key figures, notes and slicers are left out. A panel it cannot join to is skipped. Not together with `on_click`. The chosen values show in a bar above the panels with a remove button on each (and in the address), and a click on the chosen mark again undoes it.",
    "pivot.on_click": "A click on a cell sets the filters named, from the row's and the column's values (each filter's dimension must be one of `rows`, or the `columns` dimension when it is a plain dimension: a time column carries no filter; up to two filters).",
    "slicer.filter": "The id of the filter this slicer draws, in the layout instead of the header (or tab bar, or card). The filter keeps its type, scope and default and still narrows the panels it applies to; the slicer only decides where it is drawn. A filter has at most one slicer; it must be visible; a page filter's slicer sits on its own tab.",
    "slicer.display": "How a `select` or `multiselect` filter is drawn: `list` (every option shown, ticked or picked; the default), `chips` (the options as buttons) or `dropdown` (the usual control). A text, number or date filter always shows its usual control. The options are narrowed by the other filters that apply to the slicer (the dashboard's, its tab's, its own pane filters) and by a drill-down's period, never by its own filter, and a chosen value stays chosen even when the others narrow it away.",
    "text.markdown": "A short note: paragraphs, `**bold**`, `` `code` ``, `[links](https://...)` and `- ` lists. Everything else is shown as text.",
}


def _type(s, defs=SCHEMA["$defs"]):
    if "$ref" in s:
        name = s["$ref"].split("/")[-1]
        if name in ("member", "id", "hex"):
            return {"member": "member (`cube.name`)", "id": "id", "hex": "`#rrggbb`"}[name]
        if name in ("format", "granularity", "direction"):
            return " \\| ".join(f"`{v}`" for v in defs[name]["enum"])
        return "list of rules (1-4)" if name == "rules" else name
    if "const" in s:
        return f"`{s['const']}`"
    if "enum" in s:
        return " \\| ".join(f"`{v}`" for v in s["enum"])
    if "oneOf" in s:
        return " \\| ".join(_type(x, defs) for x in s["oneOf"])
    t = s.get("type", "")
    if t == "array":
        extra = f" ({s['minItems']}+)" if s.get("minItems") else ""
        return f"list of {_type(s['items'], defs)}{extra}"
    if t == "integer" and ("minimum" in s or "maximum" in s):
        return f"integer {s.get('minimum', '')}-{s.get('maximum', '')}"
    return t or "object"


def _rows(section, props, required, out, used):
    for name, s in props.items():
        key = f"{section}.{name}"
        used.add(key)
        if key not in D:
            raise KeyError(f"no description for schema field '{key}' in dashspec/docs.py")
        kind = "list of rows (lists of `{panel-id: columns}`)" if key in ("dashboard.layout", "tab.layout") else _type(s)
        out.append(f"| `{name}` | {kind} | {'yes' if name in required else ''} | {D[key]} |")


def _table(title, section, props, required, used, note=""):
    rows = []
    _rows(section, props, required, rows, used)
    return f"### {title}\n\n{note + chr(10) + chr(10) if note else ''}| Field | Type | Required | Meaning |\n|---|---|---|---|\n" + "\n".join(rows) + "\n"


def generate():
    s, defs, used = SCHEMA, SCHEMA["$defs"], set()
    out = ["# Dashboard spec reference (v1)", "",
           "Generated from [`dashboards/schema/dashboard.schema.json`](../dashboards/schema/dashboard.schema.json) by `scripts/dashspec docs`; "
           "do not edit by hand. The guide is [dashboards.md](dashboards.md).", ""]
    top = {k: v for k, v in s["properties"].items()}
    out.append(_table("The file", "dashboard", top, s["required"], used, "A dashboard is one YAML file, `dashboards/<id>.yml`."))
    tab = top["tabs"]["items"]
    out.append(_table("A tab (`tabs[]`)", "tab", tab["properties"], tab["required"], used, "A file has `layout` **or** `tabs` (2 to 8 tabs). Every panel is placed once in all, not once per tab."))
    theme = top["theme"]
    out.append(_table("`theme`", "theme", theme["properties"], [], used))
    out.append(_table("`theme.colors`", "theme.colors", theme["properties"]["colors"]["properties"], [], used, "Each value is `#rrggbb`."))
    out.append(_table("`time`", "time", top["time"]["properties"], top["time"]["required"], used))
    out.append(_table("A calculation (`calculations[]`)", "calculation", defs["calculation"]["properties"], defs["calculation"]["required"], used,
                      "A named formula over measures; a panel uses it as `calc.<id>`."))
    out.append(_table("A filter", "filter", defs["filter"]["properties"], defs["filter"]["required"], used))
    out.append(_table("A KPI measure (`kpi.measures[]`)", "measure", defs["measure"]["properties"], [], used,
                      "Exactly one of `member`, `sum` (with `label`) or `ratio` (with `label`). `ratio` is `{ num: [measures], den: [measures] }`."))
    out.append(_table("A time-chart series (`timeseries.series[]`)", "series", defs["series"]["properties"], [], used,
                      "Like a KPI measure (`member`, `sum` or `ratio`), plus a colour."))
    col = defs["column"]["anyOf"][1]
    out.append(_table("A table column (`table.columns[]`)", "column", col["properties"], col["required"], used,
                      "Either a member string, or an object with these fields."))
    out.append(_table("`on_click`", "on_click", defs["on_click"]["properties"], defs["on_click"]["required"], used))
    panel = defs["panel"]
    out.append("## Panels\n")
    out.append(_table("Every panel", "panel", panel["properties"], panel["required"], used))
    for b in panel["allOf"]:
        kind = b["if"]["properties"]["type"]["const"]
        then = b["then"]
        extra = ""
        if kind == "bar":
            extra = "Exactly one of `measure` or `stack`."
        out.append(_table(f"`{kind}`", kind, then["properties"], then.get("required", []), used, extra))
        if kind == "kpi":
            used.add("kpi.sparkline.granularity")
    out.append("""## Rules the validator enforces

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
""")
    unused = {k for k in D if k not in used}
    if unused:
        raise KeyError(f"descriptions for fields that are not in the schema: {sorted(unused)}")
    return "\n".join(out)
