"""Built-in harness metadata and event capability registry."""

from dataclasses import dataclass
from enum import Enum


class ProcessIdentity(Enum):
    DISCOVERABLE = "discoverable"
    EMITTER = "emitter"


@dataclass(frozen=True)
class HarnessSpec:
    harness_id: str
    display_name: str
    process_names: tuple[str, ...]
    events: frozenset[str]
    process_identity: ProcessIdentity
    capabilities: frozenset[str]

    def supports_event(self, event: str) -> bool:
        return event in self.events


_COMMON_EVENTS = frozenset({
    "session-start",
    "prompt-submit",
    "tool-use",
    "stop",
    "session-end",
    "permission-request",
})

HARNESSES = {
    "claude": HarnessSpec(
        harness_id="claude",
        display_name="Claude Code",
        process_names=("claude", "claude.exe"),
        events=_COMMON_EVENTS | {"stop-failure", "elicitation"},
        process_identity=ProcessIdentity.DISCOVERABLE,
        capabilities=frozenset({"hooks", "process-discovery", "terminal-focus"}),
    ),
    "codex": HarnessSpec(
        harness_id="codex",
        display_name="Codex",
        process_names=("codex", "codex.exe"),
        events=_COMMON_EVENTS,
        process_identity=ProcessIdentity.DISCOVERABLE,
        capabilities=frozenset({"hooks", "process-discovery", "terminal-focus"}),
    ),
    "pi": HarnessSpec(
        harness_id="pi",
        display_name="Pi",
        process_names=(),
        events=frozenset({"fleet-event"}),
        process_identity=ProcessIdentity.EMITTER,
        capabilities=frozenset({"extension-events", "exact-pid-input"}),
    ),
}


def get_harness(harness_id: str) -> HarnessSpec | None:
    if not isinstance(harness_id, str):
        return None
    return HARNESSES.get(harness_id)


def registered_harnesses() -> tuple[HarnessSpec, ...]:
    return tuple(HARNESSES.values())
