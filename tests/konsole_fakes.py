"""Fake Konsole and KWin D-Bus state shared by Konsole and nested tmux tests."""

from types import SimpleNamespace

from claude_fleet_monitor.terminal_apis import konsole


def qdbus_result(returncode=0, stdout=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout)


class FakeKonsole:
    """Konsole and KWin D-Bus state where focus only follows activation."""

    def __init__(self, executable, active=False):
        self.executable = executable
        self.visible = "5"
        self.focused = "5"
        self.active = active
        self.activates = True
        self.runs = True
        self.calls = []
        self.scripts = []
        self.unloaded = []

    def run(self, command, **kwargs):
        assert command[0] == self.executable
        self.calls.append(command)
        args = command[1:]
        if args[:1] == ["org.kde.KWin"]:
            return self._kwin(args)
        if args[:3] == [
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus.GetConnectionUnixProcessID",
        ]:
            return qdbus_result(0, "4242\n")
        if args == ["svc"]:
            return qdbus_result(
                0,
                "/Windows/7\n/konsole/MainWindow_1\n/konsole/MainWindow_1/actions\n",
            )
        method = args[2] if len(args) > 2 else ""
        if method == "org.kde.konsole.Window.setCurrentSession":
            self.visible = args[3]
            if self.active:
                self.focused = self.visible
            return qdbus_result(0)
        if method == "org.kde.konsole.Window.currentSession":
            return qdbus_result(0, f"{self.focused}\n")
        if method == "org.kde.konsole.Session.title":
            return qdbus_result(0, f"title {args[1].rsplit('/', 1)[1]}\n")
        if method == "org.qtproject.Qt.QWidget.isActiveWindow":
            return qdbus_result(0, "true\n" if self.active else "false\n")
        if method == "org.qtproject.Qt.QWidget.windowTitle":
            return qdbus_result(0, f"title {self.focused}\n")
        raise AssertionError(command)

    def _kwin(self, args):
        method = args[2]
        if method == "org.kde.kwin.Scripting.loadScript":
            with open(args[3]) as script:
                self.scripts.append((script.read(), args[4], args[3]))
            return qdbus_result(0, "11\n")
        if method == "org.kde.kwin.Script.run":
            if not self.runs:
                return qdbus_result(1)
            if self.activates:
                self.active = True
                self.focused = self.visible
            return qdbus_result(0)
        if method == "org.kde.kwin.Scripting.unloadScript":
            self.unloaded.append(args[3])
            return qdbus_result(0, "true\n")
        raise AssertionError(args)


def fake_konsole(monkeypatch, active=False):
    executable = "/usr/bin/qdbus-qt6"
    fake = FakeKonsole(executable, active=active)
    monkeypatch.setattr(konsole.shutil, "which", lambda name: executable)
    monkeypatch.setattr(konsole.subprocess, "run", fake.run)
    monkeypatch.setattr(konsole, "_ACTIVATION_SETTLE_SECONDS", 0)
    monkeypatch.setattr(
        konsole.KonsoleAPI, "find_tab", lambda self, pid, env: "svc|7|2"
    )
    return fake
