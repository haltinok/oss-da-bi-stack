// The language switch on the /d pages: EN | TR, a small segmented control in the header. Choosing a language keeps the choice and loads the page again,
// so every word, date and number is drawn afresh in it (the filters, drill-downs and lists are in the URL and come back as they were).
import { $ } from "../lib/dom.js";
import { writeLang } from "./strings.js";

/** `active` is "en" or "tr"; `t` the page's words (the group's name). */
export function mountLangSwitch(t, active) {
  const group = $("#lang-switch");
  if (!group) return;
  group.setAttribute("aria-label", t.languageLabel);
  group.title = t.languageLabel;
  for (const b of group.querySelectorAll("button[data-lang]")) {
    b.setAttribute("aria-pressed", String(b.dataset.lang === active));
    b.onclick = () => {
      if (b.dataset.lang === active) return;
      const kept = writeLang(b.dataset.lang);
      const url = new URL(location.href);
      if (!kept || url.searchParams.has("lang")) url.searchParams.set("lang", b.dataset.lang);        // a browser that will not keep it, or a link that carried one
      if (url.href === location.href) location.reload(); else location.assign(url);
    };
  }
}
