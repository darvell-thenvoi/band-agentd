from band_agentd.cli import main
from band_agentd.service import ServiceScope, unit_path


def test_remove_deletes_the_service_file_and_settings(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("band_agentd.service.shutil.which", lambda _name: None)
    monkeypatch.setattr("band_agentd.cli.default_scope", lambda: ServiceScope.USER)
    unit = unit_path("payments-helper", ServiceScope.USER)
    unit.parent.mkdir(parents=True)
    unit.write_text("[Unit]\n", encoding="utf-8")
    config = tmp_path / "band-agentd" / "payments-helper.yaml"
    config.parent.mkdir()
    config.write_text("agent: {}\n", encoding="utf-8")

    assert main(["remove", "payments-helper"]) == 0

    assert not unit.exists()
    assert not config.exists()
    assert "app.band.ai" in capsys.readouterr().out


def test_remove_unknown_agent_lists_the_installed_ones(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("band_agentd.service.shutil.which", lambda _name: None)
    monkeypatch.setattr("band_agentd.cli.default_scope", lambda: ServiceScope.USER)
    (tmp_path / "band-agentd").mkdir()
    (tmp_path / "band-agentd" / "api-coder.yaml").write_text("agent: {}\n", encoding="utf-8")

    assert main(["remove", "missing"]) == 2

    assert "Installed: api-coder" in capsys.readouterr().err
