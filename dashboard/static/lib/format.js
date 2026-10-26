// Number and date formatting for one locale and currency, so a dashboard in tr-TR / TRY and one in en-US / USD share the code.
//
//   const { money, moneyFull, int, pct, decimal, monthName } = createFormat({ locale: "tr-TR", currency: "TRY" });
// Every function takes null/undefined to "—", so a missing value never shows as "NaN" or "$0".
export function createFormat({ locale = "en-US", currency = "USD" } = {}) {
  const compact = new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 2 });
  const cents = new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const symbol = new Intl.NumberFormat(locale, { style: "currency", currency }).formatToParts(0).find((p) => p.type === "currency")?.value ?? currency;
  const integer = new Intl.NumberFormat(locale);
  const twoDecimals = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });
  const oneDecimal = new Intl.NumberFormat(locale);
  const month = new Intl.DateTimeFormat(locale, { month: "short", timeZone: "UTC" });
  const sign = (v) => (v < 0 ? "−" : "");
  const percents = {};
  return {
    locale, currency, symbol,
    /** Compact currency for tiles: $1.29K, ₺1,2 Mn; under 1000 with cents. */
    money: (v) => (v == null ? "—" : sign(v) + symbol + (Math.abs(v) >= 1000 ? compact.format(Math.abs(v)) : cents.format(Math.abs(v)))),
    /** Whole currency units with grouping, for tables and tooltips. */
    moneyFull: (v) => (v == null ? "—" : v.toLocaleString(locale, { style: "currency", currency, maximumFractionDigits: 0 })),
    /** A plain number, up to two decimals, grouped: 1,234.57 */
    number: (v) => (v == null || !isFinite(v) ? "—" : twoDecimals.format(v)),
    int: (v) => (v == null ? "—" : integer.format(Math.round(v))),
    /** A fraction as a percentage: 0.153 -> 15.3%; never "−0%" for a tiny negative. */
    pct: (v, d = 1) => {
      if (v == null || !isFinite(v)) return "—";
      const shown = (percents[d] ||= new Intl.NumberFormat(locale, { style: "percent", minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: false }));   // %15,3 in Turkish, 15.3% in English
      const txt = shown.format(Math.abs(v));
      return (v < 0 && Math.abs(v * 100).toFixed(d) !== (0).toFixed(d) ? "−" : "") + txt;
    },
    /** One decimal place: 12.5 */
    decimal: (v) => (v == null ? "—" : oneDecimal.format(Math.round(v * 10) / 10)),
    /** Short month name from an ISO date or a 1-12 number: Jan, Şub. */
    monthName: (isoOrNumber) => {
      const m = typeof isoOrNumber === "number" ? isoOrNumber : +String(isoOrNumber).split("-")[1];
      return month.format(new Date(Date.UTC(2000, m - 1, 1)));
    },
  };
}

export const ratio = (a, b) => (b && a != null ? a / b : null);
