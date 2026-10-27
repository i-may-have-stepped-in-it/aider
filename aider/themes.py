"""
Color themes for the terminal UI.

A theme sets the chat colors (the same knobs as --user-input-color etc.), the
markdown code theme, and the accent colors used by the welcome card, rules and
status bar. Colors are mid-tones chosen to stay readable on both dark and light
terminal backgrounds.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Theme:
    name: str
    user_input_color: str
    assistant_output_color: str
    tool_output_color: str
    tool_warning_color: str
    tool_error_color: str
    code_theme: str
    # Gradient stops for the welcome banner, left to right
    gradient: tuple = ()
    accent: str = "#00cc00"
    muted: str = "#808080"
    completion_menu: dict = field(default_factory=dict)


THEMES = {
    # Soft violet -> cyan, inspired by Kimi Code's look
    "aurora": Theme(
        name="aurora",
        user_input_color="#38BDF8",
        assistant_output_color="#A78BFA",
        tool_output_color="#94A3B8",
        tool_warning_color="#F59E0B",
        tool_error_color="#F43F5E",
        code_theme="one-dark",
        gradient=("#818CF8", "#A78BFA", "#C084FC", "#22D3EE"),
        accent="#A78BFA",
        muted="#64748B",
        completion_menu=dict(
            completion_menu_bg_color="#1E1B4B",
            completion_menu_color="#E0E7FF",
            completion_menu_current_bg_color="#7C3AED",
            completion_menu_current_color="#FFFFFF",
        ),
    ),
    # Quiet and low-chrome, inspired by Codex CLI
    "codex": Theme(
        name="codex",
        user_input_color="#10A37F",
        assistant_output_color="default",
        tool_output_color="#8E8EA0",
        tool_warning_color="#D97706",
        tool_error_color="#EF4444",
        code_theme="github-dark",
        gradient=("#10A37F", "#10A37F"),
        accent="#10A37F",
        muted="#8E8EA0",
    ),
    # Google blue -> purple -> rose
    "gemini": Theme(
        name="gemini",
        user_input_color="#4285F4",
        assistant_output_color="#8AB4F8",
        tool_output_color="#9AA0A6",
        tool_warning_color="#FBBC04",
        tool_error_color="#EA4335",
        code_theme="monokai",
        gradient=("#4285F4", "#9B72CB", "#D96570"),
        accent="#4285F4",
        muted="#9AA0A6",
    ),
    # The original aider colors
    "classic": Theme(
        name="classic",
        user_input_color="#00cc00",
        assistant_output_color="#0088ff",
        tool_output_color=None,
        tool_warning_color="#FFA500",
        tool_error_color="#FF2222",
        code_theme="default",
        gradient=("#00cc00", "#0088ff"),
        accent="#00cc00",
        muted="#808080",
    ),
}

DEFAULT_THEME = "aurora"

_COLOR_ARGS = (
    "user_input_color",
    "assistant_output_color",
    "tool_output_color",
    "tool_warning_color",
    "tool_error_color",
    "code_theme",
)


def get(name):
    return THEMES.get(name or DEFAULT_THEME, THEMES["classic"])


def apply_to_args(args, parser=None):
    """
    Fill color args from the selected theme.

    Only args still at their parser default are changed, so explicit
    --user-input-color etc. (from CLI, env or config file) always win.
    """
    theme = get(getattr(args, "theme", None))
    defaults = {}
    if parser is not None:
        defaults = {name: parser.get_default(name) for name in _COLOR_ARGS}
    else:
        classic = THEMES["classic"]
        defaults = {name: getattr(classic, name) for name in _COLOR_ARGS}

    for name in _COLOR_ARGS:
        if getattr(args, name, None) == defaults.get(name):
            setattr(args, name, getattr(theme, name))

    for name, value in theme.completion_menu.items():
        if getattr(args, name, None) is None:
            setattr(args, name, value)
    return theme


# --------------------------------------------------------------------------- #
# Rendering helpers
# --------------------------------------------------------------------------- #


def _hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))


def _lerp(stops, t):
    if len(stops) == 1:
        return stops[0]
    pos = t * (len(stops) - 1)
    i = min(int(pos), len(stops) - 2)
    frac = pos - i
    a, b = _hex_to_rgb(stops[i]), _hex_to_rgb(stops[i + 1])
    r, g, bl = (round(x + (y - x) * frac) for x, y in zip(a, b))
    return f"#{r:02x}{g:02x}{bl:02x}"


def gradient_text(text, stops, bold=True):
    """Return a rich Text with a horizontal color gradient."""
    from rich.text import Text

    out = Text()
    visible = [c for c in text if not c.isspace()]
    n = max(len(visible) - 1, 1)
    k = 0
    for ch in text:
        if ch.isspace():
            out.append(ch)
            continue
        style = _lerp(stops, k / n)
        out.append(ch, style=f"bold {style}" if bold else style)
        k += 1
    return out


def context_meter(used, total, width=10):
    """A compact text bar like ▰▰▰▱▱▱▱▱▱▱ 31%."""
    if not total:
        return ""
    frac = max(0.0, min(1.0, used / total))
    filled = round(frac * width)
    return "▰" * filled + "▱" * (width - filled) + f" {frac:.0%}"


def welcome_panel(theme, version, model_name, cwd, files=0, extras=None):
    """A Codex-style welcome card: who/where/what, plus the handful of commands people need."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    title = gradient_text(f" aider v{version} ", theme.gradient or (theme.accent,))

    info = Table.grid(padding=(0, 2))
    info.add_column(style=theme.muted, no_wrap=True)
    info.add_column(overflow="fold")
    info.add_row("model", Text(model_name, style=f"bold {theme.accent}"))
    info.add_row("directory", cwd)
    if files:
        info.add_row("files", f"{files} in chat")
    for key, value in (extras or {}).items():
        info.add_row(key, value)

    tips = Text()
    for i, (cmd, desc) in enumerate(
        (
            ("/add", "add files"),
            ("/model", "switch model"),
            ("/venice", "Venice models & agents"),
            ("/help", "all commands"),
        )
    ):
        if i:
            tips.append("   ")
        tips.append(cmd, style=f"bold {theme.accent}")
        tips.append(f" {desc}", style=theme.muted)

    body = Table.grid()
    body.add_row(info)
    body.add_row("")
    body.add_row(tips)
    body.add_row(Text("Describe a change in plain words to get started.", style=theme.muted))

    return Panel(
        body,
        title=title,
        title_align="left",
        border_style=theme.muted,
        padding=(1, 2),
        expand=False,
    )
