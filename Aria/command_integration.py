"""
Integration module - Connects real command handlers to the Discord bot
All commands listed here actually work.
"""

import formatter as fmt
from command_engine import CommandEngine
import time


class CommandIntegration:
    """Integrates real command handlers with DiscordBot"""
    
    def __init__(self, bot, api_client, prefix: str = ";"):
        self.bot = bot
        self.api_client = api_client
        self.engine = CommandEngine(prefix=prefix)
        # NOTE: setup_commands_500 intentionally NOT called — it only added fake metadata
    
    def _unique_commands(self):
        """Return only primary-name commands (no aliases), sorted."""
        return sorted(
            {name: cmd for name, cmd in self.bot.commands.items() if cmd.name == name}.items()
        )

    def setup_help_commands(self):
        """Register help commands with the bot"""
        
        if "help" not in self.bot.commands:
            @self.bot.command(name="help", aliases=["h", "commands"])
            def cmd_help(ctx, args):
                # Fallback only when main.py help is unavailable.
                unique = self._unique_commands()
                lines = [(name, "") for name, _ in unique]
                msg_text = fmt.command_page(
                    "Commands",
                    lines,
                    f"{len(unique)} commands available",
                )
                self.api_client.send_message(ctx["channel_id"], msg_text)
        else:
            @self.bot.command(name="helpfallback")
            def cmd_helpfallback(ctx, args):
                # Keep manual-access fallback without overriding primary help handler.
                unique = self._unique_commands()
                lines = [(name, "") for name, _ in unique]
                msg_text = fmt.command_page(
                    "Commands",
                    lines,
                    f"{len(unique)} commands available",
                )
                self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="helpwall", aliases=["wallcmds"])
        def cmd_helpwall(ctx, args):
            """List all real registered commands split across messages."""
            unique = self._unique_commands()
            prefix = self.bot.prefix
            chunk, messages = [], []
            for name, cmd in unique:
                aliases = f" [{', '.join(cmd.aliases)}]" if cmd.aliases else ""
                chunk.append(f"{fmt.CYAN}{prefix}{name}{fmt.RESET}{fmt.DARK}{aliases}{fmt.RESET}")
                if len(chunk) >= 30:
                    messages.append(fmt._block("\n".join(chunk)))
                    chunk = []
            if chunk:
                messages.append(fmt._block("\n".join(chunk)))
            for m in messages:
                sent = self.api_client.send_message(ctx["channel_id"], m)
        
        @self.bot.command(name="cmdinfo")
        def cmd_cmdinfo(ctx, args):
            """Show info for a real registered command."""
            if not args:
                msg_text = fmt.error(f"Usage: {self.bot.prefix}cmdinfo <command>")
                self.api_client.send_message(ctx["channel_id"], msg_text)
                return
            name = args[0].lower()
            cmd = self.bot.commands.get(name)
            if not cmd:
                self.api_client.send_message(ctx["channel_id"], fmt.error(f"Unknown command: {name}"))
                return
            info = {"Name": cmd.name}
            if cmd.aliases:
                info["Aliases"] = ", ".join(cmd.aliases)
            info["Status"] = "Active"
            self.api_client.send_message(ctx["channel_id"], fmt.status_box("Command Info", info))
        
        @self.bot.command(name="quickhelp")
        def cmd_quickhelp(ctx, args):
            """Show a quick overview of loaded commands."""
            unique = self._unique_commands()
            prefix = self.bot.prefix
            lines = [(f"{prefix}{name}", ", ".join(cmd.aliases) if cmd.aliases else "—") for name, cmd in unique[:25]]
            msg_text = fmt.command_page(
                "Quick Help",
                lines,
                f"{len(unique)} total commands — use {prefix}helpwall to see all",
            )
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="categories")
        def cmd_categories(ctx, args):
            """Show real command count with a category-style breakdown."""
            unique = self._unique_commands()
            real_count = len(unique)
            prefix = self.bot.prefix

            # Build a quick keyword-based category map from real commands
            _cat_map = {
                "System": ["help", "helpwall", "cmdwall", "categories", "quickhelp", "cmdinfo",
                            "restart", "stop", "setprefix", "customize", "terminal", "ui",
                            "web", "backup", "version"],
                "Profile": ["setpfp", "setbanner", "stealpfp", "stealbanner", "stealname",
                             "bio", "setbio", "pronouns", "setpronouns", "displayname",
                             "setdisplayname", "setstatus", "deco"],
                "Guild": ["guilds", "myguilds", "guildinfo", "guildbadge", "guildmembers",
                           "leaveguild", "massleave", "joininvite", "join", "exportguilds"],
                "Messaging": ["purge", "spam", "massdm", "dmuser", "deletehistory",
                               "snipe", "esnipe", "react", "typing", "channelmsgs"],
                "User": ["userinfo", "friends", "mutualinfo", "block", "acceptall",
                          "bulkcheck", "checktoken", "inviteinfo", "createinvite",
                          "channelinfo", "hypesquad", "status", "client"],
                "Activity": ["rpc", "vrrpc", "superreact", "autoreact"],
                "Tools": ["history", "badges", "quest", "localstats", "export",
                           "scrapesummary", "ms", "bold", "italic", "upper", "lower",
                           "reverse", "mock", "flip", "echo", "length", "time"],
                "Host": ["host", "stophost", "listhosted", "hoststopall", "hoston",
                          "hostoff", "hostblacklist", "listallhosted"],
                "Boost": ["nitro", "giveaway"],
                "Voice": ["vc", "vce", "vccam", "vcstream"],
            }
            cmd_names = {name for name, _ in unique}
            breakdown = {}
            assigned = set()
            for cat, cmds in _cat_map.items():
                matched = [c for c in cmds if c in cmd_names]
                if matched:
                    breakdown[cat] = len(matched)
                    assigned.update(matched)
            other = len([n for n in cmd_names if n not in assigned])
            if other:
                breakdown["Other"] = other

            info = {cat: str(cnt) for cat, cnt in sorted(breakdown.items())}
            info["──────────"] = "──────────"
            info["Total"] = str(real_count)
            info["Tip"] = f"{prefix}helpwall · {prefix}cmdwall · {prefix}help"
            msg_text = fmt.status_box("Commands Overview", info)
            self.api_client.send_message(ctx["channel_id"], msg_text)
    
    def setup_text_commands(self):
        """Register text manipulation commands - ANSI SAFE OUTPUT"""
        
        @self.bot.command(name="bold")
        def cmd_bold(ctx, args):
            text = " ".join(args) if args else "No text"
            msg_text = fmt.success(f"**{text}**")
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="italic")
        def cmd_italic(ctx, args):
            text = " ".join(args) if args else "No text"
            msg_text = fmt.success(f"*{text}*")
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="underline")
        def cmd_underline(ctx, args):
            text = " ".join(args) if args else "No text"
            msg_text = fmt.success(f"__{text}__")
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="strike", aliases=["strikethrough"])
        def cmd_strike(ctx, args):
            text = " ".join(args) if args else "No text"
            msg_text = fmt.success(f"~~{text}~~")
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="reverse")
        def cmd_reverse(ctx, args):
            text = " ".join(args) if args else "No text"
            reversed_text = text[::-1]
            msg_text = fmt._block(f"{fmt.CYAN}Original:{fmt.RESET} {text}\n{fmt.CYAN}Reversed:{fmt.RESET} {reversed_text}")
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="upper")
        def cmd_upper(ctx, args):
            text = " ".join(args).upper() if args else "No text"
            msg_text = fmt._block(f"{fmt.YELLOW}{text}{fmt.RESET}")
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="lower")
        def cmd_lower(ctx, args):
            text = " ".join(args).lower() if args else "No text"
            msg_text = fmt._block(f"{fmt.YELLOW}{text}{fmt.RESET}")
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="mock")
        def cmd_mock(ctx, args):
            """SpongeBob mocking text"""
            text = " ".join(args) if args else "No text"
            mock_text = "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(text))
            msg_text = fmt._block(f"{fmt.PURPLE}{mock_text}{fmt.RESET}")
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="flip")
        def cmd_flip(ctx, args):
            """Flip text upside down"""
            text = " ".join(args) if args else "No text"
            # Simple upside-down character mapping
            flip_map = {
                'a': 'ɐ', 'e': 'ǝ', 'i': 'ı', 'o': 'o', 'u': 'n',
                'v': 'Λ', 'w': 'M', 'A': '∀', 'E': 'Ǝ', 'M': 'W',
            }
            flipped = ""
            for c in text[::-1]:
                flipped += flip_map.get(c, c)
            msg_text = fmt._block(f"{fmt.CYAN}{flipped}{fmt.RESET}")
            self.api_client.send_message(ctx["channel_id"], msg_text)
    
    def setup_utility_commands(self):
        """Register utility commands - ANSI SAFE OUTPUT"""
        
        @self.bot.command(name="echo")
        def cmd_echo(ctx, args):
            text = " ".join(args) if args else "No text"
            msg_text = fmt._block(f"{fmt.WHITE}{text}{fmt.RESET}")
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="length")
        def cmd_length(ctx, args):
            text = " ".join(args) if args else "No text"
            length = len(text)
            msg_text = fmt.status_box("Text Length", {
                "Text": text[:50] + "..." if len(text) > 50 else text,
                "Length": str(length),
                "Words": str(len(text.split()))
            })
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="time")
        def cmd_time(ctx, args):
            from datetime import datetime
            now = datetime.now()
            msg_text = fmt.status_box("Current Time", {
                "Time": now.strftime("%H:%M:%S"),
                "Date": now.strftime("%Y-%m-%d"),
                "Unix": str(int(now.timestamp())),
                "Timezone": "UTC"
            })
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="ms", aliases=["ping", "latency"])
        def cmd_ping(ctx, args):
            start = time.time()
            msg = self.api_client.send_message(ctx["channel_id"], "> Ping...")
            latency = int((time.time() - start) * 1000)
            
            msg_text = fmt.status_box("Latency", {
                "Response Time": f"{latency}ms",
                "Status": "✓ Healthy" if latency < 200 else "⚠ Slow"
            })
            
            if msg:
                self.api_client.edit_message(ctx["channel_id"], msg.get("id"), msg_text)
    
    def register_all(self):
        """Register all command groups"""
        self.setup_help_commands()
        self.setup_text_commands()
        self.setup_utility_commands()


def integrate_command_engine(bot, api_client, prefix: str = ";"):
    """Quick integration function
    
    Usage in main.py:
        from command_integration import integrate_command_engine
        integrate_command_engine(bot, bot.api, ";")
    """
    integration = CommandIntegration(bot, api_client, prefix)
    integration.register_all()
    return integration
