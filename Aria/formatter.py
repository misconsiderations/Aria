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

NAME = "Aria"
VERSION = "v1.0.0"
AUTHOR = "Misconsideration"

def _block(content: str) -> str:
    lines = content.split("\n")
    result = ["> ```ansi"]
    for line in lines:
        result.append(f"> {line}")
    result.append("> ```")
    return "\n".join(result)

def header(subtitle: str) -> str:
    return _block(
        f"{PURPLE}{BOLD}{UNDERLINE}{NAME}{RESET}{DARK} :: {RESET}{WHITE}{VERSION}{DARK} :: {RESET}{BLUE}{subtitle}{RESET}"
    )

def _raw_header(subtitle: str) -> str:
    """Header line without the block wrapper."""
    return f"{PURPLE}{BOLD}{UNDERLINE}{NAME}{RESET}{DARK} :: {RESET}{WHITE}{VERSION}{DARK} :: {RESET}{BLUE}{subtitle}{RESET}"

def _raw_command_list(cmds: list) -> str:
    """Command list lines without the block wrapper."""
    lines = []
    for name, desc in cmds:
        lines.append(f"{CYAN}{name:<13}{DARK}:: {RESET}{WHITE}{desc}{RESET}")
    return "\n".join(lines)

def _raw_footer(text: str) -> str:
    """Footer line without the block wrapper."""
    return f"{DARK}{text}{RESET}"

def category_list(categories: dict) -> str:
    lines = []
    for name, desc in categories.items():
        lines.append(f"{PURPLE}{name:<10}{DARK}:: {RESET}{WHITE}{desc}{RESET}")
    return _block("\n".join(lines))

def footer_main() -> str:
    return _block(f"{DARK}Developed by {WHITE}{AUTHOR}{RESET}")

def footer_page(prefix: str, category: str, page: int, total: int) -> str:
    return _block(f"{DARK}{prefix}help {category.lower()} [1-{total}]{RESET}")

def layout(header_text: str, body_text: str, footer_text: str) -> str:
    return "\n".join([
        _block(_raw_header(header_text)),
        _block(body_text),
        _block(_raw_footer(footer_text)),
    ])

def command_page(title: str, cmds: list, footer_text: str) -> str:
    return layout(title, _raw_command_list(cmds), footer_text)

def command_list(cmds: list) -> str:
    lines = []
    for name, desc in cmds:
        lines.append(f"{CYAN}{name:<13}{DARK}:: {RESET}{WHITE}{desc}{RESET}")
    return _block("\n".join(lines))

def command_usage(name: str, usage: str, description: str, prefix: str) -> str:
    head = _block(
        f"{PURPLE}{BOLD}{UNDERLINE}{NAME}{RESET}{DARK} :: {RESET}{WHITE}{VERSION}{DARK} :: {RESET}{BLUE}{name.upper()}{RESET}"
    )
    body = _block(
        f"{CYAN}{'Command':<13}{DARK}:: {RESET}{WHITE}{name}{RESET}\n"
        f"{CYAN}{'Usage':<13}{DARK}:: {RESET}{WHITE}{prefix}{usage}{RESET}\n"
        f"{CYAN}{'Description':<13}{DARK}:: {RESET}{WHITE}{description}{RESET}"
    )
    return head + body

def success(msg: str) -> str:
    return f"> **{GREEN}✓ {msg}{RESET}**"

def error(msg: str) -> str:
    return f"> **{RED}✗ {msg}{RESET}**"

def warning(msg: str) -> str:
    return f"> **{YELLOW}⚠ {msg}{RESET}**"

def status_box(status: str, details: dict) -> str:
    lines = [f"{PURPLE}{BOLD}{status}{RESET}"]
    for key, value in details.items():
        lines.append(f"{CYAN}{key:<15}{DARK}:: {RESET}{WHITE}{value}{RESET}")
    return _block("\n".join(lines))

def boost_status(status: str, claimed: int, cached: int) -> str:
    return _block(
        f"{CYAN}{'Status':<15}{DARK}:: {RESET}{WHITE}{status}{RESET}\n"
        f"{CYAN}{'Claimed':<15}{DARK}:: {RESET}{WHITE}{claimed}{RESET}\n"
        f"{CYAN}{'Cached':<15}{DARK}:: {RESET}{WHITE}{cached} codes{RESET}"
    )

def nitro_status(status: str, codes_checked: int) -> str:
    return _block(
        f"{CYAN}{'Status':<15}{DARK}:: {RESET}{WHITE}{status}{RESET}\n"
        f"{CYAN}{'Claimed':<15}{DARK}:: {RESET}{WHITE}{codes_checked}{RESET}\n"
        f"{CYAN}{'Cached':<15}{DARK}:: {RESET}{WHITE}{codes_checked} codes{RESET}"
    )

def giveaway_status(status: str, entered: int, won: int, failed: int) -> str:
    return _block(
        f"{CYAN}{'Status':<15}{DARK}:: {RESET}{WHITE}{status}{RESET}\n"
        f"{CYAN}{'Entered':<15}{DARK}:: {RESET}{WHITE}{entered}{RESET}\n"
        f"{CYAN}{'Won':<15}{DARK}:: {RESET}{WHITE}{won}{RESET}\n"
        f"{CYAN}{'Failed':<15}{DARK}:: {RESET}{WHITE}{failed}{RESET}"
    )

def info_block(title: str, content: str) -> str:
    head = _block(f"{PURPLE}{BOLD}{title}{RESET}")
    body = _block(f"{WHITE}{content}{RESET}")
    return head + "\n" + body

def inline_code(text: str) -> str:
    return f"`{text}`"

def formatted_list(items: list, color: str = CYAN) -> str:
    lines = []
    for item in items:
        lines.append(f"{color}• {item}{RESET}")
    return _block("\n".join(lines))
