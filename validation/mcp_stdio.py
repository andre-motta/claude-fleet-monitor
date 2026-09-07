"""Run a synthetic MCP stdio smoke with the current Python environment."""

import argparse
import json
import os
import selectors
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1] / 'src')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='fleet-mcp-validation-') as directory:
        env = dict(os.environ, FLEET_DIR=directory, PYTHONPATH=str(args.source.resolve()), PYTHONUNBUFFERED='1')
        fixture = {
            'session_id': 'validation-session', 'agent': 'claude',
            'repo': 'validation-fixture', 'cwd': directory, 'pid': '',
            'status': 'waiting', 'ts': int(time.time()),
        }
        (Path(directory) / 'fixture.json').write_text(json.dumps(fixture))
        process = subprocess.Popen(
            [sys.executable, '-u', '-m', 'claude_fleet_monitor.mcp_server'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, bufsize=0,
        )
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        selector.register(process.stderr, selectors.EVENT_READ)
        buffered = bytearray()
        errors = bytearray()

        def send(message):
            process.stdin.write((json.dumps(message) + '\n').encode())
            process.stdin.flush()

        def response(request_id):
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                for key, _ in selector.select(timeout=0.5):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.fileobj is process.stderr:
                        errors.extend(chunk)
                        continue
                    buffered.extend(chunk)
                    while b'\n' in buffered:
                        line, _, rest = buffered.partition(b'\n')
                        buffered[:] = rest
                        message = json.loads(line)
                        if message.get('id') == request_id:
                            if 'error' in message:
                                raise RuntimeError(message['error'])
                            return message['result']
            raise TimeoutError(f'MCP request {request_id} timed out; process exit: {process.poll()}; stderr: {errors.decode(errors="replace")[-1000:]}')

        try:
            send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2024-11-05', 'capabilities': {},
                'clientInfo': {'name': 'fleet-validation', 'version': '1'},
            }})
            initialized = response(1)
            assert initialized['serverInfo']['name'] == 'claude-fleet'
            send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
            listing = response(2)
            assert {tool['name'] for tool in listing['tools']} == {
                'fleet_status', 'fleet_session', 'fleet_sessions_needing_attention',
                'fleet_focus', 'fleet_cleanup',
            }
            send({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {
                'name': 'fleet_status', 'arguments': {},
            }})
            result = response(3)
            assert not result.get('isError')
            status = json.loads(result['content'][0]['text'])
            assert any(session['session_id'] == 'validation-session' and session['status'] == 'waiting' for session in status['sessions'])
            print('PASS: subprocess stdio initialization, five tools and synthetic fleet status')
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            selector.close()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()


if __name__ == '__main__':
    main()
