"""
CLI Agent Hook — /cli command for one-shot AI CLI invocations.

Registers a /cli slash command so you can call gemini, claude, codex, or kimi
for a one-shot response without going through the OpenClaw gateway.

Usage inside aider:
  /cli gemini <prompt>    — run: gemini -p "<prompt>"
  /cli claude <prompt>    — run: claude -p "<prompt>"
  /cli codex <prompt>     — run: codex exec "<prompt>"
  /cli kimi <prompt>      — run: kimi --print "<prompt>"

  /cli list               — show available CLIs and their status

Examples:
  /cli gemini explain the authentication flow in auth.py
  /cli claude review this function for security issues
  /cli codex add type annotations to utils.py
"""

from typing import Any, Dict, Optional


def _run_cli(name: str, prompt: str, cwd: Optional[str] = None) -> str:
    from aider.agents.cli_agent import CliAgent, CliAgentError
    agent = CliAgent(name)
    if not agent.is_available():
        return f"[cli:{name}] binary '{agent.spec['binary']}' not found on PATH."
    try:
        return agent.run(prompt, cwd=cwd)
    except CliAgentError as e:
        return f"[cli:{name}] error: {e}"


def _cmd_cli(self_commands, args: str) -> None:
    """Handle the /cli command."""
    io = self_commands.io
    coder = getattr(self_commands, "coder", None)
    cwd = getattr(coder, "root", None) if coder else None

    args = args.strip()

    if not args or args in ("help", "--help", "-h"):
        io.tool_output("Usage: /cli <tool> <prompt>")
        io.tool_output("")
        io.tool_output("Tools:  gemini  claude  codex  kimi")
        io.tool_output("")
        io.tool_output("Examples:")
        io.tool_output("  /cli gemini explain the auth flow in auth.py")
        io.tool_output("  /cli claude review this function for security issues")
        io.tool_output("  /cli codex add type annotations to models.py")
        io.tool_output("  /cli kimi refactor this to use async/await")
        io.tool_output("")
        io.tool_output("Use '/cli list' to check which CLIs are available.")
        return

    if args == "list":
        from aider.agents.cli_agent import CliAgent, _CLI_SPECS
        io.tool_output("CLI agents:")
        _modes = {"kimi": "Wire/subagents", "gemini": "headless", "claude": "print", "codex": "exec"}
        for name in sorted(_CLI_SPECS):
            agent = CliAgent(name)
            status = "✓ available" if agent.is_available() else "✗ not found"
            mode = _modes.get(name, "oneshot")
            io.tool_output(f"  {name:<12} {status:<18} [{mode}]")
        return

    # Parse: first word = tool name, rest = prompt
    parts = args.split(None, 1)
    if len(parts) < 2:
        io.tool_error("/cli requires a tool name and a prompt. Try: /cli gemini <your prompt>")
        return

    tool_name, prompt = parts[0].lower(), parts[1]

    io.tool_output(f"[cli:{tool_name}] running...")
    output = _run_cli(tool_name, prompt, cwd=cwd)
    io.tool_output(output)


def _completions_cli(self_commands):
    """Tab-completions for /cli."""
    from aider.agents.cli_agent import _CLI_SPECS, _CLI_ALIASES
    completions = [("list", "Show available CLIs")]
    for name in sorted(_CLI_SPECS):
        completions.append((name, f"Run one-shot prompt via {name} CLI"))
    for alias, target in sorted(_CLI_ALIASES.items()):
        completions.append((alias, f"Alias for {target}"))
    return completions


def on_pre_send(
    messages: list,
    model: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Warn when a cli: model name is used — these need the /cli command instead.
    """
    if model and model.lower().startswith("cli:"):
        cli_name = model[4:]
        return {
            "model": model,
            "_cli_warning": (
                f"Model '{model}' looks like a CLI agent. "
                f"Use /cli {cli_name} <prompt> for one-shot CLI invocation."
            ),
        }
    return {"model": model} if model else {}


def register_hooks(hooks_manager) -> None:
    """Register CLI agent hooks and the /cli slash command."""
    import types

    hooks_manager.register("pre_send", on_pre_send)

    # Inject /cli command into the live Commands instance if available
    commands = getattr(hooks_manager, "commands", None)
    if commands is not None:
        commands.cmd_cli = types.MethodType(_cmd_cli, commands)
        commands.completions_cli = types.MethodType(_completions_cli, commands)
        if getattr(hooks_manager, "io", None):
            hooks_manager.io.tool_output("CLI agent hook registered (/cli command available)")
