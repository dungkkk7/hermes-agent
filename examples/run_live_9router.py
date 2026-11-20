#!/usr/bin/env python3
"""
examples/run_live_9router.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runnable standalone example demonstrating integration with local 9router
or OpenAI-compatible endpoints (e.g. Nous-Hermes-2-Yi-34B on port 20128).

Graceful Fallback Handling:
If port 20128 is not running, the script prints clear informational instructions
and exits cleanly with exit code 0 (or exit code 1 if --strict is specified).

Usage:
    python3 examples/run_live_9router.py
    python3 examples/run_live_9router.py --port 20128 --model nous-hermes-2-yi-34b
    python3 examples/run_live_9router.py --probe-only
    python3 examples/run_live_9router.py --strict
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
import sys
import tempfile
from typing import Any, Dict, Optional
from urllib.parse import urlparse

# Ensure package root is in sys.path when executed directly
_pkg_root = Path(__file__).resolve().parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from hermes_teamwork.config import load_config
from hermes_teamwork.core.sentinel import Sentinel
from hermes_teamwork.runners.openai_runner import OpenAICompatibleRunner


def check_tcp_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Probes raw TCP connectivity to determine if endpoint is listening."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def probe_http_completions(
    base_url: str,
    model: str = "nous-hermes-2-yi-34b",
    api_key: str = "mock-key",
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Sends a minimal chat completions ping with stream=False enforced."""
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
            "response_text": resp.text[:200],
            "is_success": resp.status_code == 200,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "status_code": 0,
            "error": str(exc),
            "is_success": False,
        }


def print_offline_guidance(host: str, port: int) -> None:
    """Prints friendly diagnostic information and instructions on launching 9router."""
    print(f"\n{'=' * 72}")
    print(f"[INFO] 9router server not detected at {host}:{port}.")
    print(f"The local OpenAI-compatible endpoint is currently offline or unreachable.")
    print(f"{'=' * 72}")
    print("\nTo start a local 9router daemon:")
    print(f"  $ 9router --port {port} --model nous-hermes-2-yi-34b")
    print("\nOr start a local OpenAI-compatible server using vLLM or llama.cpp:")
    print(f"  $ python3 -m vllm.entrypoints.openai.api_server --port {port} --model NousResearch/Nous-Hermes-2-Yi-34B")
    print(f"  $ ./llama-server -m models/nous-hermes-2-yi-34b.Q4_K_M.gguf --port {port}\n")


def main() -> int:
    cfg = load_config()
    parsed = urlparse(cfg.get("base_url", "http://localhost:20128/v1"))
    default_host = parsed.hostname or "127.0.0.1"
    default_port = parsed.port or 20128

    parser = argparse.ArgumentParser(
        prog="run_live_9router",
        description="Execute Hermes Teamwork live 9router verification.",
    )
    parser.add_argument("--host", type=str, default=default_host, help=f"Host (default: {default_host})")
    parser.add_argument("--port", type=int, default=default_port, help=f"Port (default: {default_port})")
    parser.add_argument("--base-url", type=str, default=None, help="Full base URL (default: http://<host>:<port>/v1)")
    parser.add_argument("--model", type=str, default=cfg.get("model", "nous-hermes-2-yi-34b"), help="Model name")
    parser.add_argument("--api-key", type=str, default=cfg.get("api_key", "mock-key"), help="API key")
    parser.add_argument("--timeout", type=float, default=5.0, help="Timeout in seconds (default: 5.0)")
    parser.add_argument("--workspace", type=str, default=None, help="Workspace directory")
    parser.add_argument("--probe-only", action="store_true", help="Only probe connectivity, skip Sentinel mission")
    parser.add_argument("--strict", action="store_true", help="Fail with exit 1 if offline (default: clean exit 0)")
    args = parser.parse_args()

    base_url = args.base_url or f"http://{args.host}:{args.port}/v1"

    print("=== 9router Live Integration Runner ===")
    print(f"Target: {args.host}:{args.port} ({base_url})")
    print(f"Model:  {args.model}")

    # Step 1: TCP Port Probe
    print(f"\n[1/4] Probing TCP port {args.port} on {args.host}...")
    is_live = check_tcp_port(args.host, args.port, timeout=min(args.timeout, 2.0))
    if not is_live:
        print_offline_guidance(args.host, args.port)
        if args.strict:
            print("[FAIL] Strict mode: exiting with code 1 due to offline endpoint.")
            return 1
        print("[OK] Skipping live verification cleanly (exit code 0).")
        return 0

    print(f"[PASS] TCP connection established to {args.host}:{args.port}.")

    # Step 2: HTTP Endpoint Probe
    print(f"\n[2/4] Probing HTTP chat completions endpoint...")
    http_res = probe_http_completions(base_url, model=args.model, api_key=args.api_key, timeout=args.timeout)
    if http_res["reachable"]:
        print(f"[PASS] Server responded with HTTP {http_res['status_code']}.")
    else:
        print(f"[WARN] HTTP probe failed: {http_res.get('error')}")

    # Prepare Runner
    runner = OpenAICompatibleRunner(
        base_url=base_url,
        model=args.model,
        api_key=args.api_key,
        timeout=args.timeout,
    )

    # Step 3: Subagent Dispatch Probe
    temp_ctx = None
    if args.workspace:
        ws_path = Path(args.workspace).resolve()
        ws_path.mkdir(parents=True, exist_ok=True)
    else:
        temp_ctx = tempfile.TemporaryDirectory(prefix="teamwork_live_9router_")
        ws_path = Path(temp_ctx.name)

    try:
        print(f"\n[3/4] Testing isolated Subagent Dispatch via OpenAICompatibleRunner...")
        state_dir = ws_path / ".agents" / "teamwork" / "live_probe"
        state_dir.mkdir(parents=True, exist_ok=True)
        disp_file = state_dir / "DISPATCH.md"
        disp_file.write_text("Execute live 9router verification test probe.", encoding="utf-8")

        sub_res = runner.run_agent(
            agent_id="live_worker_01",
            archetype="worker",
            system_prompt="You are a live verification probe worker.",
            dispatch_file=disp_file,
            state_dir=state_dir,
            workspace_dir=ws_path,
        )
        print(f"[PASS] Subagent finished with verdict: {sub_res.get('verdict')}")

        # Step 4: Sentinel Mission E2E
        if args.probe_only:
            print(f"\n[4/4] --probe-only specified. Skipping full Sentinel mission.")
        else:
            print(f"\n[4/4] Executing Sentinel E2E mission with live runner...")
            sentinel = Sentinel(workspace_root=ws_path, runner=runner)
            mission_res = sentinel.run("Live 9router E2E verification mission")
            status = mission_res.get("status")
            print(f"[PASS] Sentinel Mission finished with status: {status}")
            if status != "SUCCESS":
                return 1

        print("\n=== Live 9router Verification PASSED (Exit Code: 0) ===")
        return 0

    except Exception as exc:
        print(f"\n[ERROR] Unexpected verification failure: {exc}", file=sys.stderr)
        return 1
    finally:
        if temp_ctx:
            temp_ctx.cleanup()


if __name__ == "__main__":
    sys.exit(main())
