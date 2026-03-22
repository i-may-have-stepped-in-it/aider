"""
Minimal main.py entrypoint - delegates to async implementation.

All startup policy has been moved to bootstrap helpers in main_async.py.
"""

import sys

from aider.report import report_uncaught_exceptions


def __getattr__(name):
    if name == "InputOutput":
        from aider.io import InputOutput
        return InputOutput
    if name == "Analytics":
        from aider.analytics import Analytics
        return Analytics
    if name == "check_version":
        from aider.versioncheck import check_version
        return check_version
        
    # Backward compatibility: functions moved to bootstrap.launch
    if name in (
        "check_gitignore",
        "setup_git",
        "load_dotenv_files",
        "sanity_check_repo",
        "check_and_load_imports",
        "is_first_run_of_new_version",
        "create_coder",
        "dispatch_session_mode",
        "get_git_root",
        "parse_args",
    ):
        import aider.bootstrap.launch as launch
        import aider.bootstrap.runtime as runtime
        import aider.bootstrap.session as session
        
        # Map name to module
        if hasattr(launch, name):
            return getattr(launch, name)
        if hasattr(runtime, name):
            return getattr(runtime, name)
        if hasattr(session, name):
            return getattr(session, name)
            
    if name == "importlib_resources":
        import importlib.resources as importlib_resources
        return importlib_resources
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main(argv=None, input=None, output=None, force_git_root=None, return_coder=False):
    """Main entrypoint - delegates to async implementation for docked prompt support."""
    report_uncaught_exceptions()
    
    # Import here to avoid circular imports
    from aider.main_async import run_async_main
    
    # Run the async main which uses the new docked prompt UI
    return run_async_main(
        argv=argv,
        input=input,
        output=output,
        force_git_root=force_git_root,
        return_coder=return_coder,
    )


if __name__ == "__main__":
    status = main()
    sys.exit(status)
