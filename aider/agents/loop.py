import shlex
import subprocess
import time
import os
from typing import Optional, List

class AutonomousAgent:
    """
    Advanced Autonomous Agent loop for Aider.
    Parity with Windsurf/Kimi/Devin 'Agent' mode.
    """

    def __init__(self, coder, max_turns: int = 5, max_cost: float = 2.0):
        self.coder = coder
        self.max_turns = max_turns
        self.max_cost = max_cost
        self.start_cost = 0.0

    def run_task(self, instruction: str, test_command: Optional[str] = None):
        """
        Execute a task autonomously. 
        If test_command is provided, uses it as the success criterion.
        """
        self.start_cost = getattr(self.coder, 'total_cost', 0.0)
        current_prompt = instruction
        
        self.coder.io.tool_output(f"🚀 Starting autonomous task: {instruction}")
        if test_command:
            self.coder.io.tool_output(f"🎯 Success criterion: '{test_command}' passes (exit 0)")

        for turn in range(self.max_turns):
            # Check cost budget
            current_cost = getattr(self.coder, 'total_cost', 0.0) - self.start_cost
            if current_cost > self.max_cost:
                self.coder.io.tool_error(f"💸 Cost budget exceeded (${current_cost:.2f} > ${self.max_cost:.2f})")
                break

            self.coder.io.tool_output(f"\n[Agent Turn {turn + 1}/{self.max_turns}] 🧠 Thinking...")
            
            # 1. Implementation Phase
            # We use a specific 'Agent Persona' for autonomous tasks if needed
            self.coder.run(with_message=current_prompt)

            # 2. Verification Phase
            if not test_command:
                # If no test command, we might ask the user for feedback or use a linter
                if self.coder.io.confirm_ask("Is the task complete?", default="y"):
                    self.coder.io.tool_output("✅ Task completed via user confirmation.")
                    return True
                else:
                    current_prompt = "The task is not yet complete. Please continue."
                    continue

            self.coder.io.tool_output(f"[Agent Turn {turn + 1}] 🧪 Validating with: {test_command}")
            try:
                # SECURITY: Parse command with shlex to avoid shell injection
                cmd_parts = shlex.split(test_command)
                if not cmd_parts:
                    self.coder.io.tool_error("❌ Invalid test command (empty after parsing)")
                    break
                
                result = subprocess.run(
                    cmd_parts,
                    shell=False,
                    capture_output=True,
                    text=True,
                    cwd=self.coder.root,
                    timeout=60 # 60s safety timeout for tests
                )
                
                if result.returncode == 0:
                    self.coder.io.tool_output(f"✅ Success! All tests passed in {turn + 1} turns.")
                    return True
                
                # 3. Reflection Phase: Detailed error reporting
                self.coder.io.tool_error(f"❌ Validation failed (Exit {result.returncode})")
                
                # Semantic Compression: If output is huge, we should truncate it
                stdout = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
                stderr = result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr
                
                current_prompt = (
                    f"The previous attempt failed validation.\n"
                    f"COMMAND: {test_command}\n"
                    f"STDOUT (last 2k chars):\n{stdout}\n"
                    f"STDERR (last 2k chars):\n{stderr}\n"
                    "Please analyze the failure and provide a fix."
                )
            except subprocess.TimeoutExpired:
                self.coder.io.tool_error("❌ Validation timed out (60s)")
                current_prompt = "The test command timed out. This might mean an infinite loop or slow performance. Please check."
            except Exception as e:
                self.coder.io.tool_error(f"❌ Validation crashed: {e}")
                break

        self.coder.io.tool_error(f"⚠️ Task failed to converge within {self.max_turns} turns.")
        return False
