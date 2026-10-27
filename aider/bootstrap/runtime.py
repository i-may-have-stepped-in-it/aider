"""
Runtime dispatch helpers extracted from aider.main.
"""

from pathlib import Path

from aider.coders.coder_factory import create_coder


def _print_welcome(coder, io):
    from aider import __version__, themes, venice

    model = coder.main_model
    extras = {}
    max_input = model.info.get("max_input_tokens")
    if max_input:
        extras["context"] = f"{max_input:,} tokens"
    if venice.is_venice_model(model.name):
        extras["venice"] = f"web search {venice.runtime['web_search']}"
        _, character = venice.split_character(model.name)
        character = character or venice.runtime["character"]
        if character:
            extras["character"] = character

    io.console.print(
        themes.welcome_panel(
            io.theme,
            __version__,
            model.name,
            str(Path.cwd()),
            files=len(coder.abs_fnames),
            extras=extras,
        )
    )


def show_welcome(coder):
    """Print the welcome card (pretty terminals only)."""
    io = coder.io
    if not getattr(io, "pretty", False) or not hasattr(io, "console"):
        return

    try:
        _print_welcome(coder, io)
    except Exception:
        pass  # Never let decoration break startup


def attach_runtime_services(args, coder, analytics, git_root, hooks_manager):
    """Attach file watching, clipboard support, and hooks to the coder."""
    ignores = []
    if git_root:
        ignores.append(str(Path(git_root) / ".gitignore"))
    if args.aiderignore:
        ignores.append(args.aiderignore)

    if args.watch_files:
        from aider.watch import FileWatcher

        file_watcher = FileWatcher(
            coder,
            gitignores=ignores,
            verbose=args.verbose,
            analytics=analytics,
            root=str(Path.cwd()) if args.subtree_only else None,
        )
        coder.file_watcher = file_watcher

    if args.copy_paste:
        from aider.copypaste import ClipboardWatcher

        analytics.event("copy-paste mode")
        ClipboardWatcher(coder.io, verbose=args.verbose)

    show_welcome(coder)
    coder.show_announcements()

    if hooks_manager:
        coder.hooks_manager = hooks_manager
        # Register UI observer for real-time dashboard and status line
        hooks_manager.register_ui_observer(coder.io)

    # Set initial UI mode based on arguments
    if hasattr(args, "auto") and args.auto:
        coder.io.set_mode("AUTO")
    elif hasattr(args, "architect") and args.architect:
        coder.io.set_mode("ARCHITECT")
    elif hasattr(args, "ask") and args.ask:
        coder.io.set_mode("ASK")
    else:
        coder.io.set_mode("CHAT")


def handle_pre_run_actions(
    args,
    io,
    coder,
    commands,
    analytics,
    main_model,
    git_root,
    is_first_run,
    urls_module,
    webbrowser_module,
    utils_module,
    fnames,
):
    """
    Handle one-shot actions before entering message or interactive execution.

    Returns:
        (handled, result)
    """
    if args.show_prompts:
        coder.cur_messages += [dict(role="user", content="Hello!")]
        messages = coder.format_messages().all_messages()
        utils_module.show_messages(messages)
        analytics.event("exit", reason="Showed prompts")
        return True, None

    if args.lint:
        coder.commands.cmd_lint(fnames=fnames)

    if args.test:
        if not args.test_cmd:
            io.tool_error("No --test-cmd provided.")
            analytics.event("exit", reason="No test command provided")
            return True, 1
        coder.commands.cmd_test(args.test_cmd)
        if io.placeholder:
            coder.run(io.placeholder)

    if args.commit:
        if args.dry_run:
            io.tool_output("Dry run enabled, skipping commit.")
        else:
            coder.commands.cmd_commit()

    if args.lint or args.test or args.commit:
        analytics.event("exit", reason="Completed lint/test/commit")
        return True, None

    if args.show_repo_map:
        repo_map = coder.get_repo_map()
        if repo_map:
            io.tool_output(repo_map)
        analytics.event("exit", reason="Showed repo map")
        return True, None

    if args.apply:
        content = io.read_text(args.apply)
        if content is None:
            analytics.event("exit", reason="Failed to read apply content")
            return True, None
        coder.partial_response_content = content
        coder.apply_updates()
        analytics.event("exit", reason="Applied updates")
        return True, None

    if args.apply_clipboard_edits:
        args.edit_format = main_model.editor_edit_format
        args.message = "/paste"

    if args.show_release_notes is True:
        io.tool_output(f"Opening release notes: {urls_module.release_notes}")
        io.tool_output()
        webbrowser_module.open(urls_module.release_notes)
    elif args.show_release_notes is None and is_first_run:
        io.tool_output()
        io.offer_url(
            urls_module.release_notes,
            "Would you like to see what's new in this version?",
            allow_never=False,
        )

    if git_root and Path.cwd().resolve() != Path(git_root).resolve():
        io.tool_warning(
            "Note: in-chat filenames are always relative to the git working dir, not the current"
            " working dir."
        )
        io.tool_output(f"Cur working dir: {Path.cwd()}")
        io.tool_output(f"Git working dir: {git_root}")

    if args.stream and args.cache_prompts:
        io.tool_warning("Cost estimates may be inaccurate when using streaming and caching.")

    if args.load:
        commands.cmd_load(args.load)

    return False, None


def dispatch_session_mode(args, io, coder, analytics):
    """Handle MCP, ACP, message, and exit modes."""
    from aider.commands import SwitchCoder

    if args.mcp:
        from aider.mcp.server import AiderMCPServer

        server = AiderMCPServer(coder)
        try:
            server.start()
        except KeyboardInterrupt:
            pass
        return True, None

    if args.acp:
        from aider.editor_protocol.agent import ACP_AVAILABLE, run_acp_mode
        from aider.async_utils import run_async_safely

        if not ACP_AVAILABLE:
            io.tool_error("ACP mode requires 'agent-client-protocol' package.")
            io.tool_output("Install with: pip install agent-client-protocol")
            return True, 1

        io.tool_output("Starting Aider in ACP mode (Agent Client Protocol)...")
        try:
            run_async_safely(run_acp_mode(coder))
        except KeyboardInterrupt:
            pass
        return True, None

    if args.message:
        io.add_to_input_history(args.message)
        io.tool_output()
        try:
            coder.run(with_message=args.message)
        except SwitchCoder:
            pass
        analytics.event("exit", reason="Completed --message")
        return True, None

    if args.message_file:
        try:
            message_from_file = io.read_text(args.message_file)
            io.tool_output()
            coder.run(with_message=message_from_file)
        except FileNotFoundError:
            io.tool_error(f"Message file not found: {args.message_file}")
            analytics.event("exit", reason="Message file not found")
            return True, 1
        except IOError as err:
            io.tool_error(f"Error reading message file: {err}")
            analytics.event("exit", reason="Message file IO error")
            return True, 1

        analytics.event("exit", reason="Completed --message-file")
        return True, None

    if args.exit:
        analytics.event("exit", reason="Exit flag set")
        return True, None

    return False, None


def run_interactive_session(args, io, coder, analytics, hooks_manager):
    """Run the main interactive coder loop including mode switches."""
    from aider.commands import SwitchCoder
    analytics.event(
        "cli session",
        main_model=coder.main_model,
        edit_format=coder.main_model.edit_format,
    )

    while True:
        try:
            coder.ok_to_warm_cache = bool(args.cache_keepalive_pings)
            coder.run()

            if hooks_manager:
                try:
                    hooks_manager.execute("on_exit", coder=coder)
                except Exception as err:
                    if hooks_manager.verbose:
                        io.tool_error(f"Hook error (on_exit): {err}")

            analytics.event("exit", reason="Completed main CLI coder.run")
            return None
        except SwitchCoder as switch:
            coder.ok_to_warm_cache = False

            if hooks_manager:
                coder.hooks_manager = hooks_manager

            if hasattr(switch, "placeholder") and switch.placeholder is not None:
                io.placeholder = switch.placeholder

            kwargs = dict(io=io, from_coder=coder)
            kwargs.update(switch.kwargs)
            if "show_announcements" in kwargs:
                del kwargs["show_announcements"]

            coder = create_coder(**kwargs)

            if switch.kwargs.get("show_announcements") is not False:
                coder.show_announcements()


async def run_interactive_session_async(args, io, coder, analytics, hooks_manager):
    """
    Async version of run_interactive_session.
    
    Enables non-blocking prompt input during generation (Option B).
    """
    from aider.commands import SwitchCoder
    analytics.event(
        "cli session",
        main_model=coder.main_model,
        edit_format=coder.main_model.edit_format,
    )

    while True:
        try:
            coder.ok_to_warm_cache = bool(args.cache_keepalive_pings)
            await coder.run_async()

            if hooks_manager:
                try:
                    await hooks_manager.execute_async("on_exit", coder=coder)
                except Exception as err:
                    if hooks_manager.verbose:
                        io.tool_error(f"Hook error (on_exit): {err}")

            analytics.event("exit", reason="Completed main CLI coder.run_async")
            return None
        except SwitchCoder as switch:
            coder.ok_to_warm_cache = False

            if hooks_manager:
                coder.hooks_manager = hooks_manager

            if hasattr(switch, "placeholder") and switch.placeholder is not None:
                io.placeholder = switch.placeholder

            kwargs = dict(io=io, from_coder=coder)
            kwargs.update(switch.kwargs)
            if "show_announcements" in kwargs:
                del kwargs["show_announcements"]

            coder = create_coder(**kwargs)

            if switch.kwargs.get("show_announcements") is not False:
                coder.show_announcements()
