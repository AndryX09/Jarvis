import asyncio
import http.client
import importlib.metadata
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "app" / "server.py"


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_listener(process: subprocess.Popen[str], port: int) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=2)
            raise AssertionError(
                f"HTTP server exited early ({process.returncode}).\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("HTTP server did not listen within 15 seconds")


class StreamableHttpIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        importlib.metadata.version("mcp") == "1.28.1",
        "integration test requires the pinned mcp==1.28.1",
    )
    def test_public_host_can_read_status_but_cannot_reach_mcp(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            vault = temporary_root / "vault"
            state = temporary_root / "state"
            vault.mkdir()
            state.mkdir()
            port = _unused_loopback_port()
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "VAULT_ROOT": str(vault),
                    "STATE_ROOT": str(state),
                    "JARVIS_TRANSPORT": "streamable-http",
                    "JARVIS_HTTP_HOST": "127.0.0.1",
                    "JARVIS_HTTP_PORT": str(port),
                    "JARVIS_HTTP_ALLOWED_HOSTS": "127.0.0.1:*,public.example",
                    "JARVIS_MCP_ALLOWED_HOSTS": "127.0.0.1:*",
                }
            )
            process = subprocess.Popen(
                [sys.executable, str(SERVER)],
                cwd=str(SERVER.parent),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                _wait_for_listener(process, port)

                status_connection = http.client.HTTPConnection(
                    "127.0.0.1", port, timeout=5
                )
                status_connection.request(
                    "GET", "/api/status", headers={"Host": "public.example"}
                )
                status_response = status_connection.getresponse()
                status_code = status_response.status
                status_response.read()
                status_connection.close()
                self.assertEqual(status_code, 200)

                initialize_body = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "boundary-test",
                                "version": "1",
                            },
                        },
                    }
                )
                mcp_headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                }
                mcp_connection = http.client.HTTPConnection(
                    "127.0.0.1", port, timeout=5
                )
                mcp_connection.request(
                    "POST",
                    "/mcp",
                    body=initialize_body,
                    headers={"Host": "public.example", **mcp_headers},
                )
                mcp_response = mcp_connection.getresponse()
                mcp_status_code = mcp_response.status
                mcp_response.read()
                mcp_connection.close()
                self.assertIn(mcp_status_code, {401, 421})

                loopback_connection = http.client.HTTPConnection(
                    "127.0.0.1", port, timeout=5
                )
                loopback_connection.request(
                    "POST",
                    "/mcp",
                    body=initialize_body,
                    headers={f"Host": f"127.0.0.1:{port}", **mcp_headers},
                )
                loopback_response = loopback_connection.getresponse()
                loopback_status_code = loopback_response.status
                loopback_response.read()
                loopback_connection.close()
                self.assertEqual(loopback_status_code, 401)
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)

    @unittest.skipUnless(
        importlib.metadata.version("mcp") == "1.28.1",
        "integration test requires the pinned mcp==1.28.1",
    )
    def test_real_http_handshake_lists_contract_and_calls_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            vault = temporary_root / "vault"
            state = temporary_root / "state"
            vault.mkdir()
            state.mkdir()
            port = _unused_loopback_port()
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "VAULT_ROOT": str(vault),
                    "STATE_ROOT": str(state),
                    "JARVIS_TRANSPORT": "streamable-http",
                    "JARVIS_HTTP_HOST": "127.0.0.1",
                    "JARVIS_HTTP_PORT": str(port),
                    "JARVIS_HTTP_ALLOWED_HOSTS": "127.0.0.1:*",
                    "JARVIS_HTTP_MCP_ENABLED": "true",
                }
            )
            process = subprocess.Popen(
                [sys.executable, str(SERVER)],
                cwd=str(SERVER.parent),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                _wait_for_listener(process, port)
                asyncio.run(self._exercise_server(port))
            finally:
                process.terminate()
                try:
                    process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)

    @unittest.skipUnless(
        importlib.metadata.version("mcp") == "1.28.1",
        "integration test requires the pinned mcp==1.28.1",
    )
    def test_stdio_transport_remains_compatible(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            vault = temporary_root / "vault"
            state = temporary_root / "state"
            vault.mkdir()
            state.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "VAULT_ROOT": str(vault),
                    "STATE_ROOT": str(state),
                    "JARVIS_TRANSPORT": "stdio",
                }
            )
            parameters = StdioServerParameters(
                command=sys.executable,
                args=[str(SERVER)],
                env=env,
                cwd=str(SERVER.parent),
            )
            asyncio.run(self._exercise_stdio(parameters))

    async def _exercise_server(self, port: int) -> None:
        url = f"http://127.0.0.1:{port}/mcp"
        async with streamable_http_client(url) as (read, write, _session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = [tool.name for tool in listed.tools]
                self.assertEqual(len(names), 23)
                self.assertFalse(any("delete" in name.lower() for name in names))

                status = await session.call_tool("jarvis_status", {})
                self.assertFalse(status.isError)
                self.assertIn("1.4.0", str(status.structuredContent))

    async def _exercise_stdio(self, parameters: StdioServerParameters) -> None:
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                self.assertEqual(len(listed.tools), 23)
                status = await session.call_tool("jarvis_status", {})
                self.assertFalse(status.isError)
                self.assertIn("1.4.0", str(status.structuredContent))


if __name__ == "__main__":
    unittest.main()
