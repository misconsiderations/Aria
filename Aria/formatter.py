RESET = "\u001b[0m"
BOLD = "\u001b[1m"
UNDERLINE = "\u001b[4m"

DARK = "\u001b[30m"
WHITE = "\u001b[0;37m"
CYAN = "\u001b[0;36m"
PURPLE = "\u001b[0;35m"
BLUE = "\u001b[0;34m"
GREEN = "\u001b[0;32m"
RED = "\u001b[0;31m"
YELLOW = "\u001b[0;33m"
PINK = "\u001b[1;35m"

NAME = "Aria"
VERSION = "v1.1.0"

def quote_block(text: str) -> str:
    """Wrap text in quote blocks for Discord display."""
    return '\n'.join(f'> {line}' for line in text.split('\n'))

def format_message(title: str, content: str = "", status: str = None) -> str:
    """Format a message with title and optional content."""
    if status == "error":
        symbol = f"{RED}✗{RESET}"
    elif status == "success":
        symbol = f"{GREEN}✓{RESET}"
    elif status == "info":
        symbol = f"{CYAN}ℹ{RESET}"
    else:
        symbol = f"{PURPLE}•{RESET}"
    
    result = f"{symbol} {BOLD}{title}{RESET}"
    if content:
        result += f"\n{content}"
    return result

def _block(content: str) -> str:
    """Wrap content in ANSI code block."""
    return f"```ansi\n{content}```"

def header(subtitle: str) -> str:
    """Create a formatted header line."""
    return f"{PINK}{BOLD}{NAME}{RESET} {DARK}::{RESET} {GREEN}{VERSION}{RESET} {DARK}::{RESET} {CYAN}{subtitle}{RESET}"

def category_list(categories: dict) -> str:
    """Format a clean category listing."""
    lines = []
    for name, desc in categories.items():
        lines.append(f"{PURPLE}{name:<16}{DARK}| {RESET}{WHITE}{desc}{RESET}")
    return "\n".join(lines)

def command_list(cmds: list) -> str:
    """Format a clean command listing."""
    lines = []
    for name, desc in cmds:
        lines.append(f"{CYAN}{name:<20}{DARK}| {RESET}{WHITE}{desc}{RESET}")
    return "\n".join(lines)

def status_bar(label: str, value: str, max_width: int = 40) -> str:
    """Format a status bar item."""
    value_str = str(value)[:max_width]
    return f"{CYAN}{label:<15}{DARK}| {RESET}{WHITE}{value_str}{RESET}"

def success(msg: str) -> str:
    """Format a success message."""
    return f"{GREEN}✓ {msg}{RESET}"

def error(msg: str) -> str:
    """Format an error message."""
    return f"{RED}✗ {msg}{RESET}"

def warning(msg: str) -> str:
    """Format a warning message."""
    return f"{YELLOW}⚠ {msg}{RESET}"

def _compose(*sections) -> str:
    """Compose multiple sections into a single code block."""
    combined = "\n".join(str(s) for s in sections if s)
    return _block(combined)

def status_box(title: str, details: dict) -> str:
    """Format a status/configuration box."""
    lines = [f"{BOLD}{title}{RESET}"]
    for key, value in details.items():
        lines.append(f"{CYAN}{key:<15}{DARK}| {RESET}{WHITE}{str(value)}{RESET}")
    return _block("\n".join(lines))

def command_page(title: str, lines: list, footer: str = "") -> str:
    """Format a command page with title, command list, and optional footer."""
    result_lines = [header(title)]
    for name, desc in lines:
        result_lines.append(f"{CYAN}{name:<20}{DARK}| {RESET}{WHITE}{desc}{RESET}")
    if footer:
        result_lines.append(f"\n{DARK}{footer}{RESET}")
    return _block("\n".join(result_lines))

def footer_page(prefix: str, category: str, page: int, total_pages: int) -> str:
    """Format pagination footer for command pages."""
    return f"Page {page}/{total_pages} • Category: {category} • Use {prefix}help for more"

