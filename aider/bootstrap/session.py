"""
Session assembly helpers extracted from aider.main.
"""

import os

from aider.urls import edit_formats


def create_commands(args, io, parser, read_only_fnames, runtime=None):
    """Create the Commands instance for a session."""
    from aider.commands import Commands

    return Commands(
        io,
        None,
        voice_language=args.voice_language,
        voice_input_device=args.voice_input_device,
        voice_format=args.voice_format,
        verify_ssl=args.verify_ssl,
        args=args,
        parser=parser,
        verbose=args.verbose,
        editor=args.editor,
        original_read_only_fnames=read_only_fnames,
        runtime=runtime,
    )


def create_summarizer(args, main_model):
    """Create the chat summarizer for a session."""
    from aider.history import ChatSummary

    return ChatSummary(
        [main_model.weak_model, main_model],
        args.max_chat_history_tokens or main_model.max_chat_history_tokens,
    )


def resolve_map_tokens(args, main_model):
    """Resolve repo-map token budget from args/model defaults."""
    if args.map_tokens is None:
        return main_model.get_repo_map_tokens()
    return args.map_tokens


def finalize_streaming_settings(args, io, main_model):
    """Apply stream/cache settings that depend on model metadata."""
    if args.cache_prompts and args.map_refresh == "auto":
        args.map_refresh = "files"

    if not main_model.streaming:
        if args.stream:
            io.tool_warning(
                f"Warning: Streaming is not supported by {main_model.name}. Disabling streaming."
            )
        args.stream = False


def create_coder(
    args,
    io,
    analytics,
    main_model,
    repo,
    fnames,
    read_only_fnames,
    lint_cmds,
    commands,
    summarizer,
    runtime=None,
    background_semantic_index=True,
):
    """Create the session coder and attach optional agent support."""
    from aider.coders import Coder
    from aider.coders.base_coder import UnknownEditFormat

    map_tokens = resolve_map_tokens(args, main_model)

    analytics.event("auto_commits", enabled=bool(args.auto_commits))

    try:
        coder = Coder.create(
            main_model=main_model,
            edit_format=args.edit_format,
            io=io,
            repo=repo,
            fnames=fnames,
            read_only_fnames=read_only_fnames,
            show_diffs=args.show_diffs,
            auto_commits=args.auto_commits,
            dirty_commits=args.dirty_commits,
            dry_run=args.dry_run,
            map_tokens=map_tokens,
            verbose=args.verbose,
            stream=args.stream,
            use_git=args.git,
            restore_chat_history=args.restore_chat_history,
            auto_lint=args.auto_lint,
            auto_test=args.auto_test,
            lint_cmds=lint_cmds,
            test_cmd=args.test_cmd,
            commands=commands,
            summarizer=summarizer,
            analytics=analytics,
            runtime=runtime,
            map_refresh=args.map_refresh,
            cache_prompts=args.cache_prompts,
            map_mul_no_files=args.map_multiplier_no_files,
            num_cache_warming_pings=args.cache_keepalive_pings,
            suggest_shell_commands=args.suggest_shell_commands,
            chat_language=args.chat_language,
            commit_language=args.commit_language,
            detect_urls=args.detect_urls,
            auto_copy_context=args.copy_paste,
            auto_accept_architect=args.auto_accept_architect,
            add_gitignore_files=args.add_gitignore_files,
            use_semantic_index=args.semantic_index,
            background_semantic_index=background_semantic_index,
            review_mode=args.review,
            auto_review=args.auto_review,
        )

        if getattr(args, "enable_agents", False) or os.environ.get("AIDER_ENABLE_AGENTS"):
            try:
                from aider.agents.integration import initialize_agents

                max_agents = getattr(args, "max_agents", 5)
                initialize_agents(coder, max_concurrent=max_agents)
                io.tool_output(f"Multi-agent support enabled (max concurrent: {max_agents})")
            except Exception as err:
                if args.verbose:
                    io.tool_error(f"Failed to initialize agents: {err}")

        return coder
    except UnknownEditFormat as err:
        io.tool_error(str(err))
        io.offer_url(edit_formats, "Open documentation about edit formats?")
        analytics.event("exit", reason="Unknown edit format")
        return 1
    except ValueError as err:
        io.tool_error(str(err))
        analytics.event("exit", reason="ValueError during coder creation")
        return 1
