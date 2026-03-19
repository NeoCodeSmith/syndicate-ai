"""
SYNDICATE AI — Command Line Interface
File: src/syndicate/cli/main.py

Usage:
    syndicate run startup-mvp --context '{"project_brief": "B2B SaaS"}'
    syndicate stream <execution-id>
    syndicate agents list --division engineering
    syndicate agents get engineering.ui-engineer
    syndicate workflows list
    syndicate status <execution-id>
    syndicate health

Install:
    pip install syndicate-ai
    export SYNDICATE_API_KEY=sk-your-key
    export SYNDICATE_BASE_URL=http://localhost:8000  # optional
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# ── Minimal dependencies for CLI (no FastAPI/Celery needed) ────────────────


def _require(package: str) -> Any:
    try:
        import importlib

        return importlib.import_module(package)
    except ImportError:
        print(f"Error: '{package}' is required. Run: pip install {package}")
        sys.exit(1)


def _get_client() -> Any:
    api_key = os.environ.get("SYNDICATE_API_KEY", "")
    base_url = os.environ.get("SYNDICATE_BASE_URL", "http://localhost:8000")

    if not api_key:
        print("Error: SYNDICATE_API_KEY environment variable not set.")
        print("  export SYNDICATE_API_KEY=sk-your-key")
        sys.exit(1)

    from syndicate.sdk.client import SyndicateClient

    return SyndicateClient(api_key=api_key, base_url=base_url)


def _fmt_status(status: str) -> str:
    icons = {
        "COMPLETED": "✅",
        "ACTIVE": "⚡",
        "PENDING": "⏳",
        "FAILED": "❌",
        "ABORTED": "🛑",
    }
    return f"{icons.get(status, '●')} {status}"


def _print_execution(ex: Any) -> None:
    bar_width = 20
    filled = int((ex.progress_pct / 100) * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)

    print(f"\n  Execution : {ex.execution_id}")
    print(f"  Workflow  : {ex.workflow_name}")
    print(f"  Status    : {_fmt_status(ex.status)}")
    print(
        f"  Progress  : [{bar}] {ex.progress_pct}%  ({ex.completed_steps}/{ex.total_steps} steps)"
    )
    if ex.current_step:
        print(f"  Current   : {ex.current_step}")
    if ex.completed_at:
        print(f"  Completed : {ex.completed_at}")
    print()


# ── Command implementations ────────────────────────────────────────────────


def cmd_run(args: list[str]) -> None:
    """syndicate run <workflow-id> [--context '<json>'] [--wait] [--stream]"""
    if not args:
        print("Usage: syndicate run <workflow-id> [--context '<json>'] [--wait]")
        sys.exit(1)

    workflow_id = args[0]
    context: dict[str, Any] = {}
    wait = False

    i = 1
    while i < len(args):
        if args[i] == "--context" and i + 1 < len(args):
            try:
                context = json.loads(args[i + 1])
            except json.JSONDecodeError as e:
                print(f"Error: Invalid JSON for --context: {e}")
                sys.exit(1)
            i += 2
        elif args[i] == "--wait":
            wait = True
            i += 1
        else:
            i += 1

    client = _get_client()
    print(f"\n  🚀 Executing workflow: {workflow_id}")
    execution = client.execute(workflow_id, context=context)
    print(f"  Execution ID: {execution.execution_id}")

    if wait:
        print("  Waiting for completion...\n")
        try:
            result = client.wait(execution.execution_id)
            _print_execution(result)
        except TimeoutError as e:
            print(f"\n  ⚠️  {e}")
            sys.exit(1)
    else:
        print(f"\n  Track: syndicate status {execution.execution_id}")
        print(f"  Stream: syndicate stream {execution.execution_id}\n")

    client.close()


def cmd_status(args: list[str]) -> None:
    """syndicate status <execution-id>"""
    if not args:
        print("Usage: syndicate status <execution-id>")
        sys.exit(1)

    client = _get_client()
    ex = client.get_execution(args[0])
    _print_execution(ex)
    client.close()


def cmd_stream(args: list[str]) -> None:
    """syndicate stream <execution-id>"""
    if not args:
        print("Usage: syndicate stream <execution-id>")
        sys.exit(1)

    execution_id = args[0]
    client = _get_client()

    print(f"\n  📡 Streaming execution: {execution_id}\n")
    icons = {
        "step.dispatched": "→",
        "step.active": "⚡",
        "step.completed": "✅",
        "step.failed": "❌",
        "step.retrying": "🔄",
        "step.escalated": "⚠️",
        "validation.passed": "✓",
        "validation.failed": "✗",
        "execution.completed": "🎉",
        "execution.aborted": "🛑",
        "heartbeat": "·",
    }

    try:
        for event in client.stream(execution_id):
            if event.type == "heartbeat":
                print("·", end="", flush=True)
                continue
            icon = icons.get(event.type, "•")
            step = event.data.get("step_name", "")
            agent = event.data.get("agent_id", "")
            label = f"{step} ({agent})" if agent else step
            print(f"  {icon}  [{event.type}]  {label}")
    except KeyboardInterrupt:
        print("\n\n  Stream interrupted.")
    finally:
        client.close()


def cmd_agents(args: list[str]) -> None:
    """syndicate agents list|get [args]"""
    if not args:
        print("Usage: syndicate agents list|get ...")
        sys.exit(1)

    sub = args[0]
    client = _get_client()

    if sub == "list":
        division = None
        capability = None
        i = 1
        while i < len(args):
            if args[i] == "--division" and i + 1 < len(args):
                division = args[i + 1]
                i += 2
            elif args[i] == "--capability" and i + 1 < len(args):
                capability = args[i + 1]
                i += 2
            else:
                i += 1

        agents = client.list_agents(division=division, capability=capability)
        print(f"\n  {len(agents)} agents found\n")
        current_div = ""
        for a in sorted(agents, key=lambda x: (x.division, x.name)):
            if a.division != current_div:
                print(f"  ── {a.division.upper()} ──")
                current_div = a.division
            caps = ", ".join(a.capabilities[:3])
            if len(a.capabilities) > 3:
                caps += f" +{len(a.capabilities) - 3}"
            print(f"    {a.id:<55} {caps}")
        print()

    elif sub == "get":
        if len(args) < 2:
            print("Usage: syndicate agents get <agent-id>")
            sys.exit(1)
        agent = client.get_agent(args[1])
        print(json.dumps(agent, indent=2))
    else:
        print(f"Unknown subcommand: {sub}")
        sys.exit(1)

    client.close()


def cmd_health(_args: list[str]) -> None:
    """syndicate health"""
    client = _get_client()
    result = client.health()
    status = result.get("status", "unknown")
    version = result.get("version", "?")
    icon = "✅" if status == "healthy" else "❌"
    print(f"\n  {icon}  SYNDICATE AI  v{version}  —  {status}\n")
    client.close()


# ── Entry point ────────────────────────────────────────────────────────────

COMMANDS = {
    "run": cmd_run,
    "status": cmd_status,
    "stream": cmd_stream,
    "agents": cmd_agents,
    "health": cmd_health,
}

HELP = """
  SYNDICATE AI CLI  —  Deterministic Multi-Agent Orchestration

  Commands:
    run <workflow-id> [--context '<json>'] [--wait]   Execute a workflow
    status <execution-id>                              Get execution status
    stream <execution-id>                              Stream live events
    agents list [--division <div>]                     List agents
    agents get <agent-id>                              Get agent contract
    health                                             Check API health

  Environment:
    SYNDICATE_API_KEY    Required. Your API key (sk-...)
    SYNDICATE_BASE_URL   Optional. Default: http://localhost:8000

  Examples:
    syndicate run startup-mvp --context '{"project_brief":"SaaS for invoicing"}'
    syndicate run startup-mvp --wait
    syndicate stream exec-abc123
    syndicate agents list --division engineering
    syndicate health
"""


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(HELP)
        sys.exit(0)

    cmd = args[0]
    if cmd not in COMMANDS:
        print(f"  Unknown command: {cmd}\n  Run 'syndicate --help' for usage.")
        sys.exit(1)

    COMMANDS[cmd](args[1:])


if __name__ == "__main__":
    main()
