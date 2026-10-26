// The page's own words, per language (the language of the spec's `locale`, English when there is no translation). The words in a dashboard
// (titles, labels, descriptions) are the author's and are not translated here.
const EN = {
  all: "All", reset: "Reset filters", table: "Table", excel: "Excel", exportAll: "Export all", refresh: "Refresh", loading: "Loading…",
  updated: "Updated", stale: "Stale", couldNotLoad: "could not load", signedIn: "Signed in", signOut: "Sign out", dashboards: "Dashboards",
  clickHint: "Click to filter the other panels; click again to undo", noRows: "No rows match these filters", total: "Total", share: "Share of total", period: "Period",
  measure: "Measure", value: "Value", granularity: "Granularity", filters: "Filters", exported: "exported", from: "from", none: "none",
  downloadPanel: "Download this panel's data as an Excel file",
  noDashboards: "No dashboards are available for your role.",
  noSuchDashboard: (id) => `There is no dashboard '${id}'. Open /d/ for the list.`,
  loadFailed: (status) => `The dashboard could not be loaded (HTTP ${status})`,
  notForRole: (title, role) => `The dashboard '${title}' is not available for your role (${role}).`,
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
  all: "Tümü", reset: "Filtreleri sıfırla", table: "Tablo", excel: "Excel", exportAll: "Tümünü dışa aktar", refresh: "Yenile", loading: "Yükleniyor…",
  updated: "Güncellendi", stale: "Eski", couldNotLoad: "yüklenemedi", signedIn: "Oturum açık", signOut: "Çıkış", dashboards: "Panolar",
  clickHint: "Diğer panelleri filtrelemek için tıklayın; geri almak için yeniden tıklayın", noRows: "Bu filtrelere uyan satır yok", total: "Toplam", share: "Toplam içindeki pay",
  period: "Dönem", measure: "Ölçü", value: "Değer", granularity: "Ayrıntı", filters: "Filtreler", exported: "dışa aktarıldı", from: "kaynak:", none: "yok",
  downloadPanel: "Bu panelin verisini Excel dosyası olarak indir",
  noDashboards: "Rolünüz için erişilebilir pano yok.",
  noSuchDashboard: (id) => `'${id}' adlı bir pano yok. Liste için /d/ adresini açın.`,
  loadFailed: (status) => `Pano yüklenemedi (HTTP ${status})`,
  notForRole: (title, role) => `'${title}' panosu rolünüz (${role}) için kullanılamaz.`,
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

/** The strings for a locale such as "tr-TR": that language where there is one, English for what it lacks. */
export const stringsFor = (locale = "en-US") => ({ ...EN, ...(LANGS[String(locale).split("-")[0]] || {}) });
export const languages = Object.keys(LANGS);
