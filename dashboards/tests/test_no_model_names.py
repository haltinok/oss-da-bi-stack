"""The guard of PLAN-decouple.md (scripts/no_model_names.py): the app folders name no cube or member of any model the repo ships, and the guard really finds one when it is planted."""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("no_model_names", REPO / "scripts" / "no_model_names.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_the_app_names_no_model():
    assert list(guard.hits()) == [], "the app (dashboard/, builder/, dashboards/dashspec/, lab/, admin/, auth/, cube/cube.js) names a model: put it in the model's meta or model.config.yml"


def test_the_guard_finds_a_planted_member_and_a_planted_cube_and_ignores_plain_words(tmp_path, monkeypatch):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "x.js").write_text('const a = "internet_sales.revenue";\nconst b = "inventory_health";\nconst items = dates.length; // "calendar" and "items" are plain words\n')
    real = guard.names()
    monkeypatch.setattr(guard, "names", lambda: real)          # the models are the repo's, the files scanned are the temporary ones
    monkeypatch.setattr(guard, "REPO", tmp_path)
    monkeypatch.setattr(guard, "SCAN", ["app"])
    found = [(n, name) for _, n, name in guard.hits()]
    assert found == [(1, "internet_sales.revenue"), (2, "inventory_health")]


def test_the_guard_skips_model_add_ons_and_tests(tmp_path, monkeypatch):
    for d in ("builder/recipes", "builder/tests", "builder"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    for f in ("builder/recipes/r.py", "builder/tests/t.py"):
        (tmp_path / f).write_text('x = "internet_sales.revenue"\n')
    real = guard.names()
    monkeypatch.setattr(guard, "names", lambda: real)
    monkeypatch.setattr(guard, "REPO", tmp_path)
    monkeypatch.setattr(guard, "SCAN", ["builder"])
    assert list(guard.hits()) == []
