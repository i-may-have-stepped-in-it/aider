"""
CLI Agent — one-shot invocations of native AI CLI tools.

Supports: gemini, claude, codex, kimi

For gemini/claude/codex, uses simple headless/oneshot modes:
  cli:gemini  → gemini -p "<prompt>" --yolo
  cli:claude  → claude -p "<prompt>"
  cli:codex   → codex exec "<prompt>"

For kimi, uses the Wire protocol (kimi --wire --yolo) which supports:
  - Native subagent spawning via the Task tool
  - Auto-approved tool calls (Shell, file ops) with --yolo
  - Structured streaming events (ContentPart, ToolCall, SubagentEvent)
  - Full file system access in the working directory

Usage:
  from aider.agents.cli_agent import CliAgent
  result = CliAgent("kimi").run("refactor auth.py", cwd="/path/to/repo")
  result = CliAgent("gemini").run("explain this function", cwd="/path/to/repo")
"""

import json
import os
import shutil
import subprocess
import threading
import uuid
from typing import Optional

# CLI invocation specs for simple headless/print modes
_CLI_SPECS: dict[str, dict] = {
    "gemini": {
        "binary": "gemini",
        "args_before": [],
        "prompt_flag": "-p",  # gemini -p "prompt" --yolo
        "args_after": ["--yolo"],
    },
    "claude": {
        "binary": "claude",
        "args_before": [],
        "prompt_flag": "-p",  # claude -p "prompt"
        "args_after": [],
    },
    "codex": {
        "binary": "codex",
        "args_before": ["exec"],  # codex exec "prompt"
        "prompt_flag": None,  # positional
        "args_after": [],
    },
    # kimi uses Wire protocol — see KimiWireClient below
    "kimi": {
        "binary": "kimi",
        "args_before": [],
        "prompt_flag": None,
        "args_after": [],
    },
}

# Aliases
_CLI_ALIASES: dict[str, str] = {
    "gca": "gemini",
    "gemini-cli": "gemini",
    "gemini-coding-assist": "gemini",
    "claude-cli": "claude",
    "codex-cli": "codex",
    "kimi-cli": "kimi",
}


class CliAgentError(Exception):
    pass


class KimiWireClient:
    """
    Communicates with kimi via its Wire protocol (JSON-RPC 2.0 over stdio).

    Starts `kimi --wire --yolo [--work-dir <cwd>]`, does the initialize
    handshake, sends a prompt, collects all ContentPart text events, and
    returns the concatenated output when the turn finishes.

    With --yolo, kimi auto-approves all tool calls (Shell, file writes, etc.)
    and will use its Task tool to spawn subagents when it deems necessary.
    """

    PROTOCOL_VERSION = "1.5"

    def __init__(self, timeout: int = 600, env: Optional[dict] = None):
        self.timeout = timeout
        self.extra_env = env or {}

    def run(self, prompt: str, cwd: Optional[str] = None) -> str:
        """
        Run a prompt through kimi via Wire protocol.

        Returns:
            All text output from the assistant turn.

        Raises:
            CliAgentError on process failure or timeout.
        """
        if not shutil.which("kimi"):
            raise CliAgentError("kimi binary not found on PATH.")

        cmd = ["kimi", "--wire", "--yolo"]
        if cwd:
            cmd += ["--work-dir", cwd]

        env = {**os.environ, **self.extra_env}

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd,
                env=env,
            )
        except FileNotFoundError:
            raise CliAgentError("kimi binary not found.")

        text_parts: list[str] = []
        done = threading.Event()

        def _read_responses():
            """Read JSON-RPC messages from kimi stdout and handle them."""
            pending_requests: dict[str, dict] = {}  # id → params

            while True:
                try:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Notification: event from agent (no id)
                    if "method" in msg and msg.get("method") == "event":
                        params = msg.get("params", {})
                        etype = params.get("type", "")
                        payload = params.get("payload", {})

                        if etype == "ContentPart" and payload.get("type") == "text":
                            text_parts.append(payload.get("text", ""))

                    # Request from agent to client (has id + method == "request")
                    elif "method" in msg and msg.get("method") == "request" and "id" in msg:
                        req_id = msg["id"]
                        rparams = msg.get("params", {})
                        rtype = rparams.get("type", "")

                        if rtype == "ApprovalRequest":
                            # Auto-approve (--yolo should handle this, but be safe)
                            approval_id = rparams.get("payload", {}).get("id", "")
                            _send(
                                proc,
                                {
                                    "jsonrpc": "2.0",
                                    "id": req_id,
                                    "result": {
                                        "request_id": approval_id,
                                        "response": "approve_for_session",
                                    },
                                },
                            )

                        elif rtype == "QuestionRequest":
                            # Answer with empty (skip questions)
                            q_id = rparams.get("payload", {}).get("id", "")
                            _send(
                                proc,
                                {
                                    "jsonrpc": "2.0",
                                    "id": req_id,
                                    "result": {"request_id": q_id, "answers": {}},
                                },
                            )

                        elif rtype == "ToolCallRequest":
                            # External tool calls — we haven't registered any, but handle gracefully
                            tc_id = rparams.get("payload", {}).get("id", "")
                            _send(
                                proc,
                                {
                                    "jsonrpc": "2.0",
                                    "id": req_id,
                                    "result": {
                                        "tool_call_id": tc_id,
                                        "return_value": {
                                            "is_error": True,
                                            "output": "Tool not available in aider context.",
                                            "message": "Tool not registered.",
                                            "display": [],
                                        },
                                    },
                                },
                            )

                    # Response to our requests (has id, no method)
                    elif "id" in msg and "method" not in msg:
                        req_id = msg["id"]
                        if req_id in pending_requests:
                            pending_requests[req_id]["response"] = msg
                            pending_requests[req_id]["event"].set()

                except Exception:
                    break

            done.set()

        def _send(p, obj):
            try:
                p.stdin.write(json.dumps(obj) + "\n")
                p.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

        reader = threading.Thread(target=_read_responses, daemon=True)
        reader.start()

        # 1. initialize handshake
        init_id = str(uuid.uuid4())
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": init_id,
                "params": {
                    "protocol_version": self.PROTOCOL_VERSION,
                    "client": {"name": "aider-cli-agent", "version": "1.0.0"},
                    "capabilities": {"supports_question": True},
                },
            },
        )

        # Small settle time — initialize response comes quickly
        import time

        time.sleep(0.3)

        # 2. send prompt
        prompt_id = str(uuid.uuid4())
        _send(
            proc,
            {
                "jsonrpc": "2.0",
                "method": "prompt",
                "id": prompt_id,
                "params": {"user_input": prompt},
            },
        )

        # 3. wait for completion
        finished = done.wait(timeout=self.timeout)
        if not finished:
            proc.terminate()
            raise CliAgentError(f"kimi Wire session timed out after {self.timeout}s")

        proc.stdin.close()
        proc.wait(timeout=10)

        if proc.returncode not in (0, None) and not text_parts:
            stderr = proc.stderr.read().strip() if proc.stderr else ""
            raise CliAgentError(f"kimi exited with code {proc.returncode}. stderr: {stderr[:500]}")

        return "".join(text_parts).strip()


class CliAgent:
    """
    Runs a one-shot prompt through a native AI CLI tool.

    For kimi, uses the Wire protocol for full subagent/tool support.
    For gemini/claude/codex, uses their respective headless/print modes.

    Args:
        name: CLI name ("gemini", "claude", "codex", "kimi") or an alias.
        timeout: Seconds to wait for the CLI to respond (default: 300 for
                 simple CLIs, 600 for kimi Wire sessions).
        env: Extra environment variables to pass to the subprocess.
    """

    def __init__(
        self,
        name: str,
        timeout: Optional[int] = None,
        env: Optional[dict] = None,
    ):
        name = name.lower().strip()
        self.name = _CLI_ALIASES.get(name, name)
        if self.name not in _CLI_SPECS:
            raise CliAgentError(
                f"Unknown CLI agent '{name}'. "
                f"Available: {', '.join(sorted(_CLI_SPECS))} "
                f"(aliases: {', '.join(sorted(_CLI_ALIASES))})"
            )
        self.spec = _CLI_SPECS[self.name]
        # kimi Wire sessions can run longer due to subagent spawning
        self.timeout = timeout or (600 if self.name == "kimi" else 300)
        self.extra_env = env or {}

    def is_available(self) -> bool:
        """Return True if the CLI binary is on PATH."""
        return shutil.which(self.spec["binary"]) is not None

    def build_command(self, prompt: str) -> list[str]:
        """Build the subprocess command list (for non-kimi CLIs)."""
        spec = self.spec
        cmd: list[str] = [spec["binary"]] + spec["args_before"]
        if spec["prompt_flag"] is None:
            cmd.append(prompt)
        else:
            cmd += [spec["prompt_flag"], prompt]
        cmd += spec["args_after"]
        return cmd

    def run(self, prompt: str, cwd: Optional[str] = None) -> str:
        """
        Run the CLI with a one-shot prompt.

        kimi uses Wire protocol (subagent-capable).
        All others use their headless/print/exec modes.

        Returns:
            Text output from the CLI run.

        Raises:
            CliAgentError: if the binary is not found or the process fails.
        """
        if not self.is_available():
            raise CliAgentError(f"CLI binary '{self.spec['binary']}' not found on PATH.")

        if self.name == "kimi":
            client = KimiWireClient(timeout=self.timeout, env=self.extra_env)
            return client.run(prompt, cwd=cwd)

        # Simple subprocess for gemini / claude / codex
        cmd = self.build_command(prompt)
        env = {**os.environ, **self.extra_env}

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=cwd,
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise CliAgentError(f"CLI '{self.name}' timed out after {self.timeout}s")
        except FileNotFoundError:
            raise CliAgentError(f"CLI binary '{self.spec['binary']}' not found.")

        if result.returncode != 0:
            raise CliAgentError(
                f"CLI '{self.name}' exited with code {result.returncode}.\n"
                f"stderr: {result.stderr.strip()}"
            )

        return result.stdout.strip()


def is_cli_model(model_name: str) -> bool:
    """Return True if this model name should be handled by CliAgent."""
    if not model_name:
        return False
    lower = model_name.lower()
    if lower.startswith("cli:"):
        return True
    return lower in _CLI_ALIASES


def cli_name_from_model(model_name: str) -> str:
    """Extract CLI name from a model string like 'cli:kimi' or 'gemini-cli'."""
    lower = model_name.lower()
    if lower.startswith("cli:"):
        return lower[4:]
    return _CLI_ALIASES.get(lower, lower)


def run_oneshot(model_name: str, prompt: str, cwd: Optional[str] = None) -> str:
    """
    Convenience wrapper: route a model name + prompt to the correct CLI.

    Example:
        run_oneshot("cli:kimi", "refactor auth.py to use async/await")
        run_oneshot("cli:gemini", "explain this function")
        run_oneshot("codex-cli", "add type annotations")
    """
    name = cli_name_from_model(model_name)
    agent = CliAgent(name)
    return agent.run(prompt, cwd=cwd)
