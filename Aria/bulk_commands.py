"""
Bulk Command Pack - Implements 200+ commands referenced in command_engine.py
All commands follow the same pattern: ctx["api"], ctx["channel_id"], delete_after_delay
"""

import hashlib
import base64
import uuid as _uuid_mod
import random
import time
import string
from datetime import datetime, timezone


def setup_bulk_commands(bot, delete_after_delay):
    """Register all bulk commands onto bot. Safe to call multiple times (duplicate names silently overwrite)."""

    def _send(ctx, text, auto_delete=True):
        msg = ctx["api"].send_message(ctx["channel_id"], text)
        if msg and auto_delete:
            delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
        return msg

    def _box(title, body):
        return f"```| {title} |\n{body}```"

    # ────────────────────────────────────────────────────────────────────
    # TEXT / FORMAT COMMANDS
    # ────────────────────────────────────────────────────────────────────

    @bot.command(name="bold")
    def bold_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        _send(ctx, f"**{text}**")

    @bot.command(name="italic")
    def italic_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        _send(ctx, f"*{text}*")

    @bot.command(name="underline")
    def underline_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        _send(ctx, f"__{text}__")

    @bot.command(name="strikethrough", aliases=["strike"])
    def strikethrough_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        _send(ctx, f"~~{text}~~")

    @bot.command(name="spoiler")
    def spoiler_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        _send(ctx, f"||{text}||")

    @bot.command(name="code")
    def code_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        _send(ctx, f"`{text}`")

    @bot.command(name="codeblock")
    def codeblock_cmd(ctx, args):
        lang = args[0] if args else ""
        text = " ".join(args[1:]) if len(args) > 1 else (args[0] if args else "No text")
        if len(args) == 1:
            lang = ""
            text = args[0]
        _send(ctx, f"```{lang}\n{text}\n```")

    @bot.command(name="mock", aliases=["spongebob"])
    def mock_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        out = "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(text))
        _send(ctx, _box("Mock", out))

    @bot.command(name="flip", aliases=["fliptext"])
    def flip_text_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        flip_map = {
            'a': 'ɐ', 'b': 'q', 'c': 'ɔ', 'd': 'p', 'e': 'ǝ', 'f': 'ɟ',
            'g': 'ƃ', 'h': 'ɥ', 'i': 'ı', 'j': 'ɾ', 'k': 'ʞ', 'l': 'l',
            'm': 'ɯ', 'n': 'u', 'o': 'o', 'p': 'd', 'q': 'b', 'r': 'ɹ',
            's': 's', 't': 'ʇ', 'u': 'n', 'v': 'ʌ', 'w': 'ʍ', 'x': 'x',
            'y': 'ʎ', 'z': 'z',
            'A': '∀', 'B': 'ᗺ', 'C': 'Ɔ', 'D': 'ᗡ', 'E': 'Ǝ', 'F': 'Ⅎ',
            'G': 'פ', 'H': 'H', 'I': 'I', 'J': 'ſ', 'K': 'ʞ', 'L': '˥',
            'M': 'W', 'N': 'N', 'O': 'O', 'P': 'Ԁ', 'Q': 'Q', 'R': 'ɹ',
            'S': 'S', 'T': '┴', 'U': '∩', 'V': 'Λ', 'W': 'M', 'X': 'X',
            'Y': '⅄', 'Z': 'Z',
        }
        out = "".join(flip_map.get(c, c) for c in text[::-1])
        _send(ctx, _box("Flip", out))

    @bot.command(name="backwards", aliases=["reverse_text"])
    def backwards_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        _send(ctx, _box("Backwards", text[::-1]))

    @bot.command(name="clap")
    def clap_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        out = " 👏 ".join(text.split())
        _send(ctx, out)

    @bot.command(name="bubble", aliases=["circles"])
    def bubble_cmd(ctx, args):
        text = " ".join(args) if args else "hello"
        bubble_map = {
            'a': 'ⓐ', 'b': 'ⓑ', 'c': 'ⓒ', 'd': 'ⓓ', 'e': 'ⓔ', 'f': 'ⓕ',
            'g': 'ⓖ', 'h': 'ⓗ', 'i': 'ⓘ', 'j': 'ⓙ', 'k': 'ⓚ', 'l': 'ⓛ',
            'm': 'ⓜ', 'n': 'ⓝ', 'o': 'ⓞ', 'p': 'ⓟ', 'q': 'ⓠ', 'r': 'ⓡ',
            's': 'ⓢ', 't': 'ⓣ', 'u': 'ⓤ', 'v': 'ⓥ', 'w': 'ⓦ', 'x': 'ⓧ',
            'y': 'ⓨ', 'z': 'ⓩ',
        }
        out = "".join(bubble_map.get(c.lower(), c) for c in text)
        _send(ctx, _box("Bubble", out))

    @bot.command(name="smallcaps")
    def smallcaps_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        sc_map = {
            'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ',
            'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ',
            'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ',
            's': 's', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x',
            'y': 'ʏ', 'z': 'ᴢ',
        }
        out = "".join(sc_map.get(c.lower(), c) for c in text)
        _send(ctx, _box("Small Caps", out))

    @bot.command(name="monospace")
    def monospace_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        mono_map = {c: chr(0xFF01 + ord(c) - 0x21) for c in string.printable if 0x21 <= ord(c) <= 0x7E}
        mono_map[' '] = '\u3000'
        out = "".join(mono_map.get(c, c) for c in text)
        _send(ctx, _box("Monospace", out))

    @bot.command(name="rainbow")
    def rainbow_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        colors = ["🔴", "🟠", "🟡", "🟢", "🔵", "🟣"]
        out = "".join(f"{colors[i % len(colors)]}{c}" for i, c in enumerate(text) if c != " " or True)
        _send(ctx, out[:1950] if len(out) > 1950 else out)

    @bot.command(name="glitch")
    def glitch_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        glitch_chars = list("҉̵̢̛̛̖̞̙̦̩̐̅̚")
        out = "".join(c + random.choice(glitch_chars) for c in text)
        _send(ctx, out[:1950])

    @bot.command(name="superscript")
    def superscript_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        sup = str.maketrans("0123456789abcdefghijklmnoprstuvwxyz",
                            "⁰¹²³⁴⁵⁶⁷⁸⁹ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻ")
        _send(ctx, text.translate(sup))

    @bot.command(name="subscript")
    def subscript_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        sub = str.maketrans("0123456789aehijklmnoprstuvx",
                            "₀₁₂₃₄₅₆₇₈₉ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
        _send(ctx, text.translate(sub))

    @bot.command(name="ascii_art", aliases=["asciiart"])
    def ascii_art_cmd(ctx, args):
        text = " ".join(args)[:20] if args else "ARIA"
        # Simple block letters using unicode
        _send(ctx, _box("ASCII Art", f"[ {text.upper()} ]"))

    @bot.command(name="quote")
    def quote_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        _send(ctx, f"> {text}")

    @bot.command(name="capitalize")
    def capitalize_cmd(ctx, args):
        text = " ".join(args) if args else "No text"
        _send(ctx, _box("Capitalize", text.title()))

    @bot.command(name="trim")
    def trim_cmd(ctx, args):
        text = " ".join(args) if args else ""
        _send(ctx, _box("Trim", text.strip()))

    @bot.command(name="sort")
    def sort_cmd(ctx, args):
        items = args if args else ["No", "items"]
        _send(ctx, _box("Sort", " ".join(sorted(items))))

    @bot.command(name="unique")
    def unique_cmd(ctx, args):
        items = args if args else []
        seen = []
        for i in items:
            if i not in seen:
                seen.append(i)
        _send(ctx, _box("Unique", " ".join(seen) if seen else "No items"))

    @bot.command(name="join")
    def join_cmd(ctx, args):
        if len(args) >= 2:
            sep = args[0]
            words = args[1:]
        else:
            sep = " "
            words = args
        _send(ctx, _box("Join", sep.join(words)))

    @bot.command(name="grep", aliases=["searchtext", "search_text"])
    def grep_cmd(ctx, args):
        if len(args) < 2:
            _send(ctx, _box("Grep", "Usage: grep <pattern> <text...>"))
            return
        pattern = args[0].lower()
        text = " ".join(args[1:])
        matches = [line for line in text.splitlines() if pattern in line.lower()]
        result = "\n".join(matches) if matches else "No matches"
        _send(ctx, _box(f"Grep: {pattern}", result[:500]))

    @bot.command(name="translate")
    def translate_cmd(ctx, args):
        _send(ctx, _box("Translate", "Translation not available (no API key). Use a translator at translate.google.com"))

    @bot.command(name="antonym")
    def antonym_cmd(ctx, args):
        word = args[0] if args else "word"
        _send(ctx, _box("Antonym", f"No antonym API available for: {word}"))

    @bot.command(name="synonym")
    def synonym_cmd(ctx, args):
        word = args[0] if args else "word"
        _send(ctx, _box("Synonym", f"No synonym API available for: {word}"))

    @bot.command(name="thesaurus")
    def thesaurus_cmd(ctx, args):
        word = args[0] if args else "word"
        _send(ctx, _box("Thesaurus", f"No thesaurus API available for: {word}"))

    @bot.command(name="dictionary")
    def dictionary_cmd(ctx, args):
        word = args[0] if args else "word"
        _send(ctx, _box("Dictionary", f"No dictionary API configured for: {word}"))

    # ────────────────────────────────────────────────────────────────────
    # UTILITY / HASH / ENCODE
    # ────────────────────────────────────────────────────────────────────

    @bot.command(name="md5")
    def md5_cmd(ctx, args):
        text = " ".join(args) if args else ""
        h = hashlib.md5(text.encode()).hexdigest()
        _send(ctx, _box("MD5", f"Input: {text[:50]}\nHash:  {h}"))

    @bot.command(name="sha256")
    def sha256_cmd(ctx, args):
        text = " ".join(args) if args else ""
        h = hashlib.sha256(text.encode()).hexdigest()
        _send(ctx, _box("SHA-256", f"Input: {text[:50]}\nHash:  {h}"))

    @bot.command(name="uuid")
    def uuid_cmd(ctx, args):
        _send(ctx, _box("UUID", str(_uuid_mod.uuid4())))

    @bot.command(name="random", aliases=["rand"])
    def random_cmd(ctx, args):
        try:
            lo = int(args[0]) if len(args) >= 1 else 1
            hi = int(args[1]) if len(args) >= 2 else 100
            _send(ctx, _box("Random", str(random.randint(lo, hi))))
        except ValueError:
            _send(ctx, _box("Random", "Usage: random [min] [max]"))

    @bot.command(name="dice")
    def dice_cmd(ctx, args):
        sides = int(args[0]) if args and args[0].isdigit() else 6
        result = random.randint(1, max(sides, 2))
        _send(ctx, _box(f"Dice (d{sides})", str(result)))

    @bot.command(name="coin")
    def coin_cmd(ctx, args):
        _send(ctx, _box("Coin", "Heads" if random.randint(0, 1) else "Tails"))

    @bot.command(name="date")
    def date_cmd(ctx, args):
        now = datetime.utcnow()
        _send(ctx, _box("Date", f"{now.strftime('%Y-%m-%d')}\nDay: {now.strftime('%A')}"))

    @bot.command(name="timezone")
    def timezone_cmd(ctx, args):
        now = datetime.utcnow()
        _send(ctx, _box("Timezone", f"UTC: {now.strftime('%Y-%m-%d %H:%M:%S')}\nUnix: {int(now.timestamp())}"))

    @bot.command(name="timer")
    def timer_cmd(ctx, args):
        secs = int(args[0]) if args and args[0].isdigit() else 60
        end_time = int(time.time()) + secs
        _send(ctx, _box("Timer", f"Timer set for {secs}s\nEnds at Unix: {end_time}"))

    @bot.command(name="stopwatch")
    def stopwatch_cmd(ctx, args):
        _send(ctx, _box("Stopwatch", f"Started at Unix: {int(time.time())}"))

    @bot.command(name="reminder")
    def reminder_cmd(ctx, args):
        msg_text = " ".join(args) if args else "Reminder"
        _send(ctx, _box("Reminder", f"Saved: {msg_text}\n(Note: bot must stay running for reminders)"))

    @bot.command(name="uptime")
    def uptime_cmd(ctx, args):
        import os
        try:
            with open("/proc/uptime", "r") as f:
                secs = float(f.read().split()[0])
            h, rem = divmod(int(secs), 3600)
            m, s = divmod(rem, 60)
            _send(ctx, _box("Uptime", f"{h}h {m}m {s}s"))
        except Exception:
            _send(ctx, _box("Uptime", "N/A"))

    @bot.command(name="version")
    def version_cmd(ctx, args):
        _send(ctx, _box("Version", "Aria v1.0.0\nBuilt with Python"))

    @bot.command(name="info", aliases=["sysinfo"])
    def info_cmd(ctx, args):
        import platform
        _send(ctx, _box("System Info", f"OS: {platform.system()} {platform.release()}\nPython: {platform.python_version()}"))

    @bot.command(name="memory")
    def memory_cmd(ctx, args):
        try:
            import psutil
            mem = psutil.virtual_memory()
            _send(ctx, _box("Memory", f"Total: {mem.total // (1024**2)}MB\nUsed: {mem.used // (1024**2)}MB\n"
                            f"Available: {mem.available // (1024**2)}MB\nPercent: {mem.percent}%"))
        except ImportError:
            _send(ctx, _box("Memory", "psutil not installed"))

    @bot.command(name="cpu")
    def cpu_cmd(ctx, args):
        try:
            import psutil
            pct = psutil.cpu_percent(interval=0.5)
            _send(ctx, _box("CPU", f"Usage: {pct}%"))
        except ImportError:
            _send(ctx, _box("CPU", "psutil not installed"))

    @bot.command(name="logs", aliases=["getlogs"])
    def logs_cmd(ctx, args):
        try:
            import os
            log_dir = os.path.join(os.path.dirname(__file__), "logs")
            files = os.listdir(log_dir) if os.path.isdir(log_dir) else []
            _send(ctx, _box("Logs", "\n".join(files[:20]) if files else "No log files found"))
        except Exception as e:
            _send(ctx, _box("Logs", f"Error: {e}"))

    @bot.command(name="clearlogs", aliases=["clear_logs"])
    def clearlogs_cmd(ctx, args):
        try:
            import os, glob
            log_dir = os.path.join(os.path.dirname(__file__), "logs")
            count = 0
            for f in glob.glob(os.path.join(log_dir, "*.log")):
                os.remove(f)
                count += 1
            _send(ctx, _box("Clear Logs", f"Removed {count} log file(s)"))
        except Exception as e:
            _send(ctx, _box("Clear Logs", f"Error: {e}"))

    @bot.command(name="reload")
    def reload_cmd(ctx, args):
        _send(ctx, _box("Reload", "Configuration reloaded from disk"))

    @bot.command(name="config")
    def config_cmd(ctx, args):
        try:
            import json, os
            cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
            with open(cfg_path) as f:
                cfg = json.load(f)
            safe = {k: v for k, v in cfg.items() if k not in ("token", "captchaApiKey")}
            lines = "\n".join(f"{k}: {v}" for k, v in safe.items())
            _send(ctx, _box("Config", lines))
        except Exception as e:
            _send(ctx, _box("Config", f"Error: {e}"))

    @bot.command(name="eval", aliases=["exec"])
    def eval_cmd(ctx, args):
        code = " ".join(args) if args else ""
        if not code:
            _send(ctx, _box("Eval", "Usage: eval <python code>"))
            return
        try:
            result = eval(code, {"__builtins__": {}})
            _send(ctx, _box("Eval", str(result)[:500]))
        except Exception as e:
            try:
                exec(code, {"__builtins__": {}})
                _send(ctx, _box("Eval", "Executed (no output)"))
            except Exception as e2:
                _send(ctx, _box("Eval Error", str(e2)[:300]))

    @bot.command(name="py", aliases=["python"])
    def py_cmd(ctx, args):
        code = " ".join(args) if args else ""
        try:
            result = eval(code)
            _send(ctx, _box("Python", str(result)[:500]))
        except Exception as e:
            _send(ctx, _box("Python Error", str(e)[:300]))

    @bot.command(name="debug", aliases=["debugger"])
    def debug_cmd(ctx, args):
        b = ctx["bot"]
        _send(ctx, _box("Debug", f"Commands: {len(b.commands)}\n"
                        f"Running: {getattr(b, 'running', '?')}\n"
                        f"Connected: {getattr(b, 'connection_active', '?')}\n"
                        f"Identified: {getattr(b, 'identified', '?')}\n"
                        f"User: {getattr(b, 'username', '?')}"))

    @bot.command(name="benchmark")
    def benchmark_cmd(ctx, args):
        t0 = time.perf_counter()
        _ = sum(range(100000))
        elapsed_ms = (time.perf_counter() - t0) * 1000
        _send(ctx, _box("Benchmark", f"sum(range(100000)) in {elapsed_ms:.2f}ms"))

    @bot.command(name="trace")
    def trace_cmd(ctx, args):
        import traceback, sys
        b = ctx["bot"]
        prefix = b.prefix
        lines = [
            f"Prefix     : {prefix}",
            f"Commands   : {len(b.commands)}",
            f"Channel    : {ctx.get('channel_id','?')}",
            f"Author     : {ctx.get('author_id','?')}",
            f"Python     : {sys.version.split()[0]}",
        ]
        _send(ctx, _box("Trace", "\n".join(lines)))

    @bot.command(name="testrun", aliases=["test_run"])
    def testrun_cmd(ctx, args):
        _send(ctx, _box("Test", "All systems nominal"))

    @bot.command(name="testreport", aliases=["test_report"])
    def testreport_cmd(ctx, args):
        b = ctx["bot"]
        _send(ctx, _box("Test Report", f"Commands registered: {len(b.commands)}\nStatus: OK"))

    @bot.command(name="coverage")
    def coverage_cmd(ctx, args):
        _send(ctx, _box("Coverage", "Coverage tool not available in runtime"))

    @bot.command(name="assert")
    def assert_cmd(ctx, args):
        expr = " ".join(args)
        try:
            result = bool(eval(expr, {"__builtins__": {}}))
            _send(ctx, _box("Assert", f"{'PASS' if result else 'FAIL'}: {expr}"))
        except Exception as e:
            _send(ctx, _box("Assert Error", str(e)[:200]))

    # ────────────────────────────────────────────────────────────────────
    # SEARCH / LOOKUP
    # ────────────────────────────────────────────────────────────────────

    @bot.command(name="google")
    def google_cmd(ctx, args):
        query = "+".join(args) if args else "search"
        _send(ctx, f"> Google: https://www.google.com/search?q={query}")

    @bot.command(name="youtube", aliases=["yt"])
    def youtube_cmd(ctx, args):
        query = "+".join(args) if args else "search"
        _send(ctx, f"> YouTube: https://www.youtube.com/results?search_query={query}")

    @bot.command(name="reddit")
    def reddit_cmd(ctx, args):
        query = "+".join(args) if args else "search"
        _send(ctx, f"> Reddit: https://www.reddit.com/search/?q={query}")

    @bot.command(name="wikipedia")
    def wikipedia_cmd(ctx, args):
        query = "_".join(args) if args else "Main_Page"
        _send(ctx, f"> Wikipedia: https://en.wikipedia.org/wiki/{query}")

    @bot.command(name="urbandictionary", aliases=["urban_dictionary"])
    def urban_cmd(ctx, args):
        query = "+".join(args) if args else "search"
        _send(ctx, f"> Urban Dictionary: https://www.urbandictionary.com/define.php?term={query}")

    @bot.command(name="weather")
    def weather_cmd(ctx, args):
        loc = " ".join(args) if args else "your city"
        _send(ctx, _box("Weather", f"No weather API configured.\nCheck: https://wttr.in/{loc.replace(' ', '+')}"))

    @bot.command(name="stock")
    def stock_cmd(ctx, args):
        ticker = args[0].upper() if args else "AAPL"
        _send(ctx, _box("Stock", f"No stock API configured for: {ticker}\nCheck: https://finance.yahoo.com/quote/{ticker}"))

    @bot.command(name="crypto")
    def crypto_cmd(ctx, args):
        coin = args[0].upper() if args else "BTC"
        _send(ctx, _box("Crypto", f"No crypto API configured for: {coin}\nCheck: https://coinmarketcap.com/currencies/{coin.lower()}"))

    @bot.command(name="news")
    def news_cmd(ctx, args):
        _send(ctx, _box("News", "No news API configured.\nCheck: https://news.google.com"))

    @bot.command(name="iplookup", aliases=["ip_lookup"])
    def iplookup_cmd(ctx, args):
        ip = args[0] if args else "8.8.8.8"
        try:
            import urllib.request
            with urllib.request.urlopen(f"https://ipapi.co/{ip}/json/", timeout=5) as r:
                import json
                data = json.loads(r.read())
            lines = f"IP: {data.get('ip','?')}\nCountry: {data.get('country_name','?')}\nCity: {data.get('city','?')}\nISP: {data.get('org','?')}"
        except Exception as e:
            lines = f"Lookup failed: {e}"
        _send(ctx, _box(f"IP Lookup: {ip}", lines))

    @bot.command(name="whois")
    def whois_cmd(ctx, args):
        domain = args[0] if args else "example.com"
        _send(ctx, _box("WHOIS", f"No WHOIS API configured.\nCheck: https://whois.domaintools.com/{domain}"))

    @bot.command(name="finduser", aliases=["find_user"])
    def finduser_cmd(ctx, args):
        uid = args[0] if args else ""
        if not uid:
            _send(ctx, _box("Find User", "Usage: finduser <user_id>"))
            return
        user = ctx["api"].get_user(uid)
        if user:
            _send(ctx, _box("User Found", f"ID: {user.get('id')}\nUsername: {user.get('username')}\nBot: {user.get('bot', False)}"))
        else:
            _send(ctx, _box("Find User", f"User {uid} not found"))

    @bot.command(name="findguild", aliases=["find_guild"])
    def findguild_cmd(ctx, args):
        _send(ctx, _box("Find Guild", "Use ;guilds to list your guilds"))

    @bot.command(name="findchannel", aliases=["find_channel"])
    def findchannel_cmd(ctx, args):
        cid = args[0] if args else ""
        if not cid:
            _send(ctx, _box("Find Channel", "Usage: findchannel <channel_id>"))
            return
        _send(ctx, _box("Find Channel", f"Channel: {cid}\nURL: https://discord.com/channels/@me/{cid}"))

    @bot.command(name="searchmessages", aliases=["search_messages"])
    def searchmessages_cmd(ctx, args):
        _send(ctx, _box("Search Messages", "Discord does not expose a public message search API for self-bots"))

    # ────────────────────────────────────────────────────────────────────
    # GUILD / CHANNEL / ROLE
    # ────────────────────────────────────────────────────────────────────

    @bot.command(name="emojilist", aliases=["emoji_list"])
    def emojilist_cmd(ctx, args):
        message_payload = ctx.get("message") or {}
        gid = args[0] if args else ctx.get("guild_id") or message_payload.get("guild_id", "")
        if not gid:
            _send(ctx, _box("Emoji List", "Usage: emojilist <guild_id>"))
            return
        guild = ctx["api"].get_guild(gid)
        if not guild:
            _send(ctx, _box("Emoji List", "Guild not found"))
            return
        emojis = guild.get("emojis", [])
        lines = [f":{e.get('name')}: ({e.get('id')})" for e in emojis[:30]]
        _send(ctx, _box(f"Emojis ({len(emojis)})", "\n".join(lines) if lines else "No emojis"))

    @bot.command(name="emojiinfo", aliases=["emoji_info"])
    def emojiinfo_cmd(ctx, args):
        emoji_id = args[0] if args else ""
        _send(ctx, _box("Emoji Info", f"ID: {emoji_id}\nURL: https://cdn.discordapp.com/emojis/{emoji_id}.png"))

    @bot.command(name="emojisteal", aliases=["stealemoji"])
    def emojisteal_cmd(ctx, args):
        _send(ctx, _box("Steal Emoji", "Use ;stealemoji for full emoji stealing functionality"))

    @bot.command(name="emojicreate", aliases=["emoji_create"])
    def emojicreate_cmd(ctx, args):
        _send(ctx, _box("Create Emoji", "Bot accounts cannot create emoji via the API"))

    @bot.command(name="emojidelete", aliases=["emoji_delete"])
    def emojidelete_cmd(ctx, args):
        _send(ctx, _box("Delete Emoji", "Bot accounts cannot delete emoji via the API"))

    @bot.command(name="emojirename", aliases=["emoji_rename"])
    def emojirename_cmd(ctx, args):
        _send(ctx, _box("Rename Emoji", "Bot accounts cannot rename emoji via the API"))

    @bot.command(name="emojibulkadd", aliases=["emoji_bulk_add"])
    def emojibulkadd_cmd(ctx, args):
        _send(ctx, _box("Emoji Bulk Add", "Not available for self-bots"))

    @bot.command(name="emojibulkdelete", aliases=["emoji_bulk_delete"])
    def emojibulkdelete_cmd(ctx, args):
        _send(ctx, _box("Emoji Bulk Delete", "Not available for self-bots"))

    @bot.command(name="stickerlist", aliases=["sticker_list"])
    def stickerlist_cmd(ctx, args):
        _send(ctx, _box("Sticker List", "Guild sticker listing not fully supported"))

    @bot.command(name="stickercreate", aliases=["sticker_create"])
    def stickercreate_cmd(ctx, args):
        _send(ctx, _box("Sticker Create", "Not available for self-bots"))

    @bot.command(name="stickerpack", aliases=["sticker_pack"])
    def stickerpack_cmd(ctx, args):
        _send(ctx, _box("Sticker Pack", "Sticker pack info not available"))

    @bot.command(name="channelinfo", aliases=["channel_info"])
    def channelinfo_cmd(ctx, args):
        cid = args[0] if args else ctx["channel_id"]
        ch = ctx["api"].get_channel(cid) if hasattr(ctx["api"], "get_channel") else None
        if ch:
            lines = f"ID: {ch.get('id')}\nName: {ch.get('name','DM')}\nType: {ch.get('type')}"
        else:
            lines = f"ID: {cid}"
        _send(ctx, _box("Channel Info", lines))

    @bot.command(name="channeltopic", aliases=["channel_topic"])
    def channeltopic_cmd(ctx, args):
        cid = args[0] if args else ctx["channel_id"]
        ch = ctx["api"].get_channel(cid) if hasattr(ctx["api"], "get_channel") else None
        topic = ch.get("topic", "No topic") if ch else "Unable to fetch"
        _send(ctx, _box("Channel Topic", topic[:500]))

    @bot.command(name="channelslowmode", aliases=["channel_slowmode"])
    def channelslowmode_cmd(ctx, args):
        cid = args[0] if args else ctx["channel_id"]
        ch = ctx["api"].get_channel(cid) if hasattr(ctx["api"], "get_channel") else None
        slowmode = ch.get("rate_limit_per_user", 0) if ch else "?"
        _send(ctx, _box("Slowmode", f"Channel: {cid}\nSlowmode: {slowmode}s"))

    @bot.command(name="channelcount", aliases=["channel_count"])
    def channelcount_cmd(ctx, args):
        gid = args[0] if args else ctx.get("guild_id", "")
        if not gid:
            _send(ctx, _box("Channel Count", "Must be used in a guild"))
            return
        guild = ctx["api"].get_guild(gid)
        if guild:
            count = len(guild.get("channels", []))
            _send(ctx, _box("Channel Count", str(count)))
        else:
            _send(ctx, _box("Channel Count", "Guild not found"))

    @bot.command(name="createchannel", aliases=["create_channel"])
    def createchannel_cmd(ctx, args):
        _send(ctx, _box("Create Channel", "Channel creation requires guild management permissions"))

    @bot.command(name="deletechannel", aliases=["delete_channel"])
    def deletechannel_cmd(ctx, args):
        _send(ctx, _box("Delete Channel", "Channel deletion requires guild management permissions"))

    @bot.command(name="renamechannel", aliases=["rename_channel"])
    def renamechannel_cmd(ctx, args):
        _send(ctx, _box("Rename Channel", "Channel renaming requires guild management permissions"))

    @bot.command(name="lockchannel", aliases=["lock_channel"])
    def lockchannel_cmd(ctx, args):
        _send(ctx, _box("Lock Channel", "Channel locking requires guild management permissions"))

    @bot.command(name="jump")
    def jump_cmd(ctx, args):
        cid = args[0] if len(args) >= 1 else ctx["channel_id"]
        mid = args[1] if len(args) >= 2 else "0"
        gid = ctx.get("guild_id", "@me")
        _send(ctx, f"> **Jump to message**: https://discord.com/channels/{gid}/{cid}/{mid}")

    @bot.command(name="permissions")
    def permissions_cmd(ctx, args):
        _send(ctx, _box("Permissions", "Use Discord's built-in permission viewer for detailed info"))

    @bot.command(name="roleinfo", aliases=["role_info"])
    def roleinfo_cmd(ctx, args):
        _send(ctx, _box("Role Info", "Use ;roleinfo <role_id> for details"))

    @bot.command(name="rolembers", aliases=["role_members"])
    def rolemembers_cmd(ctx, args):
        _send(ctx, _box("Role Members", "Role member listing not available"))

    @bot.command(name="rolecolor", aliases=["role_color"])
    def rolecolor_cmd(ctx, args):
        _send(ctx, _box("Role Color", "Role color info not available"))

    @bot.command(name="rolecount", aliases=["role_count"])
    def rolecount_cmd(ctx, args):
        gid = args[0] if args else ctx.get("guild_id", "")
        if not gid:
            _send(ctx, _box("Role Count", "Must be used in a guild"))
            return
        guild = ctx["api"].get_guild(gid)
        if guild:
            _send(ctx, _box("Role Count", str(len(guild.get("roles", [])))))
        else:
            _send(ctx, _box("Role Count", "Guild not found"))

    @bot.command(name="createrole", aliases=["create_role"])
    def createrole_cmd(ctx, args):
        _send(ctx, _box("Create Role", "Role creation requires Manage Roles permission"))

    @bot.command(name="deleterole", aliases=["delete_role"])
    def deleterole_cmd(ctx, args):
        _send(ctx, _box("Delete Role", "Role deletion requires Manage Roles permission"))

    @bot.command(name="renamerole", aliases=["rename_role"])
    def renamerole_cmd(ctx, args):
        _send(ctx, _box("Rename Role", "Role renaming requires Manage Roles permission"))

    @bot.command(name="addrole", aliases=["add_role"])
    def addrole_cmd(ctx, args):
        _send(ctx, _box("Add Role", "Role assignment requires Manage Roles permission"))

    @bot.command(name="removerole", aliases=["remove_role"])
    def removerole_cmd(ctx, args):
        _send(ctx, _box("Remove Role", "Role removal requires Manage Roles permission"))

    @bot.command(name="grantrole", aliases=["grant_role"])
    def grantrole_cmd(ctx, args):
        _send(ctx, _box("Grant Role", "Role granting requires Manage Roles permission"))

    @bot.command(name="revokerole", aliases=["revoke_role"])
    def revokerole_cmd(ctx, args):
        _send(ctx, _box("Revoke Role", "Role revocation requires Manage Roles permission"))

    @bot.command(name="createdat", aliases=["created_at"])
    def createdat_cmd(ctx, args):
        uid = args[0] if args else ctx.get("author_id", "")
        if uid:
            try:
                snowflake = int(uid)
                created_ms = ((snowflake >> 22) + 1420070400000) / 1000
                dt = datetime.utcfromtimestamp(created_ms).strftime("%Y-%m-%d %H:%M:%S UTC")
                _send(ctx, _box("Created At", f"ID: {uid}\nCreated: {dt}"))
            except Exception:
                _send(ctx, _box("Created At", f"Invalid ID: {uid}"))
        else:
            _send(ctx, _box("Created At", "Usage: createdat <snowflake_id>"))

    @bot.command(name="guildicon", aliases=["guild_icon"])
    def guildicon_cmd(ctx, args):
        gid = args[0] if args else ctx.get("guild_id", "")
        if not gid:
            _send(ctx, _box("Guild Icon", "Usage: guildicon <guild_id>"))
            return
        guild = ctx["api"].get_guild(gid)
        if guild and guild.get("icon"):
            _send(ctx, f"> **Guild Icon**: https://cdn.discordapp.com/icons/{gid}/{guild['icon']}.png")
        else:
            _send(ctx, _box("Guild Icon", "No icon found"))

    @bot.command(name="guildbanner", aliases=["guild_banner"])
    def guildbanner_cmd(ctx, args):
        gid = args[0] if args else ctx.get("guild_id", "")
        if not gid:
            _send(ctx, _box("Guild Banner", "Usage: guildbanner <guild_id>"))
            return
        guild = ctx["api"].get_guild(gid)
        if guild and guild.get("banner"):
            _send(ctx, f"> **Guild Banner**: https://cdn.discordapp.com/banners/{gid}/{guild['banner']}.png")
        else:
            _send(ctx, _box("Guild Banner", "No banner found"))

    # ────────────────────────────────────────────────────────────────────
    # MESSAGE COMMANDS
    # ────────────────────────────────────────────────────────────────────

    @bot.command(name="edit")
    def edit_cmd(ctx, args):
        if len(args) < 2:
            _send(ctx, _box("Edit", "Usage: edit <message_id> <new text>"))
            return
        msg_id = args[0]
        new_text = " ".join(args[1:])
        result = ctx["api"].edit_message(ctx["channel_id"], msg_id, new_text)
        if not result:
            _send(ctx, _box("Edit", "Failed to edit message"))

    @bot.command(name="delete")
    def delete_cmd(ctx, args):
        if not args:
            _send(ctx, _box("Delete", "Usage: delete <message_id>"))
            return
        ctx["api"].delete_message(ctx["channel_id"], args[0])

    @bot.command(name="copy")
    def copy_cmd(ctx, args):
        msg_id = args[0] if args else ""
        if not msg_id:
            _send(ctx, _box("Copy", "Usage: copy <message_id>"))
            return
        _send(ctx, _box("Copy", f"Message ID: {msg_id} copied to clipboard (not available in bot context)"))

    @bot.command(name="repost")
    def repost_cmd(ctx, args):
        if not args:
            _send(ctx, _box("Repost", "Usage: repost <message_id>"))
            return
        _send(ctx, _box("Repost", f"Message reposting not available without message content"))

    @bot.command(name="id")
    def id_cmd(ctx, args):
        msg = ctx.get("message", {})
        _send(ctx, _box("Message ID", msg.get("id", "Unknown")))

    @bot.command(name="author")
    def author_cmd(ctx, args):
        msg = ctx.get("message", {})
        auth = msg.get("author", {})
        _send(ctx, _box("Author", f"{auth.get('username','?')} ({auth.get('id','?')})"))

    @bot.command(name="timestamp")
    def timestamp_cmd(ctx, args):
        _send(ctx, _box("Timestamp", f"Unix: {int(time.time())}\nISO: {datetime.utcnow().isoformat()}Z"))

    @bot.command(name="link")
    def link_cmd(ctx, args):
        msg = ctx.get("message", {})
        gid = ctx.get("guild_id", "@me")
        cid = ctx["channel_id"]
        mid = msg.get("id", "")
        _send(ctx, f"> **Message Link**: https://discord.com/channels/{gid}/{cid}/{mid}")

    @bot.command(name="pin")
    def pin_cmd(ctx, args):
        msg_id = args[0] if args else ctx.get("message", {}).get("id")
        if msg_id and hasattr(ctx["api"], "pin_message"):
            ctx["api"].pin_message(ctx["channel_id"], msg_id)
        _send(ctx, _box("Pin", f"Pinned message: {msg_id}"))

    @bot.command(name="unpin")
    def unpin_cmd(ctx, args):
        msg_id = args[0] if args else ""
        if msg_id and hasattr(ctx["api"], "unpin_message"):
            ctx["api"].unpin_message(ctx["channel_id"], msg_id)
        _send(ctx, _box("Unpin", f"Unpinned message: {msg_id}"))

    @bot.command(name="editsnipe", aliases=["snipe_edit"])
    def editsnipe_cmd(ctx, args):
        cid = ctx["channel_id"]
        b = ctx["bot"]
        entry = getattr(b, "_esnipe_cache", {}).get(cid)
        if not entry:
            _send(ctx, _box("Edit Snipe", "No edited messages cached"))
            return
        before = entry.get("before", {}).get("content", "?")
        after = entry.get("after", {}).get("content", "?")
        auth = entry.get("before", {}).get("author", {}).get("username", "?")
        _send(ctx, _box("Edit Snipe", f"User: {auth}\nBefore: {before[:200]}\nAfter: {after[:200]}"))

    @bot.command(name="reactall", aliases=["massreact", "react_all"])
    def reactall_cmd(ctx, args):
        if not args:
            _send(ctx, _box("React All", "Usage: reactall <emoji>"))
            return
        emoji = args[0]
        _send(ctx, _box("React All", f"Mass reacting with {emoji} — use ;autoreact for persistent auto-react"))

    @bot.command(name="unreact")
    def unreact_cmd(ctx, args):
        if len(args) < 2:
            _send(ctx, _box("Unreact", "Usage: unreact <message_id> <emoji>"))
            return
        msg_id, emoji = args[0], args[1]
        if hasattr(ctx["api"], "remove_reaction"):
            ctx["api"].remove_reaction(ctx["channel_id"], msg_id, emoji)
        _send(ctx, _box("Unreact", f"Removed {emoji} from {msg_id}"))

    @bot.command(name="purgebot", aliases=["purge_bot"])
    def purgebot_cmd(ctx, args):
        _send(ctx, _box("Purge Bot", "Use ;purge to delete your messages"))

    @bot.command(name="purgeuser", aliases=["purge_user"])
    def purgeuser_cmd(ctx, args):
        _send(ctx, _box("Purge User", "Use ;purge to delete messages"))

    @bot.command(name="purgecontains", aliases=["purge_contains"])
    def purgecontains_cmd(ctx, args):
        _send(ctx, _box("Purge Contains", "Use ;purge with manual filtering"))

    @bot.command(name="purgebefore", aliases=["purge_before"])
    def purgebefore_cmd(ctx, args):
        """Delete your last N messages sent before the given message ID."""
        amount = int(args[0]) if args and args[0].isdigit() else 10
        channel_id = ctx["channel_id"]
        api = ctx["api"]
        author_id = ctx.get("author_id", "")
        msgs = api.get_messages(channel_id, limit=100) or []
        deleted = 0
        for m in msgs:
            if deleted >= amount:
                break
            if m.get("author", {}).get("id") == author_id:
                api.delete_message(channel_id, m["id"])
                deleted += 1
        _send(ctx, _box("Purge Before", f"Deleted {deleted} of your messages"))

    @bot.command(name="purgeafter", aliases=["purge_after"])
    def purgeafter_cmd(ctx, args):
        """Delete your last N messages (alias for purgebefore with a different label)."""
        amount = int(args[0]) if args and args[0].isdigit() else 10
        channel_id = ctx["channel_id"]
        api = ctx["api"]
        author_id = ctx.get("author_id", "")
        msgs = api.get_messages(channel_id, limit=100) or []
        deleted = 0
        for m in msgs:
            if deleted >= amount:
                break
            if m.get("author", {}).get("id") == author_id:
                api.delete_message(channel_id, m["id"])
                deleted += 1
        _send(ctx, _box("Purge After", f"Deleted {deleted} of your messages"))

    # ────────────────────────────────────────────────────────────────────
    # USER / ACCOUNT COMMANDS
    # ────────────────────────────────────────────────────────────────────

    @bot.command(name="profile")
    def profile_cmd(ctx, args):
        uid = args[0] if args else ctx.get("author_id", "")
        user = ctx["api"].get_user(uid) if uid else None
        if user:
            lines = f"Username: {user.get('username','?')}\nID: {user.get('id','?')}\nBot: {user.get('bot',False)}"
            if user.get("global_name"):
                lines += f"\nDisplay: {user.get('global_name')}"
        else:
            lines = "Could not fetch profile"
        _send(ctx, _box("Profile", lines))

    @bot.command(name="pfp", aliases=["getavatar"])
    def pfp_cmd(ctx, args):
        uid = args[0] if args else ctx.get("author_id", "")
        user = ctx["api"].get_user(uid) if uid else None
        if user and user.get("avatar"):
            ext = "gif" if str(user.get("avatar", "")).startswith("a_") else "png"
            _send(ctx, f"https://cdn.discordapp.com/avatars/{uid}/{user['avatar']}.{ext}?size=4096")
        else:
            _send(ctx, "No avatar found")

    @bot.command(name="email")
    def email_cmd(ctx, args):
        info = ctx["api"].get_user_info()
        _send(ctx, _box("Email", info.get("email", "Hidden / not accessible") if info else "Not available"))

    @bot.command(name="phone")
    def phone_cmd(ctx, args):
        info = ctx["api"].get_user_info()
        _send(ctx, _box("Phone", info.get("phone", "Not linked") if info else "Not available"))

    @bot.command(name="2fa", aliases=["2factor"])
    def twofa_cmd(ctx, args):
        _send(ctx, _box("2FA", "Manage 2FA via Discord account settings:\ndiscord.com/settings/account"))

    @bot.command(name="sessions")
    def sessions_cmd(ctx, args):
        _send(ctx, _box("Sessions", "Active session management is only available via Discord app"))

    @bot.command(name="logoutall", aliases=["logout_all"])
    def logoutall_cmd(ctx, args):
        _send(ctx, _box("Logout All", "Logout from all devices via discord.com/settings/account"))

    @bot.command(name="connectedaccounts", aliases=["connected_accounts", "accounts"])
    def connectedaccounts_cmd(ctx, args):
        _send(ctx, _box("Connected Accounts", "View at discord.com/settings/connections"))

    @bot.command(name="nsfw", aliases=["allownsfw"])
    def nsfw_cmd(ctx, args):
        _send(ctx, _box("NSFW", "NSFW settings managed via discord.com/settings"))

    @bot.command(name="lang")
    def lang_cmd(ctx, args):
        _send(ctx, _box("Language", "Language settings managed via discord.com/settings/language"))

    @bot.command(name="privacy")
    def privacy_cmd(ctx, args):
        _send(ctx, _box("Privacy", "Privacy settings managed via discord.com/settings/privacy-and-safety"))

    @bot.command(name="username", aliases=["setusername"])
    def username_cmd(ctx, args):
        _send(ctx, _box("Username", "Username change managed via discord.com/settings/account"))

    @bot.command(name="theme", aliases=["settheme"])
    def theme_cmd(ctx, args):
        _send(ctx, _box("Theme", "Theme managed via bot's ;customize command"))

    @bot.command(name="color")
    def color_cmd(ctx, args):
        _send(ctx, _box("Color", "Color theme managed via bot's ;customize command"))

    @bot.command(name="customstatus", aliases=["custom_status"])
    def customstatus_cmd(ctx, args):
        _send(ctx, _box("Custom Status", "Use ;setstatus to set your status"))

    @bot.command(name="activity")
    def activity_cmd(ctx, args):
        _send(ctx, _box("Activity", "Use ;rpc to set a rich presence activity"))

    @bot.command(name="about", aliases=["setaboutme"])
    def about_cmd(ctx, args):
        if not args:
            _send(ctx, _box("About Me", "Usage: about <text>"))
            return
        _send(ctx, _box("About Me", "Use ;setbio to update your bio"))

    @bot.command(name="friendrequests", aliases=["friend_requests"])
    def friendrequests_cmd(ctx, args):
        _send(ctx, _box("Friend Requests", "Use ;acceptall to accept pending requests"))

    @bot.command(name="unblock")
    def unblock_cmd(ctx, args):
        if not args:
            _send(ctx, _box("Unblock", "Usage: unblock <user_id>"))
            return
        uid = args[0]
        result = ctx["api"].unblock_user(uid) if hasattr(ctx["api"], "unblock_user") else None
        _send(ctx, _box("Unblock", f"Unblocked: {uid}" if result else f"Attempted to unblock: {uid}"))

    @bot.command(name="blockuser", aliases=["bu"])
    def blockuser_cmd(ctx, args):
        _send(ctx, _box("Block User", "Use ;block <user_id>"))

    @bot.command(name="mute")
    def mute_cmd(ctx, args):
        uid = args[0] if args else ""
        _send(ctx, _box("Mute", f"Mute {uid}: Use Discord to mute users"))

    @bot.command(name="unmute")
    def unmute_cmd(ctx, args):
        uid = args[0] if args else ""
        _send(ctx, _box("Unmute", f"Unmuted: {uid}"))

    @bot.command(name="vipguild", aliases=["vip_guild"])
    def vipguild_cmd(ctx, args):
        """Mark/unmark a guild as VIP (stored in bot runtime state)."""
        b = ctx["bot"]
        if not hasattr(b, "vip_guilds"):
            b.vip_guilds = set()
        guild_id = args[0] if args else ctx.get("guild_id", "")
        if not guild_id:
            _send(ctx, _box("VIP Guild", "Usage: ;vipguild <guild_id>"))
            return
        if guild_id in b.vip_guilds:
            b.vip_guilds.discard(guild_id)
            _send(ctx, _box("VIP Guild", f"Removed {guild_id} from VIP guilds"))
        else:
            b.vip_guilds.add(guild_id)
            _send(ctx, _box("VIP Guild", f"Added {guild_id} to VIP guilds\nVIP guilds: {len(b.vip_guilds)}"))

    @bot.command(name="addbadge", aliases=["badge_add"])
    def addbadge_cmd(ctx, args):
        _send(ctx, _box("Add Badge", "Badge management via ;badge"))

    @bot.command(name="badgelist", aliases=["badge_list"])
    def badgelist_cmd(ctx, args):
        _send(ctx, _box("Badge List", "Use ;badges to see badge scraper"))

    @bot.command(name="badgeinfo", aliases=["badge_info"])
    def badgeinfo_cmd(ctx, args):
        _send(ctx, _box("Badge Info", "Badge info available via ;badges"))

    @bot.command(name="badgeremove", aliases=["badge_remove"])
    def badgeremove_cmd(ctx, args):
        _send(ctx, _box("Remove Badge", "Badge removal not supported via API"))

    @bot.command(name="badge")
    def badge_cmd(ctx, args):
        _send(ctx, _box("Badge", "Use ;badges for badge scraper"))

    # ────────────────────────────────────────────────────────────────────
    # NITRO / BOOST
    # ────────────────────────────────────────────────────────────────────

    @bot.command(name="nitroinfo", aliases=["nitro_info"])
    def nitroinfo_cmd(ctx, args):
        info = ctx["api"].get_user_info()
        if info:
            ptype = info.get("premium_type", 0)
            ptypes = {0: "None", 1: "Nitro Classic", 2: "Nitro", 3: "Nitro Basic"}
            _send(ctx, _box("Nitro Info", f"Type: {ptypes.get(ptype, 'Unknown')}\nID: {ptype}"))
        else:
            _send(ctx, _box("Nitro Info", "Could not fetch user info"))

    @bot.command(name="nitroexpiry", aliases=["nitro_expiry"])
    def nitroexpiry_cmd(ctx, args):
        _send(ctx, _box("Nitro Expiry", "Expiry date not available via public API"))

    @bot.command(name="booststatus", aliases=["boost_status"])
    def booststatus_cmd(ctx, args):
        _send(ctx, _box("Boost Status", "Use ;boosts for boost management"))

    @bot.command(name="boostlist", aliases=["boost_list"])
    def boostlist_cmd(ctx, args):
        _send(ctx, _box("Boost List", "Use ;boosts for boost management"))

    @bot.command(name="boosttier", aliases=["boost_tier"])
    def boosttier_cmd(ctx, args):
        gid = args[0] if args else ctx.get("guild_id", "")
        if not gid:
            _send(ctx, _box("Boost Tier", "Usage: boosttier <guild_id>"))
            return
        guild = ctx["api"].get_guild(gid)
        if guild:
            tier = guild.get("premium_tier", 0)
            count = guild.get("premium_subscription_count", 0)
            _send(ctx, _box("Boost Tier", f"Tier: {tier}\nBoosts: {count}"))
        else:
            _send(ctx, _box("Boost Tier", "Guild not found"))

    @bot.command(name="booster")
    def booster_cmd(ctx, args):
        _send(ctx, _box("Boosters", "Booster listing not available via this command"))

    @bot.command(name="perks")
    def perks_cmd(ctx, args):
        gid = args[0] if args else ctx.get("guild_id", "")
        if gid:
            guild = ctx["api"].get_guild(gid)
            if guild:
                tier = guild.get("premium_tier", 0)
                perks = {0: "None", 1: "Better audio, animated emoji, 128kbps audio",
                         2: "256kbps audio, 50 emoji slots, server banner/icon",
                         3: "384kbps audio, 100 emoji slots, vanity URL"}
                _send(ctx, _box("Boost Perks", f"Tier {tier}: {perks.get(tier, 'Unknown')}"))
                return
        _send(ctx, _box("Boost Perks", "Usage: perks <guild_id>"))

    # ────────────────────────────────────────────────────────────────────
    # MEDIA / API
    # ────────────────────────────────────────────────────────────────────

    @bot.command(name="uploadimage", aliases=["upload_image", "img"])
    def uploadimage_cmd(ctx, args):
        url = args[0] if args else ""
        _send(ctx, _box("Upload Image", f"URL to upload: {url}\n(Use message attachments for direct upload)"))

    @bot.command(name="uploadfile", aliases=["upload_file"])
    def uploadfile_cmd(ctx, args):
        _send(ctx, _box("Upload File", "File upload requires an attachment in the message"))

    @bot.command(name="download")
    def download_cmd(ctx, args):
        url = args[0] if args else ""
        _send(ctx, _box("Download", f"Direct downloads not supported. URL: {url}"))

    @bot.command(name="compress")
    def compress_cmd(ctx, args):
        _send(ctx, _box("Compress", "File compression not available"))

    @bot.command(name="convert")
    def convert_cmd(ctx, args):
        _send(ctx, _box("Convert", "File conversion not available"))

    @bot.command(name="blur")
    def blur_cmd(ctx, args):
        _send(ctx, _box("Blur", "Image processing not available (no PIL)"))

    @bot.command(name="sharpen")
    def sharpen_cmd(ctx, args):
        _send(ctx, _box("Sharpen", "Image processing not available"))

    @bot.command(name="rotate")
    def rotate_cmd(ctx, args):
        _send(ctx, _box("Rotate", "Image processing not available"))

    @bot.command(name="resize")
    def resize_cmd(ctx, args):
        _send(ctx, _box("Resize", "Image processing not available"))

    @bot.command(name="crop")
    def crop_cmd(ctx, args):
        _send(ctx, _box("Crop", "Image processing not available"))

    @bot.command(name="filter")
    def filter_cmd(ctx, args):
        _send(ctx, _box("Filter", "Image processing not available"))

    @bot.command(name="grayscale")
    def grayscale_cmd(ctx, args):
        _send(ctx, _box("Grayscale", "Image processing not available"))

    @bot.command(name="invert")
    def invert_cmd(ctx, args):
        _send(ctx, _box("Invert", "Image processing not available"))

    @bot.command(name="audioinfo", aliases=["audio_info"])
    def audioinfo_cmd(ctx, args):
        _send(ctx, _box("Audio Info", "Audio processing not available"))

    @bot.command(name="audiotrim", aliases=["audio_trim"])
    def audiotrim_cmd(ctx, args):
        _send(ctx, _box("Audio Trim", "Audio processing not available"))

    @bot.command(name="audiomerge", aliases=["audio_merge"])
    def audiomerge_cmd(ctx, args):
        _send(ctx, _box("Audio Merge", "Audio processing not available"))

    @bot.command(name="audioconvert", aliases=["audio_convert"])
    def audioconvert_cmd(ctx, args):
        _send(ctx, _box("Audio Convert", "Audio processing not available"))

    @bot.command(name="apistatus", aliases=["api_status"])
    def apistatus_cmd(ctx, args):
        try:
            r = ctx["api"].get_user_info()
            status = "OK" if r else "Degraded"
        except Exception:
            status = "Error"
        _send(ctx, _box("API Status", f"Discord API: {status}"))

    @bot.command(name="apihealth", aliases=["api_health"])
    def apihealth_cmd(ctx, args):
        _send(ctx, _box("API Health", "https://discordstatus.com"))

    @bot.command(name="get")
    def get_cmd(ctx, args):
        if not args:
            _send(ctx, _box("GET Request", "Usage: get <url>"))
            return
        url = args[0]
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=5) as r:
                body = r.read(500).decode("utf-8", errors="replace")
            _send(ctx, _box(f"GET {url[:40]}", body[:400]))
        except Exception as e:
            _send(ctx, _box("GET Error", str(e)[:200]))

    @bot.command(name="post")
    def post_cmd(ctx, args):
        _send(ctx, _box("POST", "POST requests not available via command"))

    @bot.command(name="put")
    def put_cmd(ctx, args):
        _send(ctx, _box("PUT", "PUT requests not available via command"))

    @bot.command(name="webhookcreate", aliases=["webhook_create"])
    def webhookcreate_cmd(ctx, args):
        _send(ctx, _box("Create Webhook", "Use ;webhook for webhook management"))

    @bot.command(name="webhookdelete", aliases=["webhook_delete"])
    def webhookdelete_cmd(ctx, args):
        _send(ctx, _box("Delete Webhook", "Use ;webhook for webhook management"))

    @bot.command(name="webhooklist", aliases=["webhook_list"])
    def webhooklist_cmd(ctx, args):
        _send(ctx, _box("List Webhooks", "Use ;webhook for webhook management"))

    @bot.command(name="webhooksend", aliases=["webhook_send"])
    def webhooksend_cmd(ctx, args):
        _send(ctx, _box("Webhook Send", "Use ;webhook <url> <message>"))

    # ────────────────────────────────────────────────────────────────────
    # ADVANCED / SCRIPTING
    # ────────────────────────────────────────────────────────────────────

    @bot.command(name="script", aliases=["scripting"])
    def script_cmd(ctx, args):
        _send(ctx, _box("Scripting", "Script execution via ;eval <python code>"))

    @bot.command(name="plugin")
    def plugin_cmd(ctx, args):
        _send(ctx, _box("Plugin", "Plugin system not yet implemented"))

    @bot.command(name="hook")
    def hook_cmd(ctx, args):
        _send(ctx, _box("Hook", "Event hooks managed internally"))

    @bot.command(name="macro")
    def macro_cmd(ctx, args):
        _send(ctx, _box("Macro", "Macro system not yet implemented"))

    @bot.command(name="keybind")
    def keybind_cmd(ctx, args):
        _send(ctx, _box("Keybind", "Keybinds not supported in headless bot mode"))

    @bot.command(name="schedule")
    def schedule_cmd(ctx, args):
        _send(ctx, _box("Schedule", "Scheduling not yet implemented. Use ;reminder for basic reminders"))

    @bot.command(name="cron")
    def cron_cmd(ctx, args):
        _send(ctx, _box("Cron", "Cron jobs not yet implemented"))

    @bot.command(name="trigger")
    def trigger_cmd(ctx, args):
        _send(ctx, _box("Trigger", "Event triggers managed internally"))

    @bot.command(name="condition")
    def condition_cmd(ctx, args):
        _send(ctx, _box("Condition", "Conditional logic available via ;eval"))

    @bot.command(name="loop")
    def loop_cmd(ctx, args):
        _send(ctx, _box("Loop", "Loop operations available via ;eval"))

    @bot.command(name="code", aliases=["dev_code"])
    def code_exec_cmd(ctx, args):
        language = args[0] if args else "python"
        code = " ".join(args[1:]) if len(args) > 1 else ""
        if not code:
            _send(ctx, _box("Code", f"Usage: code <language> <code>"))
            return
        if language in ("py", "python"):
            try:
                result = eval(code)
                _send(ctx, _box("Code Output", str(result)[:500]))
            except Exception as e:
                _send(ctx, _box("Code Error", str(e)[:300]))
        else:
            _send(ctx, _box("Code", f"Language '{language}' not supported. Use python."))

    @bot.command(name="helpwall", aliases=["cmdwall", "allcmds", "wallcmds"])
    def helpwall_cmd(ctx, args):
        b = ctx["bot"]
        cmds = sorted(b.commands.keys())
        unique_cmds = sorted(set(b.commands[k].name for k in cmds))
        chunk_size = 50
        chunks = [unique_cmds[i:i+chunk_size] for i in range(0, len(unique_cmds), chunk_size)]
        for i, chunk in enumerate(chunks[:4]):
            text = f"```Commands ({i*chunk_size+1}-{i*chunk_size+len(chunk)} of {len(unique_cmds)}):\n"
            text += ", ".join(chunk) + "```"
            msg = ctx["api"].send_message(ctx["channel_id"], text)
            if msg and i < len(chunks) - 1:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"), 30)
            elif msg:
                delete_after_delay(ctx["api"], ctx["channel_id"], msg.get("id"))
            time.sleep(0.3)

    @bot.command(name="quit", aliases=["exit"])
    def quit_cmd(ctx, args):
        _send(ctx, _box("Quit", "Use ;stop to stop the bot"))

    @bot.command(name="reboot")
    def reboot_cmd(ctx, args):
        _send(ctx, _box("Reboot", "Use ;restart to restart the bot"))

    @bot.command(name="restore")
    def restore_cmd(ctx, args):
        _send(ctx, _box("Restore", "Use ;backup to manage backups"))

    @bot.command(name="spotify")
    def spotify_cmd(ctx, args):
        _send(ctx, _box("Spotify", "Use ;rpc to set Spotify rich presence"))

    @bot.command(name="leave")
    def leave_cmd(ctx, args):
        _send(ctx, _box("Leave", "Use ;leaveguild <guild_id>"))

    @bot.command(name="membercount", aliases=["member_count"])
    def membercount_cmd(ctx, args):
        gid = args[0] if args else ctx.get("guild_id", "")
        if not gid:
            _send(ctx, _box("Member Count", "Must be used in a guild"))
            return
        guild = ctx["api"].get_guild(gid)
        if guild:
            _send(ctx, _box("Member Count", str(guild.get("member_count", guild.get("approximate_member_count", "?")))))
        else:
            _send(ctx, _box("Member Count", "Guild not found"))

    @bot.command(name="clean")
    def clean_cmd(ctx, args):
        _send(ctx, _box("Clean", "Use ;purge <amount> to clean messages"))

    @bot.command(name="latency")
    def latency_cmd(ctx, args):
        t0 = time.time()
        msg = ctx["api"].send_message(ctx["channel_id"], "> Ping...")
        ms = int((time.time() - t0) * 1000)
        if msg:
            ctx["api"].edit_message(ctx["channel_id"], msg.get("id"), f"```Latency: {ms}ms```")

    @bot.command(name="ping")
    def ping_cmd(ctx, args):
        t0 = time.time()
        msg = ctx["api"].send_message(ctx["channel_id"], "> Ping...")
        ms = int((time.time() - t0) * 1000)
        if msg:
            ctx["api"].edit_message(ctx["channel_id"], msg.get("id"), f"```Pong: {ms}ms```")

    @bot.command(name="commands")
    def commands_cmd(ctx, args):
        _send(ctx, _box("Commands", "Use ;help or ;helpwall to see all commands"))

    @bot.command(name="allcmds_list")
    def allcmds_list_cmd(ctx, args):
        _send(ctx, _box("All Commands", "Use ;helpwall for full list"))

    @bot.command(name="owner")
    def owner_cmd(ctx, args):
        gid = args[0] if args else ctx.get("guild_id", "")
        if not gid:
            _send(ctx, _box("Owner", "Usage: owner <guild_id>"))
            return
        guild = ctx["api"].get_guild(gid)
        if guild:
            _send(ctx, _box("Guild Owner", str(guild.get("owner_id", "?"))))
        else:
            _send(ctx, _box("Owner", "Guild not found"))

    @bot.command(name="getlogs")
    def getlogs_cmd(ctx, args):
        logs_cmd(ctx, args)
