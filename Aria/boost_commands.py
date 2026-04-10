import json
import time

def setup_boost_commands(bot, api_client, delete_after_delay_func):
    from boost_manager import BoostManager
    boost_manager = BoostManager(api_client)
    boost_manager.load_state()
    
    @bot.command(name="boost")
    def boost_cmd(ctx, args):
        if not args:
            help_text = """```asciidoc
[ Boost Commands ]
boost <server_id> :: Boost a server
boost transfer <from_id> <to_id> :: Transfer boost
boost auto <server1,server2,...> :: Auto-boost from list
boost rotate <server1,server2,...> [hours] :: Auto-rotation
boost stop :: Stop rotation
boost status :: Check boost status
boost list :: List boosted servers```"""
            msg = ctx["api"].send_message(ctx["channel_id"], help_text)
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if args[0] == "status":
            import formatter as fmt
            boost_info = boost_manager.get_detailed_boost_info()
            bot_boosted = len(boost_manager.boosted_servers)

            cmds = [
                ("Total Slots",    str(boost_info['total_slots'])),
                ("Available",      str(boost_info['available'])),
                ("Used",           str(boost_info['used'])),
                ("On Cooldown",    str(boost_info['on_cooldown'])),
                ("User Boosted",   str(bot_boosted)),
            ]
            for i, cooldown in enumerate(boost_info['cooldowns'], 1):
                if cooldown['remaining_seconds'] > 0:
                    hours   = cooldown['remaining_seconds'] // 3600
                    minutes = (cooldown['remaining_seconds'] % 3600) // 60
                    cmds.append((f"Boost {i}", f"{hours}h {minutes}m Remaining"))
                else:
                    cmds.append((f"Boost {i}", "Expired"))

            # Build ANSI directly so the global formatter doesn't re-process it
            status_msg = fmt.header("Boost Status") + "\n" + fmt.command_list(cmds)
            msg = ctx["api"].send_message(ctx["channel_id"], status_msg)
        
        elif args[0] == "transfer" and len(args) >= 2:
            to_id = args[1]
            status_msg = ctx["api"].send_message(
                ctx["channel_id"],
                f"```asciidoc\n[ Boost Transfer ]\n> Finding available slots for {to_id}...```"
            )
            results, success_count = boost_manager.transfer_boost_slots(to_id)
            if not results:
                if status_msg:
                    ctx["api"].edit_message(
                        ctx["channel_id"], status_msg.get("id"),
                        f"```asciidoc\n[ Boost Transfer ]\n> No available boost slots (all on cooldown or already boosting target)```"
                    )
                msg = status_msg
            else:
                ANSI_RESET  = "\u001b[0m"
                ANSI_TITLE  = "\u001b[1;33m"
                ANSI_LABEL  = "\u001b[0;36m"
                ANSI_VALUE  = "\u001b[0;37m"
                ANSI_OK     = "\u001b[1;32m"
                ANSI_FAIL   = "\u001b[1;31m"
                body = (
                    f"{ANSI_TITLE}Boost Transfer Results{ANSI_RESET}\n"
                    f"{ANSI_LABEL}Guild:{ANSI_RESET} {ANSI_VALUE}{to_id}{ANSI_RESET}\n"
                    f"{ANSI_LABEL}Success:{ANSI_RESET} {ANSI_VALUE}{success_count}/{len(results)}{ANSI_RESET}\n\n"
                )
                for r in results:
                    color = ANSI_OK if r.get("ok") else ANSI_FAIL
                    icon  = "✓" if r.get("ok") else "✗"
                    body += f"{color}{icon} Slot {r['slot_id']}: {r['message']}{ANSI_RESET}\n"
                result_text = f"```ansi\n{body}```"
                if status_msg:
                    ctx["api"].edit_message(ctx["channel_id"], status_msg.get("id"), result_text)
                else:
                    ctx["api"].send_message(ctx["channel_id"], result_text)
                msg = status_msg
        
        elif args[0] == "auto" and len(args) >= 2:
            server_list = args[1].split(",")
            success, message = boost_manager.auto_boost_servers(server_list)
            if success:
                msg = ctx["api"].send_message(ctx["channel_id"], "> **Boost **successful in the server**.**")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **Boost **failed**.**\n> {message}")
        
        elif args[0] == "rotate" and len(args) >= 2:
            server_list = args[1].split(",")
            hours = int(args[2]) if len(args) >= 3 else 24
            success, message = boost_manager.start_rotation(server_list, hours)
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Boost** rotation started. {message}.")
        
        elif args[0] == "stop":
            success, message = boost_manager.stop_rotation()
            msg = ctx["api"].send_message(ctx["channel_id"], f"> **Boost** rotation stopped. {message}.")
        
        elif args[0] == "list":
            boosted = boost_manager.get_boosted_servers()
            if boosted:
                boosted_list = "\n".join([f"• {server_id}" for server_id in boosted[:10]])
                if len(boosted) > 10:
                    boosted_list += f"\n• ... and {len(boosted) - 10} more"
                msg = ctx["api"].send_message(ctx["channel_id"], f"```asciidoc\n[ Boosted Servers ]\n{boosted_list}```")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], "```asciidoc\n[ Boost ]\n> No boosted servers```")
        
        else:
            server_id = args[0]
            success, message = boost_manager.boost_server(server_id)
            if success:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **Boost **successful in the server**.**\n> Server: **{server_id}**")
            else:
                msg = ctx["api"].send_message(ctx["channel_id"], f"> **Boost **failed**.**\n> {message}")
        
        boost_manager.save_state()
        if 'msg' in locals() and msg:
            delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    original_stop = bot.stop
    def new_stop():
        boost_manager.save_state()
        original_stop()
    bot.stop = new_stop