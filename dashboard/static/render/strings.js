// The page's own words, per language (the language of the spec's `locale`, English when there is no translation). The words in a dashboard
// (titles, labels, descriptions) are the author's and are not translated here.
const EN = {
  tones: { good: "good", warn: "warning", bad: "bad" },
  fc: {"any": "Any", "and": "and", "search": "Search…", "selectAll": "Select all shown", "clear": "Clear", "exclude": "All except the selected", "ops": {"contains": "contains", "not_contains": "does not contain", "starts": "starts with", "ends": "ends with", "eq": "equals", "ne": "does not equal", "gt": "is greater than", "gte": "is greater than or equal to", "lt": "is less than", "lte": "is less than or equal to", "between": "is between", "on": "is on", "after": "is after", "on_or_after": "is on or after", "before": "is before", "on_or_before": "is on or before", "rel": "is in the period", "set": "is not empty", "unset": "is empty"}, "presets": {"today": "Today", "yesterday": "Yesterday", "tomorrow": "Tomorrow", "this_week": "This week", "last_week": "Last week", "next_week": "Next week", "this_month": "This month", "last_month": "Last month", "next_month": "Next month", "this_quarter": "This quarter", "last_quarter": "Last quarter", "next_quarter": "Next quarter", "this_year": "This year", "last_year": "Last year", "next_year": "Next year", "week_to_date": "Week to date", "month_to_date": "Month to date", "quarter_to_date": "Quarter to date", "year_to_date": "Year to date", "this_fiscal_quarter": "This fiscal quarter", "last_fiscal_quarter": "Last fiscal quarter", "this_fiscal_year": "This fiscal year", "last_fiscal_year": "Last fiscal year", "fiscal_year_to_date": "Fiscal year to date", "all_time": "All time"}, "counted": {"last": "Last N…", "next": "Next N…", "past": "Past N (up to today)…"}, "count": "Number", "unit": "Unit", "units": {"days": "days", "weeks": "weeks", "months": "months", "quarters": "quarters", "years": "years"}, nSelected: (n) => `${n} selected`, nExcept: (n) => `all but ${n}`, more: (n) => `${n} more: type to search`},
  sparkAria: (label, gran, bucket, value) => `${label} by ${gran}, latest ${bucket}: ${value}`, seriesAria: (labels, gran) => `${labels} by ${gran}`,
  tabsLabel: "Tabs", languageLabel: "Language", dateLocale: "en-US", connecting: "Connecting…", datasetLabel: "Dataset", themeToggle: "Theme", notLoaded: "not loaded",
  datasetTitle: (label, mart) => `Dataset: ${label} (${mart})`, signedInAs: (user, role) => `Signed in as ${user}, role ${role}`,
  all: "All", reset: "Reset filters", table: "Table", totals: "Totals", excel: "Excel", exportAll: "Export all", refresh: "Refresh", loading: "Loading…",
  updated: "Updated", stale: "Stale", couldNotLoad: "could not load", signedIn: "Signed in", signOut: "Sign out", dashboards: "Dashboards",
  clickHint: "Click to filter the other panels; click again to undo", noRows: "No rows match these filters", total: "Total", share: "Share of total", period: "Period",
  measure: "Measure", value: "Value", granularity: "Granularity", filters: "Filters", exported: "exported", from: "from", none: "none",
  downloadPanel: "Download this panel's data as an Excel file",
  noDashboards: "No dashboards are available for your role.",
  searchLabel: "Search dashboards", searchPlaceholder: "Search saved, shared and sample dashboards by name, description, owner or tag…", searchClear: "Clear the search and the tags", searchCount: (n, total) => `${n} of ${total}`,
  searchNone: (q) => `No dashboard matches “${q}”.`, searchNoSaved: "No saved dashboard matches.",
  tagInputLabel: "Add a tag", tagInputPlaceholder: "Add a tag, then Enter", tagsMax: "That is the most: 5 tags", tagRemove: (tag) => `Remove the tag ${tag}`,
  tagsHint: "Up to 5 short lower-case words (letters, digits, spaces, hyphens) that help people find and group dashboards. Everyone who can see the dashboard sees them.",
  tagsLabel: "Tags", groupByTag: "Group by tag", untagged: "Untagged", tagFilterAria: (tag) => `Filter by the tag ${tag}`,
  tagNone: (tags) => `No dashboard has the tag ${tags}.`, searchNoneTagged: (q, tags) => `No dashboard matches “${q}” with the tag ${tags}.`,
  noSuchDashboard: (id) => `There is no dashboard '${id}'. Open /d/ for the list.`,
  loadFailed: (status) => `The dashboard could not be loaded (HTTP ${status})`,
  notForRole: (title, role) => `The dashboard '${title}' is not available for your role (${role}).`,
  buildsLeft: (n, total) => `Builds left this hour: ${n} of ${total}.`, other: "Other", shading: "Shading", moreRows: (n) => `Only the first ${n} rows are shown; more exist.`, moreCols: (n) => `Only the first ${n} columns are shown; more exist.`, truncatedPivot: "Cube stopped at its row ceiling: the cells are incomplete. Narrow the filters or lower the limits.", drillHint: "Click a point to drill down; the other panels follow the period. Use the trail above to go back up.", periodLabel: "Period", clearPeriod: "Clear the period",
  saveBtn: "Save…", saveTitle: "Save this dashboard", saveName: "Name", visPrivate: "Only me", visRoles: "These roles", visEveryone: "Everyone who is signed in", saveGo: "Save", saveNewVersion: "Save as a new version",
  saveAsNew: "Save as a new dashboard", savedAs: "Saved", openSaved: "Open it", savingOff: "Saving is not set up on this server (the database login is missing); you can still download the YAML.",
  versionChanges: {
    created: "Created", unknown: "Changed", layout: "Rearranged the layout",
    title: (c) => `Renamed “${c.from}” to “${c.to}”`, page: (c) => `Changed the page: ${c.fields.join(", ")}`,
    panel_added: (c, type) => `Added ${type}: ${c.title}`, panel_removed: (c, type) => `Removed ${type}: ${c.title}`, panel_changed: (c) => `Changed “${c.title}”: ${c.fields.join(", ")}`,
    filter_added: (c) => `Added the filter ${c.label}`, filter_removed: (c) => `Removed the filter ${c.label}`, filter_changed: (c) => `Changed the filter ${c.label}: ${c.fields.join(", ")}`,
    more: (n) => `and ${n} more`,
  },
  designer: {
    button: "Design", designCopy: "Design a copy", title: "Design", close: "Close the designer", pick: "Click a panel to change it. Every change is checked and the page is drawn again.", none: "(none)", refused: "That change was not accepted:",
    footer: "Changes are saved in this draft. Formulas, tabs and the layout are still edited in the YAML.", item: (n, of) => `Item ${n} of ${of}`, changed: (title) => `Changed “${title}” in the designer.`,
    notes: { click: "Its click filter was removed: it pointed at the old grouping.", ignored: "Some panels cannot join to that field, so they ignore the filter." },
    page: "Page", filters: "Filters", noFilters: "No filters yet.", addFilter: "Add a filter", removeFilter: "Remove this filter", addPanel: "Add a panel", back: "Page", duplicate: "Duplicate", remove: "Delete", copySuffix: " (copy)",
    typeHint: { kpi: "Big numbers", timeseries: "A measure over time", bar: "Compare groups", pie: "Parts of a whole", treemap: "Nested shares", table: "Rows and columns", pivot: "A cross-tab", text: "A note" },
    confirmRemove: (title) => `Delete “${title}”?`, confirmFilter: "Remove this filter? Panels that ignored it and click rules that used it are cleaned up.",
    pageChanged: "Changed the page.", filterChanged: "Changed a filter.", filterAdded: "Added a filter.", filterRemoved: "Removed a filter.", added: (name) => `Added a new panel: ${name}.`, duplicated: "Duplicated the panel.", removed: (title) => `Deleted “${title}”.`,
    defaultTitle: (type, measure, by) => (by ? `${measure} by ${by}` : type === "timeseries" ? `${measure} over time` : measure),
    undo: "Undo", redo: "Redo", undone: (label) => (label ? `Undid: ${label}` : "Undid the last change."), redone: (label) => (label ? `Redid: ${label}` : "Redid the change."),
    drag: "Drag to move", resize: "Drag to resize", resized: "Changed the widths.",
    layout: "Layout", tabs: "Tabs", noTabs: "This dashboard is one page.", makeTabs: "Split into two tabs", tabOverview: "Overview", tabDetails: "Details", tabsMade: "Split the page into two tabs.", tabsUnmade: "Put the tabs back on one page.", onePage: "Back to one page", confirmOnePage: "Put every tab's panels on one page, one after the other?",
    addTab: "Add a tab", newTabName: "New tab", newTabNote: "A new tab. Move panels here with “Move to tab”, then replace or delete this note.", tabAdded: "Added a tab.", tabRemove: "Remove the tab", tabRemoved: (t) => `Removed the tab “${t}”; its panels moved to the next one.`,
    confirmTab: (t, n) => `Remove the tab “${t}”? Its ${n} panel(s) move to the neighbouring tab.`, tabName: "Tab name", tabEarlier: "Move the tab earlier", tabLater: "Move the tab later", toTab: "Move to tab", moved: "Moved the panel.", tabMoved: "Moved a tab.", tabRenamed: "Renamed a tab.",
    width: (n) => `Width: ${n} of 12 columns. Drag the grip in the panel's corner to move it, and the bar between two panels to resize them.`,
    cmd: { up: "Up", down: "Down", left: "Left", right: "Right", narrower: "Narrower", wider: "Wider", "join-up": "Join the row above", "join-down": "Join the row below", "own-row": "Own row" },
    look: "Look", logoPick: "Upload a logo", logoRemove: "Remove the logo", logoHint: "A PNG, JPEG or WebP picture. It is shrunk and kept inside the dashboard file (about 15 KB at most).",
    logoType: "Use a PNG, JPEG or WebP picture. SVG is not accepted.", logoRead: "That file could not be read as a picture.", logoBig: "The picture is too detailed to keep inside the dashboard file, even shrunk. Use a simpler or smaller logo.",
    kind: { member: "One measure", sum: "Sum", ratio: "Ratio" }, part: { num: "Divide", den: "By" }, addPart: "Add a measure", removePart: "Remove", addMeasure: "Add a measure", addSeries: "Add a series", removeItem: "Remove this one", formulaIs: (words) => `= ${words}`,
    cannotTitle: "That cannot be done:", cannot: { rows: "A page needs at least two rows to split into tabs.", tabs: "That does not apply to this dashboard.", item: "That item is no longer there.", spare: "There is no other measure you may read to add.", max: "There is no room for another.", min: "At least one must stay.", edge: "It is already at the edge.", alone: "It is alone in its row.", full: "That row has no room left.", same: "That is the same panel.", tab: "That tab no longer exists.", measure: "There is no measure here that you may read and that fits this panel.", dimension: "There is nothing this measure can be grouped by.", last: "A dashboard needs at least one panel.", missing: "That panel no longer exists." },
    types: { kpi: "Key figures", timeseries: "Time chart", bar: "Bar chart", pie: "Pie", treemap: "Treemap", table: "Table", pivot: "Pivot", text: "Text" },
    f: { title: "Title", label: "Label", measure: "Measure", format: "Format", color: "Colour", by: "Group by", group: "Group by", group2: "Then by", rows: "Rows", rows2: "Then rows", columns: "Columns", column: "Column", style: "Style", granularity: "Time step",
      sort: "Sort", limit: "Limit", orientation: "Direction", totals: "Totals", show: "Show", sparkline: "Sparkline step", orgName: "Organisation name", logo: "Logo", heat: "Heat map on", ruleWhen: "Colour when the value", ruleValue: "Number (a percent is a fraction: 0.25)", ruleTone: "Colour", addRule: "Add a colour rule", removeRule: "Remove the rule", orderBy: "Order by", orderDir: "Order", limitRows: "Row limit", limitColumns: "Column limit", columnStep: "Column time step", markdown: "Text", formula: "Formula", description: "Description", locale: "Language", currency: "Currency", timeDimension: "Time field", dimension: "Field", parent: "Narrowed by" },
    v: { below: "is below", above: "is above", at_most: "is at most", at_least: "is at least", good: "Good (green ✓)", warn: "Warning (amber !)", bad: "Bad (red ✕)", total: "Total", label: "Name", money: "Money", int: "Whole number", pct: "Percent", decimal: "Decimal", number: "Number", asc: "Ascending", desc: "Descending", horizontal: "Horizontal", vertical: "Vertical", footer: "Footer", header: "Header",
      both: "Rows and columns", rows: "Rows", columns: "Columns", none: "None", value: "Values", share_of_row: "Share of row", share_of_column: "Share of column", share_of_total: "Share of total",
      hour: "Hour", day: "Day", week: "Week", month: "Month", quarter: "Quarter", year: "Year", line: "Line", area: "Area", "stacked-area": "Stacked area", bar: "Bars", "stacked-bar": "Stacked bars", pie: "Pie", donut: "Donut", "en-US": "English", "tr-TR": "Turkish" },
  },
  yourSavedHint: "Dashboards you saved. You can change and share these.", sharedHint: "Saved by colleagues, so you cannot change them. Open one, or save a copy in your own dashboards and change that.", samples: "Sample dashboards", samplesHint: "Ready-made dashboards to start from.",
  yourSaved: "Your saved dashboards", sharedWithYou: "Shared with you", noSaved: "Nothing saved yet: build a dashboard and press Save.", badgePrivate: "Only you", badgeRoles: "Roles", badgeEveryone: "Everyone",
  by: "by", updated: "Updated", cannotOpen: "Your role cannot open this one", sharing: "Sharing", edit: "Edit", copy: "Save a copy", editCopy: "Edit a copy", versions: "Versions", restore: "Restore", viewVersion: "View",
  deleteBtn: "Delete", confirmDelete: "Delete this dashboard and its versions? This cannot be undone.", shared: "Sharing saved", canOpen: "Roles that can open it", cannotOpenRoles: "Roles that cannot (a member they cannot read)",
  editing: "You are editing a saved dashboard", sharedBy: "Shared by", yours: "Yours", versionNo: "version", noVersions: "No earlier versions.", copied2: "A copy is saved in your dashboards.",
  describe: "Describe a dashboard", describeHint: "Say what you want to see; you get a dashboard you can change, save or download as YAML.",
  placeholder: "e.g. Monthly revenue by channel and the top 5 products, with a table of the latest orders", build: "Build it", building: "Building…", examples: "Try one",
  modeStandin: "A rule-based stand-in answers: it understands a fixed set of phrases (measures, month/quarter/year, by region/country/category/product, top N, a table, a treemap, Turkish), not free text.",
  modeLlm: "A language model reads your request.", draft: "Draft", change: "Change this dashboard", focusOn: (title) => `The change applies to “${title}” only`, focusPlaceholder: "e.g. make this one a donut, show the top 5", changePlaceholder: "e.g. make the chart a line, show the top 3, add a table",
  apply: "Apply", yaml: "YAML", semantic: "Semantic layer", download: "Download YAML", saveDraft: "Save draft", saved: "Saved in this browser", newOne: "Describe a new one",
  yourDrafts: "Your drafts (saved in this browser)", open: "Open", remove: "Delete", noDraft: "There is no draft yet. Describe a dashboard at /d/.",
  semanticHint: "What a dashboard can show: cubes with their measures and dimensions, as your role may read them. Click a name to copy it (and insert it into the YAML if it is open).",
  search: "Search members…", noMatch: "Nothing matches.", copied: "Copied", joins: "joins", factCube: "fact", problems: "Problems found",
  yamlHint: "The whole file. Edit it and apply: it is checked for your role before it is drawn.", yamlApplied: "Applied", builtBy: "Built by", cannotTitle: "Cannot be built", failedTitle: "Could not be built",
  noteTitle: "Notes", rateLimited: "Too many builds for now.", badRequest: "The request was malformed",
  granularities: { hour: "hour", day: "day", week: "week", month: "month", quarter: "quarter", year: "year" },
};

const TR = {
  tones: { good: "iyi", warn: "uyarı", bad: "kötü" },
  fc: {"any": "Hepsi", "and": "ve", "search": "Ara…", "selectAll": "Görünenlerin hepsini seç", "clear": "Temizle", "exclude": "Seçilenler dışındakilerin hepsi", "ops": {"contains": "içerir", "not_contains": "içermez", "starts": "ile başlar", "ends": "ile biter", "eq": "eşittir", "ne": "eşit değildir", "gt": "büyüktür", "gte": "büyük veya eşittir", "lt": "küçüktür", "lte": "küçük veya eşittir", "between": "arasındadır", "on": "şu tarihtedir", "after": "şu tarihten sonradır", "on_or_after": "şu tarihte veya sonradır", "before": "şu tarihten öncedir", "on_or_before": "şu tarihte veya öncedir", "rel": "şu dönemdedir", "set": "boş değil", "unset": "boş"}, "presets": {"today": "Bugün", "yesterday": "Dün", "tomorrow": "Yarın", "this_week": "Bu hafta", "last_week": "Geçen hafta", "next_week": "Gelecek hafta", "this_month": "Bu ay", "last_month": "Geçen ay", "next_month": "Gelecek ay", "this_quarter": "Bu çeyrek", "last_quarter": "Geçen çeyrek", "next_quarter": "Gelecek çeyrek", "this_year": "Bu yıl", "last_year": "Geçen yıl", "next_year": "Gelecek yıl", "week_to_date": "Hafta başından bugüne", "month_to_date": "Ay başından bugüne", "quarter_to_date": "Çeyrek başından bugüne", "year_to_date": "Yıl başından bugüne", "this_fiscal_quarter": "Bu mali çeyrek", "last_fiscal_quarter": "Geçen mali çeyrek", "this_fiscal_year": "Bu mali yıl", "last_fiscal_year": "Geçen mali yıl", "fiscal_year_to_date": "Mali yıl başından bugüne", "all_time": "Tüm zamanlar"}, "counted": {"last": "Son N…", "next": "Gelecek N…", "past": "Geçmiş N (bugüne kadar)…"}, "count": "Sayı", "unit": "Birim", "units": {"days": "gün", "weeks": "hafta", "months": "ay", "quarters": "çeyrek", "years": "yıl"}, nSelected: (n) => `${n} seçili`, nExcept: (n) => `${n} hariç hepsi`, more: (n) => `${n} tane daha: aramak için yazın`},
  sparkAria: (label, gran, bucket, value) => `${label}, ${gran} bazında, son ${bucket}: ${value}`, seriesAria: (labels, gran) => `${labels}, ${gran} bazında`,
  tabsLabel: "Sekmeler", languageLabel: "Dil", dateLocale: "tr-TR", connecting: "Bağlanılıyor…", datasetLabel: "Veri seti", themeToggle: "Tema", notLoaded: "yüklenmedi",
  datasetTitle: (label, mart) => `Veri seti: ${label} (${mart})`, signedInAs: (user, role) => `${user} olarak oturum açıldı, rol: ${role}`,
  all: "Tümü", reset: "Filtreleri sıfırla", table: "Tablo", totals: "Toplamlar", excel: "Excel", exportAll: "Tümünü dışa aktar", refresh: "Yenile", loading: "Yükleniyor…",
  updated: "Güncellendi", stale: "Eski", couldNotLoad: "yüklenemedi", signedIn: "Oturum açık", signOut: "Çıkış", dashboards: "Panolar",
  clickHint: "Diğer panelleri filtrelemek için tıklayın; geri almak için yeniden tıklayın", noRows: "Bu filtrelere uyan satır yok", total: "Toplam", share: "Toplam içindeki pay",
  period: "Dönem", measure: "Ölçü", value: "Değer", granularity: "Ayrıntı", filters: "Filtreler", exported: "dışa aktarıldı", from: "kaynak:", none: "yok",
  downloadPanel: "Bu panelin verisini Excel dosyası olarak indir",
  noDashboards: "Rolünüz için erişilebilir pano yok.",
  searchLabel: "Pano ara", searchPlaceholder: "Kayıtlı, paylaşılan ve örnek panolarda ad, açıklama, sahip veya etikete göre arayın…", searchClear: "Aramayı ve etiketleri temizle", searchCount: (n, total) => `${total} içinden ${n}`,
  searchNone: (q) => `“${q}” ile eşleşen pano yok.`, searchNoSaved: "Eşleşen kayıtlı pano yok.",
  tagInputLabel: "Etiket ekle", tagInputPlaceholder: "Bir etiket yazıp Enter'a basın", tagsMax: "En fazla 5 etiket", tagRemove: (tag) => `${tag} etiketini kaldır`,
  tagsHint: "Panoları bulmayı ve gruplamayı kolaylaştıran en fazla 5 kısa, küçük harfli kelime (harf, rakam, boşluk, tire). Panoyu görebilen herkes bunları görür.",
  tagsLabel: "Etiketler", groupByTag: "Etikete göre grupla", untagged: "Etiketsiz", tagFilterAria: (tag) => `${tag} etiketine göre filtrele`,
  tagNone: (tags) => `${tags} etiketli pano yok.`, searchNoneTagged: (q, tags) => `${tags} etiketli ve “${q}” ile eşleşen pano yok.`,
  noSuchDashboard: (id) => `'${id}' adlı bir pano yok. Liste için /d/ adresini açın.`,
  loadFailed: (status) => `Pano yüklenemedi (HTTP ${status})`,
  notForRole: (title, role) => `'${title}' panosu rolünüz (${role}) için kullanılamaz.`,
  buildsLeft: (n, total) => `Bu saat kalan oluşturma: ${total} içinden ${n}.`, other: "Diğer", shading: "Renklendirme", moreRows: (n) => `Yalnızca ilk ${n} satır gösteriliyor; daha fazlası var.`, moreCols: (n) => `Yalnızca ilk ${n} sütun gösteriliyor; daha fazlası var.`, truncatedPivot: "Cube satır sınırında durdu: hücreler eksik. Filtreleri daraltın veya sınırları düşürün.", drillHint: "Detaya inmek için bir noktaya tıklayın; diğer paneller dönemi izler. Geri çıkmak için üstteki yolu kullanın.", periodLabel: "Dönem", clearPeriod: "Dönemi temizle",
  saveBtn: "Kaydet…", saveTitle: "Bu panoyu kaydet", saveName: "Ad", visPrivate: "Yalnızca ben", visRoles: "Şu roller", visEveryone: "Giriş yapan herkes", saveGo: "Kaydet", saveNewVersion: "Yeni sürüm olarak kaydet",
  saveAsNew: "Yeni pano olarak kaydet", savedAs: "Kaydedildi", openSaved: "Aç", savingOff: "Bu sunucuda kaydetme kurulu değil (veritabanı girişi eksik); YAML'ı yine de indirebilirsiniz.",
  versionChanges: {
    created: "Oluşturuldu", unknown: "Değişti", layout: "Yerleşim düzenlendi",
    title: (c) => `“${c.from}” adı “${c.to}” oldu`, page: (c) => `Sayfa değişti: ${c.fields.join(", ")}`,
    panel_added: (c, type) => `${type} eklendi: ${c.title}`, panel_removed: (c, type) => `${type} kaldırıldı: ${c.title}`, panel_changed: (c) => `“${c.title}” değişti: ${c.fields.join(", ")}`,
    filter_added: (c) => `${c.label} filtresi eklendi`, filter_removed: (c) => `${c.label} filtresi kaldırıldı`, filter_changed: (c) => `${c.label} filtresi değişti: ${c.fields.join(", ")}`,
    more: (n) => `ve ${n} tane daha`,
  },
  designer: {
    button: "Tasarla", designCopy: "Kopyayı tasarla", title: "Tasarım", close: "Tasarımcıyı kapat", pick: "Değiştirmek için bir panele tıklayın. Her değişiklik denetlenir ve sayfa yeniden çizilir.", none: "(yok)", refused: "Bu değişiklik kabul edilmedi:",
    footer: "Değişiklikler bu taslağa kaydedilir. Formüller, sekmeler ve yerleşim hâlâ YAML'dan düzenlenir.", item: (n, of) => `${of} içinden ${n}. öğe`, changed: (title) => `“${title}” tasarımcıda değiştirildi.`,
    notes: { click: "Tıklama filtresi kaldırıldı: eski gruplamaya bağlıydı.", ignored: "Bazı paneller bu alana bağlanamıyor, bu yüzden filtreyi yok sayıyor." },
    page: "Sayfa", filters: "Filtreler", noFilters: "Henüz filtre yok.", addFilter: "Filtre ekle", removeFilter: "Bu filtreyi kaldır", addPanel: "Panel ekle", back: "Sayfa", duplicate: "Çoğalt", remove: "Sil", copySuffix: " (kopya)",
    typeHint: { kpi: "Büyük rakamlar", timeseries: "Zaman içinde bir ölçü", bar: "Grupları karşılaştır", pie: "Bütünün parçaları", treemap: "İç içe paylar", table: "Satır ve sütunlar", pivot: "Çapraz tablo", text: "Bir not" },
    confirmRemove: (title) => `“${title}” silinsin mi?`, confirmFilter: "Bu filtre kaldırılsın mı? Onu yok sayan paneller ve onu kullanan tıklama kuralları temizlenir.",
    pageChanged: "Sayfa değiştirildi.", filterChanged: "Bir filtre değiştirildi.", filterAdded: "Bir filtre eklendi.", filterRemoved: "Bir filtre kaldırıldı.", added: (name) => `Yeni panel eklendi: ${name}.`, duplicated: "Panel çoğaltıldı.", removed: (title) => `“${title}” silindi.`,
    defaultTitle: (type, measure, by) => (by ? `${by} bazında ${measure}` : type === "timeseries" ? `Zaman içinde ${measure}` : measure),
    undo: "Geri al", redo: "Yinele", undone: (label) => (label ? `Geri alındı: ${label}` : "Son değişiklik geri alındı."), redone: (label) => (label ? `Yinelendi: ${label}` : "Değişiklik yinelendi."),
    drag: "Taşımak için sürükleyin", resize: "Boyutlandırmak için sürükleyin", resized: "Genişlikler değişti.",
    layout: "Yerleşim", tabs: "Sekmeler", noTabs: "Bu pano tek sayfa.", makeTabs: "İki sekmeye böl", tabOverview: "Genel bakış", tabDetails: "Ayrıntılar", tabsMade: "Sayfa iki sekmeye bölündü.", tabsUnmade: "Sekmeler tek sayfaya geri alındı.", onePage: "Tek sayfaya dön", confirmOnePage: "Her sekmenin panelleri tek sayfada art arda konsun mu?",
    addTab: "Sekme ekle", newTabName: "Yeni sekme", newTabNote: "Yeni bir sekme. Panelleri “Sekmeye taşı” ile buraya getirin, sonra bu notu değiştirin ya da silin.", tabAdded: "Sekme eklendi.", tabRemove: "Sekmeyi kaldır", tabRemoved: (t) => `“${t}” sekmesi kaldırıldı; panelleri sonraki sekmeye taşındı.`,
    confirmTab: (t, n) => `“${t}” sekmesi kaldırılsın mı? ${n} paneli komşu sekmeye taşınır.`, tabName: "Sekme adı", tabEarlier: "Sekmeyi öne al", tabLater: "Sekmeyi geriye al", toTab: "Sekmeye taşı", moved: "Panel taşındı.", tabMoved: "Bir sekme taşındı.", tabRenamed: "Bir sekmenin adı değişti.",
    width: (n) => `Genişlik: 12 sütundan ${n}. Taşımak için panelin köşesindeki tutamağı, boyutlandırmak için iki panel arasındaki çubuğu sürükleyin.`,
    cmd: { up: "Yukarı", down: "Aşağı", left: "Sola", right: "Sağa", narrower: "Daha dar", wider: "Daha geniş", "join-up": "Üstteki satıra katıl", "join-down": "Alttaki satıra katıl", "own-row": "Kendi satırı" },
    look: "Görünüm", logoPick: "Logo yükle", logoRemove: "Logoyu kaldır", logoHint: "PNG, JPEG veya WebP bir resim. Küçültülür ve pano dosyasının içinde tutulur (en çok yaklaşık 15 KB).",
    logoType: "PNG, JPEG veya WebP bir resim kullanın. SVG kabul edilmez.", logoRead: "Bu dosya resim olarak okunamadı.", logoBig: "Resim, küçültülse bile pano dosyasının içinde tutulamayacak kadar ayrıntılı. Daha sade ya da küçük bir logo kullanın.",
    kind: { member: "Tek ölçü", sum: "Toplam", ratio: "Oran" }, part: { num: "Bölünen", den: "Bölen" }, addPart: "Ölçü ekle", removePart: "Kaldır", addMeasure: "Ölçü ekle", addSeries: "Seri ekle", removeItem: "Bunu kaldır", formulaIs: (words) => `= ${words}`,
    cannotTitle: "Bu yapılamaz:", cannot: { rows: "Sekmelere bölmek için sayfada en az iki satır olmalı.", tabs: "Bu, bu pano için geçerli değil.", item: "Bu öğe artık yok.", spare: "Eklemek için okuyabildiğiniz başka ölçü yok.", max: "Bir tane daha eklemeye yer yok.", min: "En az biri kalmalı.", edge: "Zaten en uçta.", alone: "Satırında tek başına.", full: "Bu satırda yer kalmadı.", same: "Bu aynı panel.", tab: "Bu sekme artık yok.", measure: "Burada okuyabildiğiniz ve bu panele uyan bir ölçü yok.", dimension: "Bu ölçü hiçbir şeye göre gruplanamıyor.", last: "Bir panonun en az bir paneli olmalı.", missing: "Bu panel artık yok." },
    types: { kpi: "Anahtar rakamlar", timeseries: "Zaman grafiği", bar: "Çubuk grafik", pie: "Pasta", treemap: "Ağaç haritası", table: "Tablo", pivot: "Pivot", text: "Metin" },
    f: { title: "Başlık", label: "Etiket", measure: "Ölçü", format: "Biçim", color: "Renk", by: "Gruplama", group: "Gruplama", group2: "Sonra", rows: "Satırlar", rows2: "Sonra satır", columns: "Sütunlar", column: "Sütun", style: "Stil", granularity: "Zaman adımı",
      sort: "Sıralama", limit: "Sınır", orientation: "Yön", totals: "Toplamlar", show: "Gösterim", sparkline: "Mini grafik adımı", orgName: "Kurum adı", logo: "Logo", heat: "Isı haritası", ruleWhen: "Değer şu olunca renklendir", ruleValue: "Sayı (yüzde kesir olarak: 0,25)", ruleTone: "Renk", addRule: "Renk kuralı ekle", removeRule: "Kuralı kaldır", orderBy: "Sıralama ölçütü", orderDir: "Sıra", limitRows: "Satır sınırı", limitColumns: "Sütun sınırı", columnStep: "Sütun zaman adımı", markdown: "Metin", formula: "Formül", description: "Açıklama", locale: "Dil", currency: "Para birimi", timeDimension: "Zaman alanı", dimension: "Alan", parent: "Şuna bağlı" },
    v: { below: "küçükse", above: "büyükse", at_most: "en çok ise", at_least: "en az ise", good: "İyi (yeşil ✓)", warn: "Uyarı (turuncu !)", bad: "Kötü (kırmızı ✕)", total: "Toplam", label: "Ad", money: "Para", int: "Tam sayı", pct: "Yüzde", decimal: "Ondalık", number: "Sayı", asc: "Artan", desc: "Azalan", horizontal: "Yatay", vertical: "Dikey", footer: "Altta", header: "Üstte",
      both: "Satır ve sütun", rows: "Satırlar", columns: "Sütunlar", none: "Yok", value: "Değerler", share_of_row: "Satır payı", share_of_column: "Sütun payı", share_of_total: "Toplam payı",
      hour: "Saat", day: "Gün", week: "Hafta", month: "Ay", quarter: "Çeyrek", year: "Yıl", line: "Çizgi", area: "Alan", "stacked-area": "Yığılmış alan", bar: "Çubuk", "stacked-bar": "Yığılmış çubuk", pie: "Pasta", donut: "Halka", "en-US": "İngilizce", "tr-TR": "Türkçe" },
  },
  yourSavedHint: "Kaydettiğiniz panolar. Bunları değiştirebilir ve paylaşabilirsiniz.", sharedHint: "Meslektaşlarınızın kaydettiği panolar; değiştiremezsiniz. Birini açın ya da kendi panolarınıza kopyasını kaydedip onu değiştirin.", samples: "Örnek panolar", samplesHint: "Başlangıç için hazır panolar.",
  yourSaved: "Kaydettiğiniz panolar", sharedWithYou: "Sizinle paylaşılanlar", noSaved: "Henüz kayıt yok: bir pano oluşturup Kaydet'e basın.", badgePrivate: "Yalnızca siz", badgeRoles: "Roller", badgeEveryone: "Herkes",
  by: "sahibi", updated: "Güncellendi", cannotOpen: "Rolünüz bunu açamaz", sharing: "Paylaşım", edit: "Düzenle", copy: "Kopyasını kaydet", editCopy: "Kopyayı düzenle", versions: "Sürümler", restore: "Geri yükle", viewVersion: "Gör",
  deleteBtn: "Sil", confirmDelete: "Bu pano ve sürümleri silinsin mi? Geri alınamaz.", shared: "Paylaşım kaydedildi", canOpen: "Açabilen roller", cannotOpenRoles: "Açamayan roller (okuyamadıkları bir üye var)",
  editing: "Kayıtlı bir panoyu düzenliyorsunuz", sharedBy: "Paylaşan", yours: "Sizin", versionNo: "sürüm", noVersions: "Önceki sürüm yok.", copied2: "Bir kopya panolarınıza kaydedildi.",
  describe: "Pano tarif et", describeHint: "Ne görmek istediğinizi yazın; değiştirebileceğiniz, kaydedebileceğiniz veya YAML olarak indirebileceğiniz bir pano oluşur.",
  placeholder: "örn. Kanala göre aylık gelir ve en iyi 5 ürün, son siparişlerin tablosuyla", build: "Oluştur", building: "Oluşturuluyor…", examples: "Bir örnek deneyin",
  modeStandin: "Kural tabanlı bir yedek yanıtlıyor: sabit bir ifade kümesini anlar (ölçüler, ay/çeyrek/yıl, bölge/ülke/kategori/ürün kırılımı, ilk N, tablo, ağaç haritası, Türkçe), serbest metni değil.",
  modeLlm: "Bir dil modeli isteğinizi okuyor.", draft: "Taslak", change: "Bu panoyu değiştir", focusOn: (title) => `Değişiklik yalnızca “${title}” için geçerli`, focusPlaceholder: "örn. bunu halka grafik yap, ilk 5'i göster", changePlaceholder: "örn. grafiği çizgi yap, ilk 3'ü göster, tablo ekle",
  apply: "Uygula", yaml: "YAML", semantic: "Anlamsal katman", download: "YAML indir", saveDraft: "Taslağı kaydet", saved: "Bu tarayıcıda kaydedildi", newOne: "Yeni bir tane tarif et",
  yourDrafts: "Taslaklarınız (bu tarayıcıda saklanır)", open: "Aç", remove: "Sil", noDraft: "Henüz taslak yok. /d/ adresinde bir pano tarif edin.",
  semanticHint: "Bir pano neyi gösterebilir: rolünüzün okuyabildiği ölçüler ve boyutlarla küpler. Adı kopyalamak için tıklayın (YAML açıksa oraya eklenir).",
  search: "Üye ara…", noMatch: "Eşleşen yok.", copied: "Kopyalandı", joins: "birleşir", factCube: "olgu", problems: "Bulunan sorunlar",
  yamlHint: "Dosyanın tamamı. Düzenleyip uygulayın: çizilmeden önce rolünüz için denetlenir.", yamlApplied: "Uygulandı", builtBy: "Oluşturan", cannotTitle: "Oluşturulamadı", failedTitle: "Oluşturulamadı",
  noteTitle: "Notlar", rateLimited: "Şimdilik çok fazla oluşturma.", badRequest: "İstek hatalı",
  granularities: { hour: "saat", day: "gün", week: "hafta", month: "ay", quarter: "çeyrek", year: "yıl" },
};

const LANGS = { en: EN, tr: TR };
export const translations = LANGS;

// ------------------------------------------------------------------ the person's language
// The page speaks the language the person chose with the EN | TR switch (kept in this browser, or in ?lang= when the browser will not keep it), else the
// dashboard's own locale (on the list, the browser's). It covers the page's words, dates and number formats; a dashboard's own titles, labels and notes
// are its author's and are not translated.
const LANG_KEY = "dashLang";
const CODES = ["en", "tr"];
export function readLang() {
  try { const q = new URLSearchParams(location.search).get("lang"); if (CODES.includes(q)) return q; } catch { /* no URL to read */ }
  try { const v = localStorage.getItem(LANG_KEY); return CODES.includes(v) ? v : null; } catch { return null; }
}
/** Remember the choice; true when this browser kept it. */
export function writeLang(code) {
  try { localStorage.setItem(LANG_KEY, code); return localStorage.getItem(LANG_KEY) === code; } catch { return false; }
}
/** The locale the page uses: the person's choice, else `fallback` (the dashboard's locale, or the browser's). */
export const uiLocale = (fallback) => ({ en: "en-US", tr: "tr-TR" })[readLang()] || fallback || "en-US";
/** "en" or "tr" for a locale: the two languages the page has words for (anything else shows English). */
export const langOf = (locale) => (String(locale).split("-")[0] === "tr" ? "tr" : "en");

/** The strings for a locale such as "tr-TR": that language where there is one, English for what it lacks. */
export const stringsFor = (locale = "en-US") => ({ ...EN, ...(LANGS[String(locale).split("-")[0]] || {}) });
export const languages = Object.keys(LANGS);
