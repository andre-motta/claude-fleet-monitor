"""tongs plugin for Claude Fleet Monitor."""

from __future__ import annotations

try:
    from tongs.plugins.base import TongsPlugin
except ImportError:
    TongsPlugin = None


def _make_plugin_class():
    if TongsPlugin is None:
        return None

    class FleetMonitorPlugin(TongsPlugin):

        @property
        def name(self) -> str:
            return "fleet-monitor"

        @property
        def version(self) -> str:
            try:
                from claude_fleet_monitor._version import __version__
                return __version__
            except Exception:
                return "0.0.0"

        def get_commands(self) -> list[tuple[str, str, object]]:
            return [
                (
                    "Fleet Monitor",
                    "View Claude Code session fleet",
                    self._open_fleet,
                ),
            ]

        def get_screens(self) -> dict[str, type]:
            from claude_fleet_monitor.views.fleet_screen import FleetScreen
            return {"fleet": FleetScreen}

        def _open_fleet(self) -> None:
            from claude_fleet_monitor.views.fleet_screen import FleetScreen
            self._app.push_screen(FleetScreen())

        async def on_app_ready(self, app) -> None:
            self._app = app

    return FleetMonitorPlugin


_PluginClass = _make_plugin_class()

if _PluginClass is not None:
    FleetMonitorPlugin = _PluginClass
