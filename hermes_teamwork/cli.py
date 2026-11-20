"""
hermes_teamwork.cli
~~~~~~~~~~~~~~~~~~~
Standalone CLI entry point for hermes-teamwork.
Usage:
    hermes-teamwork --help
    hermes-teamwork --version
    hermes-teamwork --runner mock --request "Build authentication system"
    hermes-teamwork "Refactor authentication layer" --runner 9router --workspace /path/to/project
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from hermes_teamwork import __version__
from hermes_teamwork.config import load_config
from hermes_teamwork.runners.hermes_runner import HermesAgentRunner
from hermes_teamwork.runners.mock_runner import MockAgentRunner
from hermes_teamwork.runners.openai_runner import OpenAICompatibleRunner


def create_parser() -> argparse.ArgumentParser:
    """Creates the argument parser for hermes-teamwork CLI."""
    parser = argparse.ArgumentParser(
        prog="hermes-teamwork",
        description="Hermes Teamwork - Antigravity Multi-Agent Architecture CLI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"hermes-teamwork {__version__}",
    )
    parser.add_argument(
        "positional_request",
        nargs="?",
        default=None,
        help="The high-level task or project request",
    )
    parser.add_argument(
        "--request",
        "-r",
        dest="flag_request",
        type=str,
        default=None,
        help="The high-level task or project request",
    )
    parser.add_argument(
        "--runner",
        "--mode",
        dest="runner",
        type=str,
        default=None,
        choices=["mock", "9router", "native", "openai"],
        help="Backend runner engine to execute subagents (default: runner from config, or mock)",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--workspace",
        "-w",
        type=str,
        default=".",
        help="Target project workspace root directory (default: current directory)",
    )
    parser.add_argument(
        "--fail-rounds",
        type=int,
        default=0,
        help="(Mock runner only) Number of rounds challenger rejects before approving",
    )
    return parser


def cli_main(argv: Optional[List[str]] = None) -> int:
    """
    Main CLI logic returning integer exit code.
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    request = args.flag_request or args.positional_request
    if not request or not request.strip():
        sys.stderr.write("Error: A task request is required. Provide via positional argument or --request.\n")
        return 2

    # Load configuration
    cfg = load_config(args.config)

    # Workspace directory
    workspace_dir = Path(args.workspace).resolve()
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Select runner
    runner_choice = (args.runner or cfg.get("runner", "mock")).lower()
    if runner_choice == "mock":
        runner = MockAgentRunner(simulate_challenger_failure_rounds=args.fail_rounds)
    elif runner_choice in ("9router", "openai"):
        endpoint = cfg.get("api_base") or cfg.get("base_url") or "http://localhost:20128/v1"
        runner = OpenAICompatibleRunner(
            api_base=endpoint,
            model=cfg.get("model", "nous-hermes-2-yi-34b"),
            api_key=cfg.get("api_key", "mock-key"),
            timeout=float(cfg.get("timeout", 60.0)),
        )
    elif runner_choice == "native":
        runner = HermesAgentRunner(
            model=cfg.get("model", "nous-hermes-2-yi-34b"),
            config=cfg,
        )
    else:
        sys.stderr.write(f"Error: Unsupported runner '{runner_choice}'.\n")
        return 2

    # Import Sentinel and execute mission
    from hermes_teamwork.core.sentinel import Sentinel

    sentinel = Sentinel(workspace_root=workspace_dir, runner=runner)
    result = sentinel.run(user_request=request.strip())

    if isinstance(result, dict):
        status = result.get("status")
    else:
        status = getattr(result, "status", None)

    print(f"\nFinal Result: {result}")
    if status in ("SUCCESS", "COMPLETED", "DONE"):
        return 0
    return 1


def main(argv: Optional[List[str]] = None) -> None:
    """
    Console script entrypoint.
    """
    code = cli_main(argv)
    sys.exit(code)


if __name__ == "__main__":
    main()
