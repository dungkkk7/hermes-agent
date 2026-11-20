#!/usr/bin/env python3
"""
hermes_teamwork.scripts.verify_live_9router
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Standalone verification runner script for local 9router / OpenAI-compatible endpoint.
Connects to port 20128 by default, probes connectivity, verifies subagent execution,
and runs an end-to-end Sentinel mission.

Exit Codes:
  0: Success OR clean skip/report when offline (unless --strict is specified)
  1: Execution error or strict mode offline failure
  2: Command-line parsing error
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# Ensure package root is in sys.path when executed directly
_pkg_root = Path(__file__).resolve().parent.parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from hermes_teamwork.config import load_config
from hermes_teamwork.core.sentinel import Sentinel
from hermes_teamwork.runners.openai_runner import OpenAICompatibleRunner


def check_tcp_connectivity(host: str, port: int, timeout: float = 2.0) -> bool:
    """Probes raw TCP connectivity to the specified host and port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def probe_http_endpoint(
    base_url: str,
    model: str = "nous-hermes-2-yi-34b",
    api_key: str = "mock-key",
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Probes the OpenAI-compatible HTTP chat completions endpoint."""
    import requests

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        return {
            "reachable": True,
            "status_code": resp.status_code,
            "response_text": resp.text[:300],
            "is_success": resp.status_code == 200,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "status_code": 0,
            "response_text": "",
            "error": str(exc),
            "is_success": False,
        }


def verify_subagent_dispatch(
    runner: OpenAICompatibleRunner,
    workspace_dir: Path,
) -> Dict[str, Any]:
    """Executes a single test subagent using the OpenAI-compatible runner."""
    state_dir = workspace_dir / ".agents" / "teamwork" / "verify_subagent_probe"
    state_dir.mkdir(parents=True, exist_ok=True)
    dispatch_file = state_dir / "DISPATCH.md"
    dispatch_file.write_text("Execute live 9router verification test probe.", encoding="utf-8")

    return runner.run_agent(
        agent_id="verify_worker_01",
        archetype="worker",
        system_prompt="You are a live verification probe worker.",
        dispatch_file=dispatch_file,
        state_dir=state_dir,
        workspace_dir=workspace_dir,
    )


def verify_sentinel_mission(
    runner: OpenAICompatibleRunner,
    workspace_dir: Path,
) -> Dict[str, Any]:
    """Executes a full end-to-end mission using Sentinel and the live runner."""
    sentinel = Sentinel(workspace_root=workspace_dir, runner=runner)
    return sentinel.run("Live 9router E2E verification mission")


def create_parser() -> argparse.ArgumentParser:
    """Constructs the CLI argument parser for verify_live_9router."""
    cfg = load_config()
    parsed = urlparse(cfg.get("base_url", "http://localhost:20128/v1"))
    default_host = parsed.hostname or "127.0.0.1"
    default_port = parsed.port or 20128

    parser = argparse.ArgumentParser(
        prog="verify_live_9router",
        description="Verify local 9router (port 20128) live connectivity and Teamwork E2E execution.",
    )
    parser.add_argument("--host", type=str, default=default_host, help=f"9router host (default: {default_host})")
    parser.add_argument("--port", type=int, default=default_port, help=f"9router port (default: {default_port})")
    parser.add_argument("--base-url", type=str, default=None, help="Full base URL (default: http://<host>:<port>/v1)")
    parser.add_argument("--model", type=str, default=cfg.get("model", "nous-hermes-2-yi-34b"), help="Model name")
    parser.add_argument("--api-key", type=str, default=cfg.get("api_key", "mock-key"), help="API key")
    parser.add_argument("--timeout", type=float, default=5.0, help="Probe timeout in seconds (default: 5.0)")
    parser.add_argument("--workspace", type=str, default=None, help="Workspace directory (default: isolated temp dir)")
    parser.add_argument("--probe-only", action="store_true", help="Only probe connectivity, skip full mission run")
    parser.add_argument("--strict", action="store_true", help="Fail with exit code 1 if server is offline (default: skip clean)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose log output")
    return parser


def run_verification(argv: Optional[List[str]] = None) -> int:
    """Main verification logic returning integer exit code."""
    parser = create_parser()
    args = parser.parse_args(argv)

    base_url = args.base_url or f"http://{args.host}:{args.port}/v1"
    print(f"=== 9router Live Verification ===")
    print(f"Target: {args.host}:{args.port} ({base_url})")
    print(f"Model: {args.model}")
    print(f"Timeout: {args.timeout}s")

    # Step 1: TCP Connectivity Probe
    print(f"\n[1/4] Probing TCP port {args.port} on {args.host}...")
    is_open = check_tcp_connectivity(args.host, args.port, timeout=min(args.timeout, 2.0))
    if not is_open:
        msg = f"[SKIP] 9router server not detected at {args.host}:{args.port}. Endpoint is offline/unreachable."
        print(msg)
        if args.strict:
            print("[FAIL] Strict mode enabled: failing because endpoint is offline.")
            return 1
        print("[OK] Skipping live verification cleanly (exit code 0).")
        return 0

    print(f"[PASS] TCP connection established to {args.host}:{args.port}.")

    # Step 2: HTTP Endpoint Probe
    print(f"\n[2/4] Probing HTTP endpoint at {base_url}...")
    http_res = probe_http_endpoint(
        base_url=base_url,
        model=args.model,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    if http_res["reachable"]:
        if http_res["is_success"]:
            print(f"[PASS] HTTP 200 received from {base_url}/chat/completions.")
        else:
            print(f"[INFO] HTTP {http_res['status_code']} received (Server active, responses formatted): {http_res['response_text'][:120]}")
    else:
        print(f"[WARN] HTTP probe failed: {http_res.get('error')}")

    # Prepare Runner
    runner = OpenAICompatibleRunner(
        base_url=base_url,
        model=args.model,
        api_key=args.api_key,
        timeout=args.timeout,
    )

    # Step 3: Subagent Dispatch Test
    temp_dir_ctx = None
    if args.workspace:
        ws_path = Path(args.workspace).resolve()
        ws_path.mkdir(parents=True, exist_ok=True)
    else:
        temp_dir_ctx = tempfile.TemporaryDirectory(prefix="teamwork_live_9router_")
        ws_path = Path(temp_dir_ctx.name)

    try:
        print(f"\n[3/4] Testing Subagent Dispatch via OpenAICompatibleRunner...")
        sub_res = verify_subagent_dispatch(runner, ws_path)
        verdict = sub_res.get("verdict")
        handoff_path = Path(sub_res.get("handoff_path", ""))
        if verdict == "DONE" and handoff_path.exists():
            print(f"[PASS] Subagent completed with verdict {verdict}. Handoff written at {handoff_path.name}.")
        else:
            print(f"[FAIL] Subagent execution failed: {sub_res}")
            return 1

        # Step 4: Sentinel Mission E2E Run (unless probe-only)
        if args.probe_only:
            print("\n[4/4] Probe-only flag set. Skipping full Sentinel mission.")
        else:
            print(f"\n[4/4] Executing Sentinel E2E mission against live runner...")
            sentinel_res = verify_sentinel_mission(runner, ws_path)
            status = sentinel_res.get("status")
            if status == "SUCCESS":
                print(f"[PASS] Sentinel E2E mission succeeded! Status: {status}")
            else:
                print(f"[FAIL] Sentinel E2E mission returned status: {status}")
                return 1

        print("\n=== Live 9router E2E Verification PASSED (Exit Code: 0) ===")
        return 0

    except Exception as exc:
        print(f"\n[ERROR] Unexpected verification failure: {exc}", file=sys.stderr)
        return 1
    finally:
        if temp_dir_ctx:
            temp_dir_ctx.cleanup()


def main(argv: Optional[List[str]] = None) -> None:
    code = run_verification(argv)
    sys.exit(code)


if __name__ == "__main__":
    main()
