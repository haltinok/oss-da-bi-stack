// A logo picked in the designer, made small enough to live inside the dashboard file as a data URI (`theme.logo`). The browser does the drawing (render/designer.js);
// what is decided without a browser is here: the sizes to try and whether a result fits. Pure functions.

export const MAX_LOGO_CHARS = 20000;                              // what the spec allows (dashboards/schema): the whole file may be 30,000 characters
export const ACCEPTED = ["image/png", "image/jpeg", "image/webp"];   // not SVG: it can carry script

/** Sizes to try, biggest first: the logo is shown 28 px high, so 56 px is enough for a sharp screen; it never grows beyond the picture itself. */
export function sizesToTry(width, height) {
  if (!(width > 0 && height > 0)) return [];
  const out = [];
  for (const h of [56, 40, 28, 20]) {
    const scale = Math.min(1, h / height);
    const w = Math.max(1, Math.round(width * scale)), hh = Math.max(1, Math.round(height * scale));
    if (w > 480) continue;                                         // a banner is not a logo
    if (!out.some((s) => s.w === w && s.h === hh)) out.push({ w, h: hh });
  }
  return out;
}

/** A data URI of an accepted image type that fits. */
export const fits = (uri) => typeof uri === "string" && /^data:image\/(png|jpeg|webp);base64,/.test(uri) && uri.length <= MAX_LOGO_CHARS;

/** Which encodings to try at one size, in order: PNG keeps transparency; WebP and JPEG are smaller for a photograph (JPEG has no transparency, so it is last and on white). */
export const ENCODINGS = [{ type: "image/png" }, { type: "image/webp", quality: 0.9 }, { type: "image/webp", quality: 0.7 }, { type: "image/jpeg", quality: 0.85, onWhite: true }, { type: "image/jpeg", quality: 0.6, onWhite: true }];
