"""CSV and Excel export: the same gate, rules, limits and audit as a query; the file's contents; nothing in a cell is ever run as a formula.

  cd lab && PYTHONPATH=. uv run --with pytest --with fastapi --with httpx --with 'pyjwt[crypto]' --with psycopg2-binary --with pyyaml --with 'jsonschema>=4.18' --with xlsxwriter --with openpyxl python -m pytest tests -q
"""
import csv
import io

import pytest
from fastapi.testclient import TestClient

import main

ME = main.Caller(name="ayse", raw="kc-token")
COLS = [{"name": "label", "type": "string"}, {"name": "amount", "type": "number"}, {"name": "when", "type": "time"}]
ROWS = [["Bisiklet, \"kırmızı\"", 1234.5, "2026-01-02T00:00:00"], ["=HYPERLINK(\"http://x\")", -3, None], ["+cmd|' /C calc'!A0", 0, "2026-01-03T10:00:00"], ["line\nbreak", None, "x"], ["Çay-İçki", 7, "y"], ["-minus", 1, "z"]]


@pytest.fixture()
def api(monkeypatch):
    main.app.dependency_overrides[main.current_caller] = lambda: ME
    monkeypatch.setattr(main, "cube_session", lambda caller: {"token": "t", "user": "ayse", "role": "manager", "lab": True, "blocked_cubes": []})
    monkeypatch.setattr(main, "_per_user", {})
    lines = []
    monkeypatch.setattr(main, "audit", lambda entry: lines.append(entry))

    def fake(user, token, sql, limit):
        data = ROWS[:limit]
        return {"columns": COLS, "rows": data, "row_count": len(data), "truncated": len(ROWS) > limit}
    monkeypatch.setattr(main, "execute", fake)
    yield TestClient(main.app), lines
    main.app.dependency_overrides.clear()


def test_a_csv_has_a_byte_order_mark_a_header_proper_quoting_and_no_live_formulas(api):
    client, lines = api
    r = client.post("/export", json={"sql": "select label from t", "format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and 'attachment; filename="lab-' in r.headers["content-disposition"] and r.headers["x-lab-truncated"] == "false" and r.headers["x-lab-rows"] == "6"
    assert r.content.startswith(b"\xef\xbb\xbf"), "a BOM, so Excel reads Turkish letters right"
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0] == ["label", "amount", "when"] and len(rows) == 7
    assert rows[1][0] == 'Bisiklet, "kırmızı"' and rows[1][1] == "1234.5"
    assert rows[2][0] == "'=HYPERLINK(\"http://x\")" and rows[2][1] == "-3" and rows[2][2] == "", "text that starts like a formula is made plain; a negative number stays a number"
    assert rows[3][0].startswith("'+cmd") and rows[6][0] == "'-minus"
    assert rows[4][0] == "line\nbreak" and rows[5][0] == "Çay-İçki"
    assert lines[0]["event"] == "lab_export" and lines[0]["rows"] == 6 and lines[0]["user"] == "ayse"


def test_an_excel_file_has_numbers_text_a_header_and_no_formulas(api):
    openpyxl = pytest.importorskip("openpyxl")
    client, _ = api
    r = client.post("/export", json={"sql": "select label from t", "format": "xlsx"})
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"] and r.headers["content-disposition"].endswith('.xlsx"')
    ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
    assert [c.value for c in ws[1]] == ["label", "amount", "when"] and ws["A1"].font.bold and ws.freeze_panes == "A2"
    assert ws["B2"].value == 1234.5 and ws["B2"].data_type == "n" and ws["B3"].value == -3
    assert ws["A3"].value == '=HYPERLINK("http://x")' and ws["A3"].data_type == "s", "stored as text, so no spreadsheet runs it"
    assert ws["A4"].value.startswith("+cmd") and ws["A4"].data_type == "s"
    assert ws["B5"].value is None and ws["A6"].value == "Çay-İçki"


def test_the_export_limit_cuts_a_long_result_and_says_so(api, monkeypatch):
    client, lines = api
    monkeypatch.setattr(main, "EXPORT_ROWS", 3)
    r = client.post("/export", json={"sql": "select 1", "format": "csv"})
    assert r.headers["x-lab-truncated"] == "true" and r.headers["x-lab-rows"] == "3" and len(list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))) == 4
    assert lines[0]["truncated"] is True


def test_an_export_is_refused_like_a_query(api, monkeypatch):
    client, _ = api
    assert client.post("/export", json={"sql": "drop table x"}).status_code == 400
    assert client.post("/export", json={"sql": "select 1; select 2"}).status_code == 400
    assert client.post("/export", json={"sql": "select 1", "format": "pdf"}).status_code == 400
    monkeypatch.setattr(main, "cube_session", lambda caller: {"token": "t", "role": "manager", "lab": False})
    r = client.post("/export", json={"sql": "select 1", "format": "csv"})
    assert r.status_code == 403 and "SQL lab" in r.json()["detail"]


def test_cubes_refusals_reach_an_export_too_and_nothing_is_written(api, monkeypatch):
    client, lines = api

    def boom(*a):
        raise RuntimeError("Database Execution Error: Customer data is not available for your role")
    monkeypatch.setattr(main, "execute", boom)
    r = client.post("/export", json={"sql": "select * from customers", "format": "csv"})
    assert r.status_code == 400 and "Customer data" in r.json()["detail"] and lines[0]["event"] == "lab_export" and "error" in lines[0]


def test_info_tells_the_page_the_export_limit(api):
    client, _ = api
    assert client.get("/info").json()["limits"]["export_rows"] == main.EXPORT_ROWS
