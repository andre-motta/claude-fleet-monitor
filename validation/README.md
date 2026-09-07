# Manual integration validation

These checks are separate from ordinary pytest. Use an environment with the
project and its dependencies installed. They use synthetic temporary fleet data;
they do not prove live harness activity or desktop focus.

## MCP stdio on Linux/macOS

```console
python validation/mcp_stdio.py
```

The script starts the real MCP server process, initializes a protocol session,
lists all five tools and queries a synthetic waiting session. It writes only in
a temporary fleet directory and terminates its child process on completion.
Its pipe selector implementation is for POSIX platforms, not a claimed Windows
validation tool. Process discovery may see host agents but their data stays in
the temporary directory and is not printed.

On the 2026-09-07 validation host, sandboxed AnyIO stdio reads stalled. The same
check passed in the normal host environment, with no external network requests.
A sandbox timeout is not a pass and must be reported separately.

## GitHub Actions workflow lint

The `workflow-lint` job in `.github/workflows/test.yml` downloads the pinned
official actionlint 1.7.12 Linux release, verifies its SHA-256 before
extraction, and checks every `.github/workflows/*.yml` file. It disables the
optional shellcheck and pyflakes integrations so the gate has no project
dependency beyond the standard Ubuntu runner tools.

To reproduce locally with a downloaded actionlint binary:

```console
actionlint -no-color -shellcheck= -pyflakes= .github/workflows/*.yml
```
