"""
NEW COMMANDS FOR EXTENDED SYSTEM
Adds commands for friend scraper and self-hosting management
"""

def setup_extended_system_commands(bot, delete_after_delay_func):
    """Setup new system commands for friend scraper and self-hosting"""
    
    @bot.command(name="friends", aliases=["friendlist", "getfriends"])
    def friends_cmd(ctx, args):
        """Get list of friends with user IDs"""
        try:
            if not hasattr(ctx["bot"], "friend_scraper"):
                msg = ctx["api"].send_message(ctx["channel_id"], "```Friend scraper not initialized```")
                if msg:
                    delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            friend_ids = ctx["bot"].friend_scraper.get_all_friend_ids()
            
            if not friend_ids:
                msg = ctx["api"].send_message(ctx["channel_id"], "```No friends```")
                if msg:
                    delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            # Display first 20 friends
            friend_list = []
            for fid in friend_ids[:20]:
                details = ctx["bot"].friend_scraper.get_friend_details(fid)
                if details:
                    friend_list.append(f"{details.get('username', 'Unknown')} ({fid})")
            
            result = f"| Friends ({len(friend_ids)}) |\n" + "\n".join(friend_list)
            if len(friend_ids) > 20:
                result += f"\n... and {len(friend_ids) - 20} more"
            
            msg = ctx["api"].send_message(ctx["channel_id"], f"```{result}```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```Error: {str(e)[:100]}```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="friendcount", aliases=["friendscount"])
    def friendcount_cmd(ctx, args):
        """Get total friend count"""
        try:
            if not hasattr(ctx["bot"], "friend_scraper"):
                msg = ctx["api"].send_message(ctx["channel_id"], "```Friend scraper not initialized```")
                if msg:
                    delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            friend_ids = ctx["bot"].friend_scraper.get_all_friend_ids()
            msg = ctx["api"].send_message(ctx["channel_id"], f"```Friends: {len(friend_ids)}```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```Error: {str(e)[:100]}```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="mutualfriends")
    def mutualfriends_cmd(ctx, args):
        """Get mutual friends with another user: +mutualfriends <user_id>"""
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "```Usage: +mutualfriends <user_id>```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        try:
            if not hasattr(ctx["bot"], "friend_scraper"):
                msg = ctx["api"].send_message(ctx["channel_id"], "```Friend scraper not initialized```")
                if msg:
                    delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
                return
            
            user_id = args[0].strip("<>@!")
            mutuals = ctx["bot"].friend_scraper.get_mutual_friends_with(user_id)
            
            msg = ctx["api"].send_message(ctx["channel_id"], 
                f"```Mutual Friends: {len(mutuals)}\n{chr(10).join(mutuals[:10])}```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
        except Exception as e:
            msg = ctx["api"].send_message(ctx["channel_id"], f"```Error: {str(e)[:100]}```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="registerself", aliases=["registerhost"])
    def registerself_cmd(ctx, args):
        """Register as self-hosted: +registerself <token> [prefix]
        Owner only command
        """
        if not hasattr(ctx["bot"], "self_hosting_manager"):
            msg = ctx["api"].send_message(ctx["channel_id"], "```Self-hosting not available```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if len(args) < 1:
            msg = ctx["api"].send_message(ctx["channel_id"], "```Usage: +registerself <token> [prefix]```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        token = args[0].strip('"\' ')
        prefix = args[1] if len(args) > 1 else ";"
        user_id = ctx["author_id"]
        
        success, message = ctx["bot"].self_hosting_manager.register_user(
            user_id, token, ctx["author_id"], prefix
        )
        
        msg = ctx["api"].send_message(ctx["channel_id"], f"```{message}```")
        if msg:
            delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="selfhoststatus", aliases=["hostingstatus"])
    def selfhoststatus_cmd(ctx, args):
        """Check self-hosting status"""
        if not hasattr(ctx["bot"], "self_hosting_manager"):
            msg = ctx["api"].send_message(ctx["channel_id"], "```Self-hosting not available```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        accounts = ctx["bot"].self_hosting_manager.list_hosted_accounts(ctx["author_id"])
        
        if not accounts:
            msg = ctx["api"].send_message(ctx["channel_id"], "```No self-hosted accounts```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        result = f"| Self-Hosted Accounts ({len(accounts)}) |\n"
        for acc in accounts:
            status = "✓" if acc.get("enabled") else "✗"
            result += f"{status} {acc['user_id']} | prefix: {acc['prefix']}\n"
        
        msg = ctx["api"].send_message(ctx["channel_id"], f"```{result}```")
        if msg:
            delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="unregisterself", aliases=["unregisterhost"])
    def unregisterself_cmd(ctx, args):
        """Unregister self-hosted account: +unregisterself <user_id>"""
        if not hasattr(ctx["bot"], "self_hosting_manager"):
            msg = ctx["api"].send_message(ctx["channel_id"], "```Self-hosting not available```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "```Usage: +unregisterself <user_id>```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        user_id = args[0]
        success, message = ctx["bot"].self_hosting_manager.unregister_user(user_id, ctx["author_id"])
        
        msg = ctx["api"].send_message(ctx["channel_id"], f"```{message}```")
        if msg:
            delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="disableselfhost")
    def disableselfhost_cmd(ctx, args):
        """Disable a self-hosted account: +disableselfhost <user_id>"""
        if not hasattr(ctx["bot"], "self_hosting_manager"):
            return
        
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "```Usage: +disableselfhost <user_id>```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        user_id = args[0]
        success, message = ctx["bot"].self_hosting_manager.disable_account(user_id)
        
        msg = ctx["api"].send_message(ctx["channel_id"], f"```{message}```")
        if msg:
            delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    @bot.command(name="enableselfhost")
    def enableselfhost_cmd(ctx, args):
        """Enable a self-hosted account: +enableselfhost <user_id>"""
        if not hasattr(ctx["bot"], "self_hosting_manager"):
            return
        
        if not args:
            msg = ctx["api"].send_message(ctx["channel_id"], "```Usage: +enableselfhost <user_id>```")
            if msg:
                delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
            return
        
        user_id = args[0]
        success, message = ctx["bot"].self_hosting_manager.enable_account(user_id)
        
        msg = ctx["api"].send_message(ctx["channel_id"], f"```{message}```")
        if msg:
            delete_after_delay_func(ctx["api"], ctx["channel_id"], msg.get("id"))
    
    print("✓ Extended system commands loaded (Friend scraper + Self-hosting)")
