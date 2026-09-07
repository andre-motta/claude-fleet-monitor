# Pi validation

This validator runs the installed Pi CLI against a synthetic HTTP provider on
localhost and observes the resulting Fleet records. It uses only temporary Pi,
home, session and Fleet directories. It does not read the user's Pi settings or
contact an external model provider.

Run it from an editable or wheel-installed development environment with Pi
0.84.4 or newer, Node.js and tmux on `PATH`. The wrapper creates a unique tmux
socket with an empty config, enforces an overall timeout, propagates the
validator exit code and prints the JSON evidence to stdout:

```bash
python validation/pi/run_in_tmux.py --timeout 120
```

The JSON evidence records exact Pi, Node.js and Python versions; observed Fleet
lifecycle transitions; session switch, resume and reload behavior; clean
shutdown; abrupt PID cleanup; preservation of an unrelated extension setting;
and the structured tmux focus result. The validator creates another pane, makes
that pane active, focuses the Fleet record, and independently verifies that the
active pane changed to the pane containing the real Pi process. A detached tmux
server has no GUI parent window, so window activation remains unavailable or
failed separately from the successful pane selection.

The normal pytest suite covers malformed ownership metadata, old and unknown Pi
versions, paths with spaces and Unicode, idempotent install/remove, virtual
environment migration, bounded fail-open delivery, duplicate starts, retries,
errors, aborts, prompt nesting, privacy and synchronous session capture.
