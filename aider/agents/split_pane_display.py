"""
Split-Pane Display - Addresses deficit from Claude Code Agent Teams

This module provides multi-pane terminal support for viewing multiple agents simultaneously.
Supports tmux on Linux and iTerm2 on Mac.
"""

import logging
import os
import subprocess
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SplitPaneManager:
    """
    Manages split-pane terminal display for multi-agent visualization.

    Supports:
    - tmux on Linux/Mac
    - iTerm2 on Mac (via AppleScript)
    """

    def __init__(self, display_mode: str = "in-process"):
        """
        Initialize split-pane manager.

        Args:
            display_mode: "in-process", "split", or "tmux"
        """
        self.display_mode = display_mode
        self.panes: Dict[str, Dict[str, any]] = {}
        self.session_name = f"aider-agents-{int(time.time())}"

        # Detect terminal capabilities
        self.has_tmux = self._check_tmux()
        self.has_iterm2 = self._check_iterm2()

    def _check_tmux(self) -> bool:
        """Check if tmux is available."""
        try:
            result = subprocess.run(["tmux", "-V"], capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def _check_iterm2(self) -> bool:
        """Check if iTerm2 is available (Mac only)."""
        if not self._is_mac():
            return False

        try:
            result = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to get name of every application process',
                ],
                capture_output=True,
                text=True,
            )
            return "iTerm2" in result.stdout
        except Exception:
            return False

    def _is_mac(self) -> bool:
        """Check if running on Mac."""
        return os.uname().sysname == "Darwin"

    def create_pane(self, agent_name: str, command: str) -> bool:
        """
        Create a new pane for an agent.

        Args:
            agent_name: Name of the agent
            command: Command to run in the pane

        Returns:
            True if successful, False otherwise
        """
        if self.display_mode == "in-process":
            logger.info(f"In-process mode: {agent_name} would run in main terminal")
            self.panes[agent_name] = {"command": command, "mode": "in-process"}
            return True

        if self.display_mode == "tmux" or (self.display_mode == "split" and self.has_tmux):
            return self._create_tmux_pane(agent_name, command)

        if self.display_mode == "split" and self.has_iterm2:
            return self._create_iterm2_pane(agent_name, command)

        logger.warning(f"No split-pane support available for {agent_name}")
        return False

    def _create_tmux_pane(self, agent_name: str, command: str) -> bool:
        """
        Create a tmux pane for an agent.

        Args:
            agent_name: Name of the agent
            command: Command to run in the pane

        Returns:
            True if successful, False otherwise
        """
        try:
            # Create new session if first pane
            if not self.panes:
                subprocess.run(
                    [
                        "tmux",
                        "new-session",
                        "-d",
                        "-s",
                        self.session_name,
                        "-n",
                        agent_name,
                        command,
                    ],
                    check=True,
                )
                logger.info(f"Created tmux session: {self.session_name}")
            else:
                # Split window for additional panes
                subprocess.run(
                    [
                        "tmux",
                        "split-window",
                        "-t",
                        self.session_name,
                        "-h",  # Horizontal split
                        command,
                    ],
                    check=True,
                )
                logger.info(f"Created tmux pane for: {agent_name}")

            self.panes[agent_name] = {
                "command": command,
                "mode": "tmux",
                "session": self.session_name,
            }

            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create tmux pane: {e}")
            return False

    def _create_iterm2_pane(self, agent_name: str, command: str) -> bool:
        """
        Create an iTerm2 pane for an agent (Mac only).

        Args:
            agent_name: Name of the agent
            command: Command to run in the pane

        Returns:
            True if successful, False otherwise
        """
        try:
            # AppleScript to create iTerm2 split
            script = f"""
            tell application "iTerm2"
                tell current window
                    create tab with default profile
                    tell current session
                        write text "{command}"
                    end tell
                end tell
            end tell
            """

            subprocess.run(["osascript", "-e", script], check=True)

            self.panes[agent_name] = {"command": command, "mode": "iterm2"}

            logger.info(f"Created iTerm2 pane for: {agent_name}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create iTerm2 pane: {e}")
            return False

    def send_to_pane(self, agent_name: str, text: str) -> bool:
        """
        Send text to a specific pane.

        Args:
            agent_name: Name of the agent
            text: Text to send

        Returns:
            True if successful, False otherwise
        """
        if agent_name not in self.panes:
            logger.error(f"Pane {agent_name} not found")
            return False

        pane = self.panes[agent_name]

        if pane["mode"] == "tmux":
            return self._send_to_tmux_pane(agent_name, text)
        elif pane["mode"] == "iterm2":
            return self._send_to_iterm2_pane(agent_name, text)
        else:
            logger.warning(f"Cannot send to {pane['mode']} pane")
            return False

    def _send_to_tmux_pane(self, agent_name: str, text: str) -> bool:
        """Send text to a tmux pane."""
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", f"{self.session_name}", text, "Enter"], check=True
            )

            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to send to tmux pane: {e}")
            return False

    def _send_to_iterm2_pane(self, agent_name: str, text: str) -> bool:
        """Send text to an iTerm2 pane."""
        try:
            script = f"""
            tell application "iTerm2"
                tell current window
                    tell current session
                        write text "{text}"
                    end tell
                end tell
            end tell
            """

            subprocess.run(["osascript", "-e", script], check=True)

            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to send to iTerm2 pane: {e}")
            return False

    def list_panes(self) -> List[str]:
        """List all panes."""
        return list(self.panes.keys())

    def switch_to_pane(self, agent_name: str) -> bool:
        """
        Switch focus to a specific pane.

        Args:
            agent_name: Name of the agent

        Returns:
            True if successful, False otherwise
        """
        if agent_name not in self.panes:
            logger.error(f"Pane {agent_name} not found")
            return False

        pane = self.panes[agent_name]

        if pane["mode"] == "tmux":
            try:
                subprocess.run(["tmux", "select-pane", "-t", f"{self.session_name}"], check=True)

                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to switch tmux pane: {e}")
                return False

        return False

    def close_pane(self, agent_name: str) -> bool:
        """
        Close a specific pane.

        Args:
            agent_name: Name of the agent

        Returns:
            True if successful, False otherwise
        """
        if agent_name not in self.panes:
            return False

        pane = self.panes[agent_name]

        if pane["mode"] == "tmux":
            try:
                subprocess.run(["tmux", "kill-pane", "-t", f"{self.session_name}"], check=True)

                del self.panes[agent_name]
                return True
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to close tmux pane: {e}")
                return False

        return False

    def close_all(self):
        """Close all panes and cleanup."""
        if self.display_mode == "tmux" and self.has_tmux:
            try:
                subprocess.run(["tmux", "kill-session", "-t", self.session_name], check=True)
                logger.info(f"Closed tmux session: {self.session_name}")
            except subprocess.CalledProcessError:
                pass

        self.panes.clear()

    def get_display_instructions(self) -> str:
        """Get instructions for using the display."""
        if self.display_mode == "in-process":
            return """
In-Process Display Mode:
- All agents share your terminal
- Use Shift+Up/Shift+Down to navigate between sessions (not implemented yet)
- Works everywhere
"""

        if self.display_mode == "tmux" and self.has_tmux:
            return """
tmux Split-Pane Display:
- Each agent gets its own pane
- Use Ctrl+B + Arrow keys to navigate between panes
- Use Ctrl+B + z to toggle zoom (focus on one pane)
- Use Ctrl+B + q to show pane numbers
- Watch all agents simultaneously
"""

        if self.display_mode == "split" and self.has_iterm2:
            return """
iTerm2 Split-Pane Display:
- Each agent gets its own tab
- Use Cmd+Shift+Arrow to navigate between tabs
- Use Cmd+Option+Arrow to split panes
- Watch all agents simultaneously
"""

        return "No split-pane support available"

    @staticmethod
    def detect_best_display_mode() -> str:
        """
        Detect the best display mode for the current environment.

        Returns:
            "tmux", "iterm2", or "in-process"
        """
        manager = SplitPaneManager()

        if manager.has_tmux:
            return "tmux"

        if manager.has_iterm2:
            return "iterm2"

        return "in-process"


# Integration with ArchitectCoder
class AgentDisplayManager:
    """Integration helper for using split-pane display with ArchitectCoder."""

    def __init__(self, display_mode: Optional[str] = None):
        """
        Initialize display manager.

        Args:
            display_mode: Display mode (auto-detected if None)
        """
        self.display_mode = display_mode or SplitPaneManager.detect_best_display_mode()
        self.manager = SplitPaneManager(self.display_mode)

    def spawn_agent_display(self, agent_name: str, command: str) -> bool:
        """
        Spawn an agent with its own display pane.

        Args:
            agent_name: Name of the agent
            command: Command to run the agent

        Returns:
            True if successful, False otherwise
        """
        return self.manager.create_pane(agent_name, command)

    def send_to_agent(self, agent_name: str, message: str) -> bool:
        """
        Send a message to an agent.

        Args:
            agent_name: Name of the agent
            message: Message to send

        Returns:
            True if successful, False otherwise
        """
        return self.manager.send_to_pane(agent_name, message)

    def get_display_status(self) -> Dict[str, any]:
        """Get display status."""
        return {
            "display_mode": self.display_mode,
            "panes": self.manager.list_panes(),
            "instructions": self.manager.get_display_instructions(),
        }


if __name__ == "__main__":
    # Demo usage
    print("Detecting best display mode...")
    best_mode = SplitPaneManager.detect_best_display_mode()
    print(f"Best mode: {best_mode}")

    manager = SplitPaneManager(best_mode)

    print("\n" + manager.get_display_instructions())

    # Example: Create panes for different agents
    if best_mode == "tmux":
        print("\nCreating panes for demo agents...")
        manager.create_pane("backend-agent", "echo 'Backend Agent Running'")
        manager.create_pane("frontend-agent", "echo 'Frontend Agent Running'")
        manager.create_pane("test-agent", "echo 'Test Agent Running'")

        print(f"\nCreated panes: {manager.list_panes()}")
        print("\nPress Ctrl+C to close all panes...")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nClosing all panes...")
            manager.close_all()
    else:
        print("\nSplit-pane display not available in this environment")
        print("Using in-process mode instead")
