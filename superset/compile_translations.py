"""Compile Superset translation .po files into Jed-style messages.json language packs.

The apache/superset Docker image ships translation *source* files (.po) but not the
compiled messages.json files that the backend `/superset/language_pack/<lang>/` view
serves. Without them every language pack request returns 404. This script converts
each `<lang>/LC_MESSAGES/messages.po` into the gettext.js (Jed) JSON format the
frontend expects, and is run once at image build time.
"""

import json
import os
import sys

from babel.messages import pofile

TRANSLATIONS_DIR = os.environ.get(
    "SUPERSET_TRANSLATIONS_DIR", "/app/superset/translations"
)


def po_to_jed(po_path: str, lang: str) -> dict:
    with open(po_path, encoding="utf8") as f:
        catalog = pofile.read_po(f)

    plural_forms = None
    for key, value in catalog.mime_headers:
        if key == "Plural-Forms":
            plural_forms = value

    entries = {}
    for msg in catalog:
        msgid = msg.id
        if isinstance(msgid, tuple):
            msgid = msgid[0]
        if not msgid:
            continue
        key = msgid
        if msg.context:
            key = msg.context + "\u0004" + msgid
        if isinstance(msg.string, tuple):
            entries[key] = list(msg.string)
        else:
            entries[key] = [msg.string]

    return {
        "domain": "superset",
        "locale_data": {
            "superset": {
                "": {
                    "domain": "superset",
                    "lang": lang,
                    "plural_forms": plural_forms or "nplurals=2; plural=(n != 1)",
                },
                **entries,
            }
        },
    }


def main() -> int:
    compiled = 0
    for lang in os.listdir(TRANSLATIONS_DIR):
        po_path = os.path.join(TRANSLATIONS_DIR, lang, "LC_MESSAGES", "messages.po")
        if not os.path.isfile(po_path):
            continue
        doc = po_to_jed(po_path, lang)
        out_path = os.path.join(
            TRANSLATIONS_DIR, lang, "LC_MESSAGES", "messages.json"
        )
        with open(out_path, "w", encoding="utf8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=0)
        compiled += 1
        print(f"compiled {lang} -> {os.path.relpath(out_path, TRANSLATIONS_DIR)}")
    print(f"Compiled {compiled} language packs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
