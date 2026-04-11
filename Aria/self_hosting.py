"""
Self-User Hosting System
Allows hosted users to use bot functions through their own token 
(like a self-user bot) instead of running a separate bot instance
"""

import json
import time
import threading
from typing import Dict, Any, Optional, Tuple

class SelfUserHostingManager:
    """
    Manager for hosting user accounts as self-bots.
    Each hosted user gets the same command set and functionality
    but as if they're running the bot themselves with their own token.
    """
    
    def __init__(self):
        self.hosted_accounts = {}  # user_id -> {token, api_client, prefix, settings}
        self.api_clients = {}      # user_id -> DiscordAPIClient
        self.settings_file = "self_hosted_accounts.json"
        self.lock = threading.Lock()
        self._load_settings()
    
    def _load_settings(self):
        """Load persisted hosted account settings"""
        try:
            if __import__("os").path.exists(self.settings_file):
                with open(self.settings_file, "r") as f:
                    data = json.load(f)
                    self.hosted_accounts = {
                        uid: {
                            "token": acc.get("token", ""),
                            "prefix": acc.get("prefix", "+"),
                            "owner": acc.get("owner", ""),
                            "settings": acc.get("settings", {}),
                            "enabled": acc.get("enabled", True)
                        }
                        for uid, acc in data.items()
                    }
        except Exception as e:
            print(f"[SelfHosting] Error loading settings: {e}")
            self.hosted_accounts = {}
    
    def _save_settings(self):
        """Persist hosted account settings"""
        try:
            with open(self.settings_file, "w") as f:
                json.dump(self.hosted_accounts, f, indent=2)
        except Exception as e:
            print(f"[SelfHosting] Error saving settings: {e}")
    
    def register_user(self, user_id: str, token: str, owner_id: str,
                     prefix: str = ";", settings: Dict[str, Any] = None) -> Tuple[bool, str]:
        """
        Register a user as a self-hosted account.
        The user will have access to bot functions using their own token.
        """
        user_id = str(user_id)
        
        # Validate token format
        if not token or not "." in token:
            return False, "Invalid token format"
        
        with self.lock:
            if user_id in self.hosted_accounts:
                return False, "User already registered"
            
            self.hosted_accounts[user_id] = {
                "token": token,
                "prefix": prefix or ";",
                "owner": str(owner_id),
                "settings": settings or {},
                "enabled": True,
                "registered_at": time.time()
            }
            
            self._save_settings()
            print(f"[SelfHosting] Registered user {user_id} | owner: {owner_id} | prefix: {prefix}")
            return True, f"User {user_id} registered as self-hosted"
    
    def get_account(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get  a hosted user account info"""
        return self.hosted_accounts.get(str(user_id))
    
    def get_account_token(self, user_id: str) -> Optional[str]:
        """Get a hosted user's token"""
        account = self.get_account(user_id)
        if account and account.get("enabled"):
            return account.get("token")
        return None
    
    def get_account_prefix(self, user_id: str) -> str:
        """Get a hosted user's command prefix"""
        account = self.get_account(user_id)
        return account.get("prefix", ";") if account else ";"
    
    def is_self_hosted(self, user_id: str) -> bool:
        """Check if user is registered as self-hosted"""
        account = self.get_account(user_id)
        return bool(account and account.get("enabled"))
    
    def unregister_user(self, user_id: str, owner_id: str) -> Tuple[bool, str]:
        """Unregister a self-hosted user"""
        user_id = str(user_id)
        
        with self.lock:
            account = self.hosted_accounts.get(user_id)
            if not account:
                return False, "User not registered"
            
            # Check permissions
            if str(account.get("owner")) != str(owner_id):
                return False, "Permission denied"
            
            del self.hosted_accounts[user_id]
            self._save_settings()
            print(f"[SelfHosting] Unregistered user {user_id}")
            return True, f"User {user_id} unregistered"
    
    def disable_account(self, user_id: str) -> Tuple[bool, str]:
        """Disable a self-hosted account"""
        user_id = str(user_id)
        
        with self.lock:
            account = self.hosted_accounts.get(user_id)
            if not account:
                return False, "User not registered"
            
            account["enabled"] = False
            self._save_settings()
            return True, f"User {user_id} account disabled"
    
    def enable_account(self, user_id: str) -> Tuple[bool, str]:
        """Enable a self-hosted account"""
        user_id = str(user_id)
        
        with self.lock:
            account = self.hosted_accounts.get(user_id)
            if not account:
                return False, "User not registered"
            
            account["enabled"] = True
            self._save_settings()
            return True, f"User {user_id} account enabled"
    
    def update_prefix(self, user_id: str, new_prefix: str) -> Tuple[bool, str]:
        """Update a user's command prefix"""
        user_id = str(user_id)
        
        with self.lock:
            account = self.hosted_accounts.get(user_id)
            if not account:
                return False, "User not registered"
            
            account["prefix"] = new_prefix
            self._save_settings()
            return True, f"Prefix updated to '{new_prefix}'"
    
    def list_hosted_accounts(self, owner_id: str = None) -> list:
        """List all hosted accounts (optionally filtered by owner)"""
        with self.lock:
            accounts = []
            for uid, account in self.hosted_accounts.items():
                if owner_id and str(account.get("owner")) != str(owner_id):
                    continue
                accounts.append({
                    "user_id": uid,
                    "owner": account.get("owner"),
                    "prefix": account.get("prefix"),
                    "enabled": account.get("enabled", True),
                    "registered_at": account.get("registered_at")
                })
            return accounts
    
    def print_summary(self):
        """Print all registered accounts at startup"""
        with self.lock:
            total = len(self.hosted_accounts)
            if total == 0:
                print(f"\033[1;36m[SELF-HOSTING]\033[0m No registered accounts")
                return
            
            print(f"\033[1;36m[SELF-HOSTING]\033[0m Loaded {total} registered accounts")
            
            seen_users = set()
            for uid, account in self.hosted_accounts.items():
                if uid in seen_users:
                    continue
                seen_users.add(uid)
                
                status = "✓" if account.get("enabled") else "✗"
                owner = account.get("owner", "unknown")
                prefix = account.get("prefix", "+")
                print(f"  {status} user_id={uid} | owner={owner} | prefix={prefix}")


# Global instance
self_hosting_manager = SelfUserHostingManager()
