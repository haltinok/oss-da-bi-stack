// Colour rules (the spec's `rules` on a key figure or a table's measure column): the first rule that matches a value gives its tone. Pure, no DOM.
export const CUES = { good: "✓", warn: "!", bad: "✕" };           // a symbol beside the colour, so the colour is never the only signal

const TESTS = {
  below: (v, x) => v < x,
  above: (v, x) => v > x,
  at_most: (v, x) => v <= x,
  at_least: (v, x) => v >= x,
};

/** "good" | "warn" | "bad" for a value, or null (no rules, no value, or no rule matches). */
export function toneOf(rules, value) {
  if (!Array.isArray(rules) || value == null || !Number.isFinite(Number(value))) return null;
  const rule = rules.find((r) => TESTS[r.when]?.(Number(value), r.value));
  return rule ? rule.tone : null;
}

/** The markup that goes with a tone inside a value: the symbol (hidden from a screen reader) and the tone in words (hidden from the eye). `words` is { good, warn, bad }. */
export const toneCue = (tone, words = {}) => (tone ? `<span class="tone-cue" aria-hidden="true">${CUES[tone]}</span>` : "");
export const toneWord = (tone, words = {}) => (tone ? `<span class="sr-only"> (${words[tone] || tone})</span>` : "");
