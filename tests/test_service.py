from pathlib import Path

from band_agentd.service import ServiceScope, render_systemd_unit


def test_user_unit_carries_path_and_home_and_starts_with_the_user_manager(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PATH", "/home/op/.nvm/bin:/usr/bin")
    config = tmp_path / "agent.yaml"

    unit = render_systemd_unit(config, unit_name="coder", scope=ServiceScope.USER)

    assert "Description=Band agent daemon (coder)" in unit
    assert f'--config "{config}"' in unit
    assert 'Environment="PATH=/home/op/.nvm/bin:/usr/bin"' in unit
    assert f'Environment="HOME={Path.home()}"' in unit
    assert "WantedBy=default.target" in unit
    assert "network-online.target" not in unit
    assert "Restart=always" in unit


def test_system_unit_waits_for_the_network(tmp_path):
    unit = render_systemd_unit(tmp_path / "agent.yaml", scope=ServiceScope.SYSTEM)

    assert "WantedBy=multi-user.target" in unit
    assert "After=network-online.target" in unit
