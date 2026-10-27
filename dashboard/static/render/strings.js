// The page's own words, per language (the language of the spec's `locale`, English when there is no translation). The words in a dashboard
// (titles, labels, descriptions) are the author's and are not translated here.
const EN = {
  sparkAria: (label, gran, bucket, value) => `${label} by ${gran}, latest ${bucket}: ${value}`, seriesAria: (labels, gran) => `${labels} by ${gran}`,
  tabsLabel: "Tabs", languageLabel: "Language", dateLocale: "en-US", connecting: "Connecting…", datasetLabel: "Dataset", themeToggle: "Toggle light or dark theme", notLoaded: "not loaded",
  datasetTitle: (label, mart) => `Dataset: ${label} (${mart})`, signedInAs: (user, role) => `Signed in as ${user}, role ${role}`,
  all: "All", reset: "Reset filters", table: "Table", totals: "Totals", excel: "Excel", exportAll: "Export all", refresh: "Refresh", loading: "Loading…",
  updated: "Updated", stale: "Stale", couldNotLoad: "could not load", signedIn: "Signed in", signOut: "Sign out", dashboards: "Dashboards",
  clickHint: "Click to filter the other panels; click again to undo", noRows: "No rows match these filters", total: "Total", share: "Share of total", period: "Period",
  measure: "Measure", value: "Value", granularity: "Granularity", filters: "Filters", exported: "exported", from: "from", none: "none",
  downloadPanel: "Download this panel's data as an Excel file",
  noDashboards: "No dashboards are available for your role.",
  searchLabel: "Search dashboards", searchPlaceholder: "Search by name, description or owner…", searchClear: "Clear the search and the tags", searchCount: (n, total) => `${n} of ${total}`,
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
  yourSaved: "Your saved dashboards", sharedWithYou: "Shared with you", noSaved: "Nothing saved yet: build a dashboard and press Save.", badgePrivate: "Only you", badgeRoles: "Roles", badgeEveryone: "Everyone",
  by: "by", updated: "Updated", cannotOpen: "Your role cannot open this one", sharing: "Sharing", edit: "Edit", copy: "Save a copy", editCopy: "Edit a copy", versions: "Versions", restore: "Restore", viewVersion: "View",
  deleteBtn: "Delete", confirmDelete: "Delete this dashboard and its versions? This cannot be undone.", shared: "Sharing saved", canOpen: "Roles that can open it", cannotOpenRoles: "Roles that cannot (a member they cannot read)",
  editing: "You are editing a saved dashboard", sharedBy: "Shared by", yours: "Yours", versionNo: "version", noVersions: "No earlier versions.", copied2: "A copy is saved in your dashboards.",
  describe: "Describe a dashboard", describeHint: "Say what you want to see; you get a dashboard you can change, save or download as YAML.",
  placeholder: "e.g. Monthly revenue by channel and the top 5 products, with a table of the latest orders", build: "Build it", building: "Building…", examples: "Try one",
  modeStandin: "A rule-based stand-in answers: it understands a fixed set of phrases (measures, month/quarter/year, by region/country/category/product, top N, a table, a treemap, Turkish), not free text.",
  modeLlm: "A language model reads your request.", draft: "Draft", change: "Change this dashboard", changePlaceholder: "e.g. make the chart a line, show the top 3, add a table",
  apply: "Apply", yaml: "YAML", semantic: "Semantic layer", download: "Download YAML", saveDraft: "Save draft", saved: "Saved in this browser", newOne: "Describe a new one",
  yourDrafts: "Your drafts (saved in this browser)", open: "Open", remove: "Delete", noDraft: "There is no draft yet. Describe a dashboard at /d/.",
  semanticHint: "What a dashboard can show: cubes with their measures and dimensions, as your role may read them. Click a name to copy it (and insert it into the YAML if it is open).",
  search: "Search members…", noMatch: "Nothing matches.", copied: "Copied", joins: "joins", factCube: "fact", problems: "Problems found",
  yamlHint: "The whole file. Edit it and apply: it is checked for your role before it is drawn.", yamlApplied: "Applied", builtBy: "Built by", cannotTitle: "Cannot be built", failedTitle: "Could not be built",
  noteTitle: "Notes", rateLimited: "Too many builds for now.", badRequest: "The request was malformed",
  granularities: { hour: "hour", day: "day", week: "week", month: "month", quarter: "quarter", year: "year" },
};

const TR = {
  sparkAria: (label, gran, bucket, value) => `${label}, ${gran} bazında, son ${bucket}: ${value}`, seriesAria: (labels, gran) => `${labels}, ${gran} bazında`,
  tabsLabel: "Sekmeler", languageLabel: "Dil", dateLocale: "tr-TR", connecting: "Bağlanılıyor…", datasetLabel: "Veri seti", themeToggle: "Açık veya koyu temayı değiştir", notLoaded: "yüklenmedi",
  datasetTitle: (label, mart) => `Veri seti: ${label} (${mart})`, signedInAs: (user, role) => `${user} olarak oturum açıldı, rol: ${role}`,
  all: "Tümü", reset: "Filtreleri sıfırla", table: "Tablo", totals: "Toplamlar", excel: "Excel", exportAll: "Tümünü dışa aktar", refresh: "Yenile", loading: "Yükleniyor…",
  updated: "Güncellendi", stale: "Eski", couldNotLoad: "yüklenemedi", signedIn: "Oturum açık", signOut: "Çıkış", dashboards: "Panolar",
  clickHint: "Diğer panelleri filtrelemek için tıklayın; geri almak için yeniden tıklayın", noRows: "Bu filtrelere uyan satır yok", total: "Toplam", share: "Toplam içindeki pay",
  period: "Dönem", measure: "Ölçü", value: "Değer", granularity: "Ayrıntı", filters: "Filtreler", exported: "dışa aktarıldı", from: "kaynak:", none: "yok",
  downloadPanel: "Bu panelin verisini Excel dosyası olarak indir",
  noDashboards: "Rolünüz için erişilebilir pano yok.",
  searchLabel: "Pano ara", searchPlaceholder: "Ada, açıklamaya veya sahibine göre arayın…", searchClear: "Aramayı ve etiketleri temizle", searchCount: (n, total) => `${total} içinden ${n}`,
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
  yourSaved: "Kaydettiğiniz panolar", sharedWithYou: "Sizinle paylaşılanlar", noSaved: "Henüz kayıt yok: bir pano oluşturup Kaydet'e basın.", badgePrivate: "Yalnızca siz", badgeRoles: "Roller", badgeEveryone: "Herkes",
  by: "sahibi", updated: "Güncellendi", cannotOpen: "Rolünüz bunu açamaz", sharing: "Paylaşım", edit: "Düzenle", copy: "Kopyasını kaydet", editCopy: "Kopyayı düzenle", versions: "Sürümler", restore: "Geri yükle", viewVersion: "Gör",
  deleteBtn: "Sil", confirmDelete: "Bu pano ve sürümleri silinsin mi? Geri alınamaz.", shared: "Paylaşım kaydedildi", canOpen: "Açabilen roller", cannotOpenRoles: "Açamayan roller (okuyamadıkları bir üye var)",
  editing: "Kayıtlı bir panoyu düzenliyorsunuz", sharedBy: "Paylaşan", yours: "Sizin", versionNo: "sürüm", noVersions: "Önceki sürüm yok.", copied2: "Bir kopya panolarınıza kaydedildi.",
  describe: "Pano tarif et", describeHint: "Ne görmek istediğinizi yazın; değiştirebileceğiniz, kaydedebileceğiniz veya YAML olarak indirebileceğiniz bir pano oluşur.",
  placeholder: "örn. Kanala göre aylık gelir ve en iyi 5 ürün, son siparişlerin tablosuyla", build: "Oluştur", building: "Oluşturuluyor…", examples: "Bir örnek deneyin",
  modeStandin: "Kural tabanlı bir yedek yanıtlıyor: sabit bir ifade kümesini anlar (ölçüler, ay/çeyrek/yıl, bölge/ülke/kategori/ürün kırılımı, ilk N, tablo, ağaç haritası, Türkçe), serbest metni değil.",
  modeLlm: "Bir dil modeli isteğinizi okuyor.", draft: "Taslak", change: "Bu panoyu değiştir", changePlaceholder: "örn. grafiği çizgi yap, ilk 3'ü göster, tablo ekle",
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
