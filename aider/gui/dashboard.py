from typing import Any, Dict, Optional
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns

from ..io_interfaces import TerminalUIObserver

class LiveDashboard(TerminalUIObserver):
    """
    Enterprise-grade Live Dashboard for Aider.
    Uses rich.live to provide a persistent, non-flickering status display.
    """

    def __init__(self, console: Console = None):
        self.console = console or Console()
        self.live: Optional[Live] = None
        self.layout = Layout()
        
        # State
        self.current_phase = "Idle"
        self.phase_status = "pending"
        self.phases = ["Librarian", "Architect", "Reviewer", "Security Scan", "Editor"]
        self.phase_results = {p: "pending" for p in self.phases}
        
        self.total_cost = 0.0
        self.budget_percentage = 0.0
        
        self.security_status = "Safe"
        self.security_color = "green"
        self.security_violations = 0
        
        self.agents: Dict[str, Dict] = {}
        self.reasoning_text = ""
        
        self._init_layout()

    def _init_layout(self):
        """Initialize the dashboard layout."""
        self.layout.split(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3),
        )
        
        self.layout["main"].split_row(
            Layout(name="pipeline", ratio=1),
            Layout(name="reasoning", ratio=2),
        )

    def start(self):
        """Start the live dashboard."""
        self.live = Live(self.layout, console=self.console, refresh_per_second=4, transient=True)
        self.live.start()

    def stop(self):
        """Stop the live dashboard."""
        if self.live:
            self.live.stop()
            self.live = None

    def _update_renderables(self):
        """Update the renderables in the layout based on current state."""
        # Header
        self.layout["header"].update(
            Panel(
                Columns([
                    Text(f"Mode: AUTO", style="bold green"),
                    Text(f"Phase: {self.current_phase}", style="bold yellow"),
                    Text(f"Security: {self.security_status}", style=f"bold {self.security_color}"),
                    Text(f"Budget: ${self.total_cost:.3f} ({self.budget_percentage:.1f}%)", style="bold magenta"),
                ], expand=True),
                title="Aider Autonomous Dashboard",
                border_style="blue"
            )
        )

        # Pipeline
        pipeline_table = Table(box=None, expand=True)
        pipeline_table.add_column("Phase", ratio=1)
        pipeline_table.add_column("Status", width=10)

        for phase in self.phases:
            status = self.phase_results.get(phase, "pending")
            color = "green" if status == "complete" else "yellow" if status == "running" else "white"
            icon = "✓" if status == "complete" else "▶" if status == "running" else "○"
            pipeline_table.add_row(
                Text(phase, style=color),
                Text(f"{icon} {status}", style=color)
            )
        
        self.layout["pipeline"].update(
            Panel(pipeline_table, title="Task Pipeline", border_style="cyan")
        )

        # Reasoning
        self.layout["reasoning"].update(
            Panel(
                Text(self.reasoning_text or "Waiting for reasoning...", overflow="ellipsis"),
                title="LLM Reasoning Stream",
                border_style="green"
            )
        )

        # Footer (Agents)
        agent_count = len([a for a in self.agents.values() if a['status'] == 'running'])
        self.layout["footer"].update(
            Panel(
                Text(f"Active Sub-Agents: {agent_count}", justify="center"),
                title="Swarm Status",
                border_style="dim"
            )
        )

    # Observer Implementation
    def on_phase_change(self, phase: str, status: str = "running"):
        self.current_phase = phase
        self.phase_results[phase] = status
        if status == "complete":
            # If a phase completes, mark previous phases as complete too (simplified)
            idx = self.phases.index(phase) if phase in self.phases else -1
            if idx != -1:
                for i in range(idx):
                    self.phase_results[self.phases[i]] = "complete"
        
        self._update_renderables()

    def on_cost_update(self, total: float, percentage: float):
        self.total_cost = total
        self.budget_percentage = percentage
        self._update_renderables()

    def on_agent_status(self, agent_id: str, status: str, task: str = None):
        if agent_id not in self.agents:
            self.agents[agent_id] = {"status": status, "task": task}
        else:
            self.agents[agent_id]["status"] = status
            if task:
                self.agents[agent_id]["task"] = task
        self._update_renderables()

    def on_policy_check(self, result: Any):
        """Update security status on the dashboard."""
        if result.success:
            if result.violations:
                self.security_status = "Warning"
                self.security_color = "yellow"
            else:
                self.security_status = "Safe"
                self.security_color = "green"
        else:
            self.security_status = "Blocked"
            self.security_color = "red"
        
        self.security_violations = len(result.violations)
        self._update_renderables()

    def on_tool_progress(self, tool_name: str, message: str, progress: float = None):
        # We could add a tool progress bar to the dashboard
        pass

    def update_reasoning(self, text: str):
        """Update the reasoning pane."""
        self.reasoning_text = text
        self._update_renderables()
