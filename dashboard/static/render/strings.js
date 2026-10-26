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
  granularities: { hour: "saat", day: "gün", week: "hafta", month: "ay", quarter: "çeyrek", year: "yıl" },
};

const LANGS = { en: EN, tr: TR };
export const translations = LANGS;

/** The strings for a locale such as "tr-TR": that language where there is one, English for what it lacks. */
export const stringsFor = (locale = "en-US") => ({ ...EN, ...(LANGS[String(locale).split("-")[0]] || {}) });
export const languages = Object.keys(LANGS);
