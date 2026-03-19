"""
Git root helpers for startup.
"""

try:
    import git
except ImportError:
    git = None


def handle_git_root_recursion(args, force_git_root=None):
    """
    Return the current git root hint for startup.

    The old recursive reparsing flow was extracted incorrectly and introduced
    undefined-state bugs. Keep this helper narrow and correct until the full
    repo/bootstrap selection flow is reworked behind explicit bootstrap stages.
    """
    if git is None:
        return None

    if force_git_root:
        return force_git_root

    if not getattr(args, "git", True):
        return None

    try:
        repo = git.Repo(search_parent_directories=True)
        return repo.working_tree_dir
    except (git.InvalidGitRepositoryError, FileNotFoundError):
        return None
