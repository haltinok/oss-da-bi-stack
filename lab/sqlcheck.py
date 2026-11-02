"""What the SQL lab accepts before it sends anything to Cube: one statement, a SELECT (or WITH ... SELECT), not too long.

This is a convenience and a first line, not the security: Cube's SQL API only understands queries over the cubes, runs them through queryRewrite (role rules, territories, blocked
cubes) like every dashboard query, and refuses anything else (INSERT, DROP, other tables). The scanner below only keeps a second statement or a stray `;` from reaching it.
"""
from __future__ import annotations

import re

MAX_SQL = 20_000
_START = re.compile(r"^\s*(select|with)\b", re.I)


class SqlRefused(ValueError):
    pass


def semicolons_outside_quotes(sql: str) -> list[int]:
    """The positions of `;` that are not inside a quoted string, a quoted identifier or a comment."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c in "'\"":                                                    # '...' (with '' inside) or "..." (with "" inside)
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            if c == ";":
                out.append(i)
            i += 1
    return out


def check(sql: str) -> str:
    """The statement to run (a trailing `;` removed), or SqlRefused with a message for the person."""
    if not isinstance(sql, str) or not sql.strip():
        raise SqlRefused("Write a query first.")
    if len(sql) > MAX_SQL:
        raise SqlRefused(f"The query is too long ({len(sql)} characters, at most {MAX_SQL}).")
    stripped = sql.strip()
    semis = semicolons_outside_quotes(stripped)
    if semis and (len(semis) > 1 or semis[0] != len(stripped) - 1):
        raise SqlRefused("Run one statement at a time (remove the extra ;).")
    stripped = stripped[:-1].rstrip() if semis else stripped
    if not _START.match(re.sub(r"^(\s|--[^\n]*\n|/\*.*?\*/)+", "", stripped, flags=re.S)):
        raise SqlRefused("Only SELECT queries are allowed.")
    if "\x00" in stripped:
        raise SqlRefused("The query holds a character that cannot be sent.")
    return stripped
