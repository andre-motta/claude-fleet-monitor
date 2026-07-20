"""Tests for the tongs plugin module."""

import importlib
import sys

import pytest


class TestPluginWithoutTongs:
    def test_no_crash_without_tongs(self):
        saved = sys.modules.get("tongs")
        saved_base = sys.modules.get("tongs.plugins")
        saved_base2 = sys.modules.get("tongs.plugins.base")
        try:
            sys.modules["tongs"] = None
            sys.modules["tongs.plugins"] = None
            sys.modules["tongs.plugins.base"] = None
            if "claude_fleet_monitor.tongs_plugin" in sys.modules:
                del sys.modules["claude_fleet_monitor.tongs_plugin"]
            mod = importlib.import_module("claude_fleet_monitor.tongs_plugin")
            assert not hasattr(mod, "FleetMonitorPlugin") or mod._PluginClass is None
        finally:
            if saved is not None:
                sys.modules["tongs"] = saved
            else:
                sys.modules.pop("tongs", None)
            if saved_base is not None:
                sys.modules["tongs.plugins"] = saved_base
            else:
                sys.modules.pop("tongs.plugins", None)
            if saved_base2 is not None:
                sys.modules["tongs.plugins.base"] = saved_base2
            else:
                sys.modules.pop("tongs.plugins.base", None)
            sys.modules.pop("claude_fleet_monitor.tongs_plugin", None)


class TestPluginWithTongs:
    @pytest.fixture(autouse=True)
    def _check_tongs(self):
        pytest.importorskip("tongs")

    def test_plugin_instantiation(self):
        from claude_fleet_monitor.tongs_plugin import FleetMonitorPlugin
        plugin = FleetMonitorPlugin()
        assert plugin.name == "fleet-monitor"

    def test_get_commands(self):
        from claude_fleet_monitor.tongs_plugin import FleetMonitorPlugin
        plugin = FleetMonitorPlugin()
        cmds = plugin.get_commands()
        assert len(cmds) == 1
        assert cmds[0][0] == "Fleet Monitor"

    def test_get_screens(self):
        from claude_fleet_monitor.tongs_plugin import FleetMonitorPlugin
        plugin = FleetMonitorPlugin()
        screens = plugin.get_screens()
        assert "fleet" in screens
        from claude_fleet_monitor.views.fleet_screen import FleetScreen
        assert screens["fleet"] is FleetScreen

    def test_version(self):
        from claude_fleet_monitor.tongs_plugin import FleetMonitorPlugin
        plugin = FleetMonitorPlugin()
        v = plugin.version
        assert isinstance(v, str)
