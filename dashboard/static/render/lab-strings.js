// The words of the SQL lab (/lab/), English and Turkish.
const EN = {
  title: "SQL lab", home: "Home", sub: "Ask the data in SQL. Every query goes through the same rules as a dashboard.", noLab: "You have not been given the SQL lab.", noLabWhy: "Ask an admin to give a dataset you use the SQL lab permission.",
  run: "Run", running: "Running…", clear: "Clear", samples: "Examples", schema: "Cubes", schemaSearch: "Find a cube or field", schemaHint: "Click a name to put it in the query.", measure: "measure", dimension: "dimension",
  newTab: "New query", closeTab: "Close", tab: (n) => `Query ${n}`, history: "History", historyNone: "Queries you run are listed here (this browser only).", copy: "Copy", copied: "Copied", sort: "Sort",
  rows: (n) => `${n} row${n === 1 ? "" : "s"}`, took: (ms) => `${ms >= 1000 ? (ms / 1000).toFixed(1) + " s" : ms + " ms"}`, cut: (n) => `Showing the first ${n} rows: the rows beyond the limit were left out.`,
  shown: (a, b) => `Showing ${a} of ${b} rows; Copy takes all of them.`, nothing: "The query ran and returned no rows.", failed: "Could not run it:", limits: (r, s) => `At most ${r} rows and ${s} seconds per query.`, placeholder: "select <dimension>, measure(<measure>) from <cube> cross join <other cube> group by 1",
  helpTitle: "How it works", help: "Cubes are tables. Numbers are measures: use MEASURE(name). Dimensions are plain columns. Join cubes with CROSS JOIN (the model knows how they relate). You see exactly what the dashboards let you see: your territories, your role's fields.",
  saved: "Saved queries", savedHint: "Yours, and those shared with you. Running one runs it as you, under your own rules.", savedMine: "Yours", savedShared: "Shared with you", savedNone: "Nothing saved yet.", savedOff: "Saving queries is off on this install.",
  save: "Save", saveNew: "Save as new…", shareBtn: "Share…", deleteBtn: "Delete", queryTitle: "Name of the query", saveTitle: "Save the query", saved1: "Saved.", deleteConfirm: "Delete this saved query?",
  linked: (title, owner, mine) => (mine ? title : `${title} (by ${owner})`), snapshotNote: (when, until) => `Your result from ${when} (kept until ${until}).`, snapshotNone: "No saved result of yours yet: run it.", openIn: "Open",
  folderOf: (n) => `in ${n}`, runAgain: "Run again",
  exportCsv: "CSV", exportXlsx: "Excel", exporting: "Exporting…", exportCut: (n) => `The file holds the first ${n} rows; the rest was left out.`, exportAll: (n) => `Exported ${n} rows.`,
};
const TR = {
  title: "SQL laboratuvarı", home: "Ana sayfa", sub: "Veriye SQL ile sorun. Her sorgu, bir panoyla aynı kurallardan geçer.", noLab: "SQL laboratuvarı size verilmedi.", noLabWhy: "Bir yöneticiden, kullandığınız bir veri kümesine SQL laboratuvarı izni vermesini isteyin.",
  run: "Çalıştır", running: "Çalışıyor…", clear: "Temizle", samples: "Örnekler", schema: "Küpler", schemaSearch: "Küp ya da alan bul", schemaHint: "Sorguya eklemek için bir ada tıklayın.", measure: "ölçü", dimension: "boyut",
  newTab: "Yeni sorgu", closeTab: "Kapat", tab: (n) => `Sorgu ${n}`, history: "Geçmiş", historyNone: "Çalıştırdığınız sorgular burada listelenir (yalnızca bu tarayıcıda).", copy: "Kopyala", copied: "Kopyalandı", sort: "Sırala",
  rows: (n) => `${n} satır`, took: (ms) => `${ms >= 1000 ? (ms / 1000).toFixed(1) + " sn" : ms + " ms"}`, cut: (n) => `İlk ${n} satır gösteriliyor: sınırı aşan satırlar bırakıldı.`,
  shown: (a, b) => `${b} satırın ${a} tanesi gösteriliyor; Kopyala hepsini alır.`, nothing: "Sorgu çalıştı ve satır döndürmedi.", failed: "Çalıştırılamadı:", limits: (r, s) => `Sorgu başına en çok ${r} satır ve ${s} saniye.`, placeholder: "select <dimension>, measure(<measure>) from <cube> cross join <other cube> group by 1",
  helpTitle: "Nasıl çalışır", help: "Küpler tablodur. Sayılar ölçüdür: MEASURE(ad) kullanın. Boyutlar sıradan sütunlardır. Küpleri CROSS JOIN ile birleştirin (model nasıl ilişkili olduklarını bilir). Panoların size gösterdiğini görürsünüz: bölgeleriniz, rolünüzün alanları.",
  saved: "Kayıtlı sorgular", savedHint: "Sizinkiler ve sizinle paylaşılanlar. Birini çalıştırmak onu sizin kurallarınızla çalıştırır.", savedMine: "Sizinkiler", savedShared: "Sizinle paylaşılanlar", savedNone: "Henüz kayıtlı sorgu yok.", savedOff: "Bu kurulumda sorgu kaydetme kapalı.",
  save: "Kaydet", saveNew: "Yeni olarak kaydet…", shareBtn: "Paylaş…", deleteBtn: "Sil", queryTitle: "Sorgunun adı", saveTitle: "Sorguyu kaydet", saved1: "Kaydedildi.", deleteConfirm: "Bu kayıtlı sorgu silinsin mi?",
  linked: (title, owner, mine) => (mine ? title : `${title} (${owner})`), snapshotNote: (when, until) => `Sonucunuz, ${when} tarihli (${until} tarihine kadar saklanır).`, snapshotNone: "Henüz kayıtlı bir sonucunuz yok: çalıştırın.", openIn: "Aç",
  folderOf: (n) => `${n} klasöründe`, runAgain: "Yeniden çalıştır",
  exportCsv: "CSV", exportXlsx: "Excel", exporting: "Dışa aktarılıyor…", exportCut: (n) => `Dosya ilk ${n} satırı içeriyor; gerisi bırakıldı.`, exportAll: (n) => `${n} satır dışa aktarıldı.`,
};
export const labStrings = (lang) => ({ ...EN, ...(lang === "tr" ? TR : {}) });
