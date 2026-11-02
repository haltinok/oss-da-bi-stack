// The words of the start page (/home/), English and Turkish.
const EN = {
  title: "Home", hello: (name) => `Welcome, ${name}`, sub: "Everything you can open or do, in one place.",
  search: "Search your dashboards", searchNone: (q) => `Nothing matches “${q}”.`, searchResults: "Results", signOut: "Sign out", admin: "Admin",
  start: "Start", describe: "Describe a new dashboard", describeHint: "Say what you want to see; a draft is built for you to change and save.", sales: "Live sales dashboard", salesHint: "The simulator's sales, as it happens.",
  allDashboards: "All dashboards", allDashboardsHint: "Samples, yours, and what is shared with you; folders and trash.", console: "Admin console", consoleHint: "People, groups, row rules and datasets.",
  recent: "Pick up where you left off", recentNone: "Dashboards you open will show up here.", shared: "Shared with you", sharedNone: "Nothing has been shared with you yet.", mine: "Your dashboards", mineNone: "You have not saved a dashboard yet.",
  folders: "Your folders", samples: "Samples", by: "by", more: "See all", open: "Open", failed: "Could not load everything:", inFolder: (n) => `in ${n}`, updated: "Updated",
};
const TR = {
  title: "Ana sayfa", hello: (name) => `Hoş geldiniz, ${name}`, sub: "Açabileceğiniz ve yapabileceğiniz her şey, tek yerde.",
  search: "Panolarınızda arayın", searchNone: (q) => `“${q}” ile eşleşen yok.`, searchResults: "Sonuçlar", signOut: "Çıkış", admin: "Yönetim",
  start: "Başla", describe: "Yeni bir pano tarif et", describeHint: "Ne görmek istediğinizi söyleyin; değiştirip kaydedebileceğiniz bir taslak hazırlanır.", sales: "Canlı satış panosu", salesHint: "Simülatörün satışları, olduğu anda.",
  allDashboards: "Tüm panolar", allDashboardsHint: "Örnekler, sizinkiler ve sizinle paylaşılanlar; klasörler ve çöp kutusu.", console: "Yönetim konsolu", consoleHint: "Kişiler, gruplar, satır kuralları ve veri kümeleri.",
  recent: "Kaldığınız yerden devam edin", recentNone: "Açtığınız panolar burada görünür.", shared: "Sizinle paylaşılanlar", sharedNone: "Henüz sizinle paylaşılan bir şey yok.", mine: "Panolarınız", mineNone: "Henüz bir pano kaydetmediniz.",
  folders: "Klasörleriniz", samples: "Örnekler", by: "sahibi", more: "Tümünü gör", open: "Aç", failed: "Her şey yüklenemedi:", inFolder: (n) => `${n} klasöründe`, updated: "Güncellendi",
};
export const homeStrings = (lang) => ({ ...EN, ...(lang === "tr" ? TR : {}) });
