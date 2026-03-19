import os
import sqlite3
from pathlib import Path


class ToolCommandsMixin:
    """System prompt, search, index, MCP, and tool-control commands."""

    def cmd_models(self, args):
        "Search the list of available models"
        from aider import models

        args = args.strip()
        if args:
            models.print_matching_models(self.io, args)
        else:
            self.show_command_usage(
                "/models",
                error="Please provide a partial model name to search for.",
            )

    def cmd_web(self, args, return_content=False):
        "Scrape a webpage, convert to markdown and send in a message"
        from aider import commands as commands_module

        url = args.strip()
        if not url:
            self.show_command_usage("/web", error="Please provide a URL to scrape.")
            return

        self.io.tool_output(f"Scraping {url}...")
        if not self.scraper:
            scraper_cls = commands_module.Scraper
            install_playwright_fn = commands_module.install_playwright

            if scraper_cls is None or install_playwright_fn is None:
                from aider.scrape import Scraper, install_playwright

                if scraper_cls is None:
                    scraper_cls = Scraper
                    commands_module.Scraper = Scraper
                if install_playwright_fn is None:
                    install_playwright_fn = install_playwright
                    commands_module.install_playwright = install_playwright

            disable_playwright = getattr(self.args, "disable_playwright", False)
            if disable_playwright:
                res = False
            else:
                res = install_playwright_fn(self.io)
                if not res:
                    self.io.tool_warning("Unable to initialize playwright.")

            self.scraper = scraper_cls(
                print_error=self.io.tool_error,
                playwright_available=res,
                verify_ssl=self.verify_ssl,
            )

        content = self.scraper.scrape(url) or ""
        content = f"Here is the content of {url}:\n\n" + content
        if return_content:
            return content

        self.io.tool_output("... added to chat.")
        self.coder.cur_messages += [
            dict(role="user", content=content),
            dict(role="assistant", content="Ok."),
        ]

    def cmd_system(self, args):
        """Set a custom system prompt, load from file, or reset to default."""
        from aider.commands import SwitchCoder

        args = args.strip()
        if not args:
            if self.coder.system_prompt_override:
                self.io.tool_output("Current custom system prompt:")
                self.io.tool_output(self.coder.system_prompt_override)
            else:
                self.io.tool_output("Using default system prompt.")
            return

        if args == "view":
            chunks = self.coder.format_chat_chunks()
            self.io.tool_output("Final rendered system prompt:")
            self.io.tool_output("---")
            self.io.tool_output(chunks.system[0]["content"])
            self.io.tool_output("---")
            self.io.tool_output("\nAvailable Template Variables:")
            self.io.tool_output("  {fence}, {quad_backtick_reminder}, {final_reminders},")
            self.io.tool_output("  {platform}, {shell_cmd_prompt}, {rename_with_shell},")
            self.io.tool_output("  {shell_cmd_reminder}, {go_ahead_tip}, {language}")
            return

        new_prompt = None
        mode = "replace"

        if args.startswith("--append "):
            mode = "append"
            args = args[len("--append ") :].strip()
        elif args.startswith("--prepend "):
            mode = "prepend"
            args = args[len("--prepend ") :].strip()

        if args == "reset":
            new_prompt = None
            self.io.tool_output("System prompt reset to default.")
        elif args.startswith("-f ") or args.startswith("--file "):
            filename = args.split(None, 1)[1]
            try:
                content = self.io.read_text(filename)
                if content is None:
                    self.io.tool_error(f"Unable to read file: {filename}")
                    return
                new_prompt = content
                self.io.tool_output(f"Loaded system prompt from {filename}")
            except Exception as e:
                self.io.tool_error(f"Error reading system prompt from {filename}: {e}")
                return
        else:
            if args.startswith('"') and args.endswith('"') and len(args) >= 2:
                new_prompt = args[1:-1]
            else:
                new_prompt = args

        if new_prompt and mode == "append":
            new_prompt = self.coder.gpt_prompts.main_system + "\n\n" + new_prompt
            self.io.tool_output("Appended to system prompt.")
        elif new_prompt and mode == "prepend":
            new_prompt = new_prompt + "\n\n" + self.coder.gpt_prompts.main_system
            self.io.tool_output("Prepended to system prompt.")
        elif new_prompt:
            self.io.tool_output("System prompt updated (replaces default).")

        raise SwitchCoder(system_prompt_override=new_prompt)

    def cmd_search_web(self, args):
        """Search the web for information via OpenClaw Gateway."""
        query = args.strip()
        if not query:
            self.show_command_usage("/search-web", error="Please provide a search query.")
            return

        if not hasattr(self.coder, "tool_router"):
            self.io.tool_error("Tool mode not available.")
            return

        self.io.tool_output(f"Searching the web via OpenClaw for: {query}...")
        result = self.coder.tool_router.execute("search_web", {"query": query})

        if result.success:
            self.io.tool_output(result.output)
        else:
            self.io.tool_error(f"Search failed: {result.error}")

    def cmd_index(self, args):
        """Index external directories or search the global semantic index."""
        from aider.indexers.semantic import SemanticIndexer

        args = args.strip()
        if not args:
            self.show_command_usage("/index")
            return

        if args.startswith("add "):
            indexer = SemanticIndexer.get_global()
            path_str = args[len("add ") :].strip()
            path = Path(path_str).resolve()
            if not path.exists() or not path.is_dir():
                self.io.tool_error(f"Directory not found: {path_str}")
                return

            self.io.tool_output(f"Indexing {path} (Global Index)...")
            files = []
            for root, _, fs in os.walk(path):
                for f in fs:
                    if f.endswith((".py", ".js", ".ts", ".c", ".cpp", ".rs", ".go", ".md")):
                        files.append(str(Path(root) / f))

            indexer.update_index(files)
            self.io.tool_output(f"Indexed {len(files)} files.")

        elif args.startswith("doc "):
            self.io.tool_error("/index doc is currently disabled.")
            return

        elif args.startswith("search "):
            query = args[len("search ") :].strip()
            if hasattr(self.coder, "get_semantic_indexer"):
                indexer = self.coder.get_semantic_indexer(start_background=True)
            else:
                indexer = getattr(self.coder, "semantic_indexer", None)

            if indexer is None:
                indexer = SemanticIndexer.get_global(getattr(self.coder, "root", None))

            self.io.tool_output(f"Searching semantic index for: {query}...")
            results = indexer.query(query)
            if results:
                self.io.tool_output("Matches found in semantic index:")
                for path, score in results:
                    self.io.tool_output(f"  [{score:.2f}] {path}")
            else:
                self.io.tool_output("No matches found.")
        elif args == "status":
            with sqlite3.connect(indexer.db_path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM file_cache").fetchone()[0]
            self.io.tool_output(f"Global index contains {count} files.")
        else:
            self.io.tool_error(f"Unknown index action: {args}")

    def cmd_mcp(self, args):
        """Manage MCP (Model Context Protocol) servers."""
        args = args.strip()
        if not args:
            self.show_command_usage("/mcp")
            return

        tool_router = getattr(self.coder, "tool_router", None)
        if not tool_router or not hasattr(tool_router, "mcp_manager"):
            self.io.tool_error("MCP support not available in this coder mode.")
            return

        manager = self.coder.tool_router.mcp_manager

        if args.startswith("add "):
            parts = args[4:].split()
            if len(parts) < 2:
                self.io.tool_error("Usage: /mcp add <name> <cmd> [args...]")
                return
            name = parts[0]
            cmd = parts[1:]
            self.io.tool_output(f"Starting MCP server '{name}'...")
            if manager.add_server(name, cmd):
                self.io.tool_output(f"MCP server '{name}' added successfully.")
            else:
                self.io.tool_error(f"Failed to start MCP server '{name}'.")

        elif args == "list":
            if not manager.servers:
                self.io.tool_output("No active MCP servers.")
                return
            for name, server in manager.servers.items():
                self.io.tool_output(f"Server: {name} ({' '.join(server.command)})")
                if server.tools:
                    self.io.tool_output("  Tools:")
                    for tool in server.tools:
                        self.io.tool_output(f"    - {tool.name}: {tool.description}")
                if server.resources:
                    self.io.tool_output("  Resources:")
                    for r in server.resources:
                        self.io.tool_output(f"    - {r.name} ({r.uri})")
                if server.prompts:
                    self.io.tool_output("  Prompts:")
                    for p in server.prompts:
                        self.io.tool_output(f"    - {p.name}: {p.description}")

        elif args.startswith("resource "):
            uri = args[9:].strip()
            self.io.tool_output(f"Reading MCP resource: {uri}...")
            try:
                res = manager.read_resource(uri)
                for item in res.get("contents", []):
                    if "text" in item:
                        self.io.tool_output(item["text"])
                    else:
                        self.io.tool_output(f"[Binary data: {item.get('mimeType')}]")
            except Exception as e:
                self.io.tool_error(f"Error reading resource: {e}")

        elif args.startswith("remove "):
            name = args[7:].strip()
            if name in manager.servers:
                manager.servers[name].stop()
                del manager.servers[name]
                self.io.tool_output(f"MCP server '{name}' removed.")
            else:
                self.io.tool_error(f"MCP server '{name}' not found.")
        else:
            self.io.tool_error(f"Unknown mcp action: {args}")

    def cmd_settings(self, args):
        "Print out the current settings"
        from aider.format_settings import format_settings

        settings = format_settings(self.parser, self.args)
        announcements = "\n".join(self.coder.get_announcements())

        model_sections = []
        active_models = [
            ("Main model", self.coder.main_model),
            ("Editor model", getattr(self.coder.main_model, "editor_model", None)),
            ("Weak model", getattr(self.coder.main_model, "weak_model", None)),
        ]
        for label, model in active_models:
            if not model:
                continue
            info = getattr(model, "info", {}) or {}
            if not info:
                continue
            model_sections.append(f"{label} ({model.name}):")
            for k, v in sorted(info.items()):
                model_sections.append(f"  {k}: {v}")
            model_sections.append("")

        model_metadata = "\n".join(model_sections)

        output = f"{announcements}\n{settings}"
        if model_metadata:
            output += "\n" + model_metadata
        self.io.tool_output(output)

    def cmd_think_tokens(self, args):
        """Set the thinking token budget."""
        model = self.coder.main_model

        if not args.strip():
            formatted_budget = model.get_thinking_tokens()
            if formatted_budget is None:
                self.io.tool_output("Thinking tokens are not currently set.")
            else:
                budget = model.get_raw_thinking_tokens()
                self.io.tool_output(
                    f"Current thinking token budget: {budget:,} tokens ({formatted_budget})."
                )
            return

        value = args.strip()
        model.set_thinking_tokens(value)

        if value == "0":
            self.io.tool_output("Thinking tokens disabled.")
        else:
            formatted_budget = model.get_thinking_tokens()
            budget = model.get_raw_thinking_tokens()
            self.io.tool_output(
                f"Set thinking token budget to {budget:,} tokens ({formatted_budget})."
            )

        self.io.tool_output()
        announcements = "\n".join(self.coder.get_announcements())
        self.io.tool_output(announcements)

    def cmd_reasoning_effort(self, args):
        "Set the reasoning effort level (values: number or low/medium/high depending on model)"
        model = self.coder.main_model

        if not args.strip():
            reasoning_value = model.get_reasoning_effort()
            if reasoning_value is None:
                self.io.tool_output("Reasoning effort is not currently set.")
            else:
                self.io.tool_output(f"Current reasoning effort: {reasoning_value}")
            return

        value = args.strip()
        model.set_reasoning_effort(value)
        reasoning_value = model.get_reasoning_effort()
        self.io.tool_output(f"Set reasoning effort to {reasoning_value}")
        self.io.tool_output()
        announcements = "\n".join(self.coder.get_announcements())
        self.io.tool_output(announcements)

    def cmd_automode(self, args):
        """Toggle autonomous tool execution mode."""
        if not hasattr(self.coder, "tool_router"):
            self.io.tool_error(
                "Tool mode not available. Use --edit-format tool or /chat-mode tool to enable."
            )
            return

        args = args.strip()
        show_status = True
        i = 0
        parts = args.split()

        while i < len(parts):
            arg = parts[i]

            if arg == "on":
                self.coder.auto_confirm_tools = True
                self.coder.tool_router.auto_confirm = True
                self.io.tool_output("Auto mode enabled - tools will execute without confirmation")
                show_status = False
            elif arg == "off":
                self.coder.auto_confirm_tools = False
                self.coder.tool_router.auto_confirm = False
                self.io.tool_output("Auto mode disabled - will confirm each tool call")
                show_status = False
            elif arg == "--limit" and i + 1 < len(parts):
                try:
                    limit = int(parts[i + 1])
                    self.coder.max_tool_calls = limit
                    self.io.tool_output(f"Max tool calls set to: {limit}")
                    show_status = False
                except ValueError:
                    self.io.tool_error(f"Invalid limit: {parts[i + 1]}")
                i += 1
            elif arg == "--cost" and i + 1 < len(parts):
                try:
                    cost = float(parts[i + 1])
                    self.coder.max_tool_cost = cost
                    self.coder.cost_tracker.max_cost = cost
                    self.io.tool_output(f"Cost limit set to: ${cost:.2f}")
                    show_status = False
                except ValueError:
                    self.io.tool_error(f"Invalid cost: {parts[i + 1]}")
                i += 1
            elif arg == "--safe":
                from aider.tools.risk import RiskLevel

                self.coder.tool_router.risk_confirm_threshold = RiskLevel.NORMAL
                self.io.tool_output("Safe mode: only SAFE tools auto-confirm")
                show_status = False
            else:
                self.io.tool_error(f"Unknown option: {arg}")

            i += 1

        if show_status or True:
            status = "on" if self.coder.auto_confirm_tools else "off"
            self.io.tool_output("\nCurrent settings:")
            self.io.tool_output(f"  Auto mode: {status}")
            self.io.tool_output(f"  Max tool calls: {self.coder.max_tool_calls}")
            self.io.tool_output(f"  Cost limit: ${self.coder.max_tool_cost:.2f}")
            threshold = self.coder.tool_router.risk_confirm_threshold.name
            self.io.tool_output(f"  Risk threshold: {threshold}")

            if hasattr(self.coder, "cost_tracker"):
                remaining = self.coder.cost_tracker.remaining_budget
                self.io.tool_output(f"  Remaining budget: ${remaining:.2f}")

    def cmd_copy_context(self, args=None):
        """Copy the current chat context as markdown, suitable to paste into a web UI"""
        import pyperclip

        chunks = self.coder.format_chat_chunks()
        markdown = ""

        for messages in [chunks.repo, chunks.readonly_files, chunks.chat_files]:
            for msg in messages:
                if msg["role"] != "user":
                    continue

                content = msg["content"]
                if isinstance(content, list):
                    for part in content:
                        if part.get("type") == "text":
                            markdown += part["text"] + "\n\n"
                else:
                    markdown += content + "\n\n"

        args = args or ""
        markdown += f"""
Just tell me how to edit the files to make the changes.
Don't give me back entire files.
Just show me the edits I need to make.

{args}
"""

        try:
            pyperclip.copy(markdown)
            self.io.tool_output("Copied code context to clipboard.")
        except pyperclip.PyperclipException as e:
            self.io.tool_error(f"Failed to copy to clipboard: {str(e)}")
            self.io.tool_output(
                "You may need to install xclip or xsel on Linux, or pbcopy on macOS."
            )
        except Exception as e:
            self.io.tool_error(f"An unexpected error occurred while copying to clipboard: {str(e)}")
