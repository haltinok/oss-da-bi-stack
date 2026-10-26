import pathlib

from builder import cli

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_cli_writes_yaml_for_a_good_request(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = tmp_path / "d.yml"
    assert cli.main(["monthly revenue by channel", "--role", "manager", "-o", str(out)]) == 0
    assert "id: draft" in out.read_text()
    assert "ok (standin" in capsys.readouterr().err


def test_cli_exits_1_and_explains_a_refusal(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli.main(["inventory dashboard", "--role", "rep"]) == 1
    assert "cannot" in capsys.readouterr().err
