"""
Integration module - Connects CommandEngine to the Discord bot
Ensures all help output is ANSI-safe (properly wrapped in codeblocks)
"""

import formatter as fmt
from command_engine import CommandEngine, setup_commands_500
import time


class CommandIntegration:
    """Integrates CommandEngine with DiscordBot"""
    
    def __init__(self, bot, api_client, prefix: str = "+"):
        self.bot = bot
        self.api_client = api_client
        self.engine = CommandEngine(prefix=prefix)
        setup_commands_500(self.engine)
    
    def setup_help_commands(self):
        """Register help commands with the bot"""
        
        @self.bot.command(name="help", aliases=["h", "commands"])
        def cmd_help(ctx, args):
            """Main help command - ANSI SAFE with pagination guide"""
            if not args:
                # Show all categories with improved info
                categories = self.engine.get_all_categories()
                lines = []
                for cat_name in sorted(categories.keys()):
                    cat_cmds = self.engine.get_category_commands(cat_name)
                    pages = (len(cat_cmds) + 11) // 12
                    page_info = f" ({pages} page{'s' if pages > 1 else ''})" if pages > 1 else ""
                    lines.append((cat_name.ljust(15), categories[cat_name] + page_info))
                
                msg_text = fmt.command_page(
                    "📚 Command Categories",
                    lines,
                    f"Usage: +help <category> [page]\nExample: +help general 1  or  +help profile 2"
                )
                msg = self.api_client.send_message(ctx["channel_id"], msg_text)
                return
            
            category = args[0].lower()
            
            # Get page number if provided
            page = 1
            if len(args) > 1:
                try:
                    page = int(args[1])
                except (ValueError, IndexError):
                    page = 1
            
            # Generate help page
            msg_text = self.engine.help_category(category, page)
            msg = self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="helpwall", aliases=["cmdwall", "allcmds", "wallcmds"])
        def cmd_helpwall(ctx, args):
            """Show all commands in walls - ANSI SAFE
            
            Automatically splits into Discord's 2000 char limit
            """
            self.engine.send_help_wall(ctx, self.api_client)
        
        @self.bot.command(name="cmdinfo")
        def cmd_cmdinfo(ctx, args):
            """Get detailed command info - ANSI SAFE"""
            if not args:
                msg_text = fmt.error("Usage: +cmdinfo <command_name>")
                self.api_client.send_message(ctx["channel_id"], msg_text)
                return
            
            cmd_name = args[0].lower()
            msg_text = self.engine.command_info(cmd_name)
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="quickhelp")
        def cmd_quickhelp(ctx, args):
            """Quick help with popular commands - ANSI SAFE"""
            msg_text = self.engine.help_quick(count=20)
            self.api_client.send_message(ctx["channel_id"], msg_text)
        
        @self.bot.command(name="categories")
        def cmd_categories(ctx, args):
            """List all command categories - ANSI SAFE"""
            categories = self.engine.get_all_categories()
            lines = []
            for cat_name in sorted(categories.keys()):
                lines.append((cat_name.ljust(15), categories[cat_name]))
            
            msg_text = fmt.command_page(
                "Command Categories",
                lines,
                f"Use +help <category> to view commands"
            )
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


def integrate_command_engine(bot, api_client, prefix: str = "+"):
    """Quick integration function
    
    Usage in main.py:
        from command_integration import integrate_command_engine
        integrate_command_engine(bot, bot.api, "+")
    """
    integration = CommandIntegration(bot, api_client, prefix)
    integration.register_all()
    return integration
