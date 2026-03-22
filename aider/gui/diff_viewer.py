"""
High-Fidelity TUI Diff Reviewer for Aider.

This module provides an interactive terminal interface for reviewing 
code changes before they are applied to the filesystem.
"""

import difflib
from rich.console import Console
from rich.panel import Panel

class InteractiveDiffViewer:
    """
    Interactive TUI for reviewing code diffs with syntax highlighting.
    """

    def __init__(self, io):
        self.io = io
        self.console = getattr(io, "console", Console())

    def show_diff(self, filename: str, old_content: str, new_content: str):
        """Display a beautiful diff of the changes."""
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()
        
        diff = list(difflib.unified_diff(
            old_lines, new_lines, 
            fromfile=f"a/{filename}", 
            tofile=f"b/{filename}",
            lineterm=""
        ))

        if not diff:
            self.io.tool_output(f"No changes detected in {filename}")
            return

        # Create a professional diff table
        table = Table(title=f"Reviewing changes: {filename}", box=None, expand=True)
        table.add_column("Line", style="dim", width=4)
        table.add_column("Diff", ratio=1)

        for line in diff[2:]:  # Skip headers
            if line.startswith("+"):
                style = "green"
            elif line.startswith("-"):
                style = "red"
            elif line.startswith("@"):
                style = "cyan"
            else:
                style = "white"
            
            # Simplified line numbering for the TUI
            table.add_row("", Text(line, style=style))

        self.console.print(Panel(table, border_style="blue"))

    def request_approval(self, filename: str) -> str:
        """
        Ask the user for approval of the changes.
        Returns: "accept", "reject", "edit", or "quit"
        """
        self.console.print(f"\n[bold yellow]Reviewing {filename}[/bold yellow]")
        self.console.print("[bold cyan](a)[/bold cyan] Accept  [bold red](r)[/bold red] Reject  [bold yellow](e)[/bold yellow] Edit  [bold magenta](q)[/bold magenta] Quit")
        
        while True:
            choice = input("Choice [a/r/e/q]: ").lower().strip()
            if choice in ('a', 'accept'): return "accept"
            if choice in ('r', 'reject'): return "reject"
            if choice in ('e', 'edit'): return "edit"
            if choice in ('q', 'quit'): return "quit"
            self.console.print("Invalid choice. Please select [a/r/e/q].")

    def review_file(self, filename: str, old_content: str, new_content: str) -> str:
        """Full review cycle for a single file."""
        self.show_diff(filename, old_content, new_content)
        return self.request_approval(filename)
