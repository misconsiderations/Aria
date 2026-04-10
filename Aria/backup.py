import json
import time
import os
import zipfile
from datetime import datetime

class BackupManager:
    def __init__(self, api_client):
        self.api = api_client
        self.backup_dir = "backups"
        self._ensure_backup_dir()
    
    def _ensure_backup_dir(self):
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir)
    
    def backup_user_data(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_data = {}
        
        print(f"[Backup] Starting user data backup...")
        
        user_info = self.api.get_user_info(force=True)
        if user_info:
            backup_data["user"] = user_info
            print(f"[Backup] Saved user info")
        
        friends = self.api.get_friends()
        if friends:
            backup_data["friends"] = friends
            print(f"[Backup] Saved {len(friends)} friends")
        
        guilds = self.api.get_guilds(force=True)
        if guilds:
            backup_data["guilds"] = guilds
            print(f"[Backup] Saved {len(guilds)} guilds")
        
            guild_details = {}
            for guild in guilds[:10]:
                try:
                    guild_id = guild["id"]
                    channels = self.api.get_channels(guild_id, force=True)
                    if channels:
                        guild_details[guild_id] = {
                            "channels": channels,
                            "name": guild.get("name", "Unknown")
                        }
                    time.sleep(0.5)
                except:
                    continue
            backup_data["guild_details"] = guild_details
        
        dms_response = self.api.request("GET", "/users/@me/channels")
        if dms_response and dms_response.status_code == 200:
            dm_channels = dms_response.json()
            backup_data["dm_channels"] = dm_channels
            print(f"[Backup] Saved {len(dm_channels)} DM channels")

        if os.path.exists("hosted_users.json"):
            try:
                with open("hosted_users.json", "r") as f:
                    backup_data["hosted_users"] = json.load(f)
                print(f"[Backup] Saved hosted_users.json")
            except Exception:
                pass

        filename = f"{self.backup_dir}/backup_{timestamp}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, indent=2, ensure_ascii=False)
        
        print(f"[Backup] Backup saved to {filename}")
        return filename
    
    def backup_messages(self, channel_id, limit=1000):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        all_messages = []
        last_id = None
        
        print(f"[Backup] Backing up messages from channel {channel_id}...")
        
        for i in range(0, limit, 100):
            fetch_limit = min(100, limit - len(all_messages))
            if fetch_limit <= 0:
                break
            
            params = {"limit": fetch_limit}
            if last_id:
                params["before"] = last_id
            
            messages = self.api.get_messages(channel_id, fetch_limit, last_id)
            if not messages:
                break
            
            all_messages.extend(messages)
            last_id = messages[-1]["id"]
            
            print(f"[Backup] Collected {len(all_messages)}/{limit} messages")
            time.sleep(0.5)
        
        filename = f"{self.backup_dir}/messages_{channel_id}_{timestamp}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(all_messages, f, indent=2, ensure_ascii=False)
        
        print(f"[Backup] Saved {len(all_messages)} messages to {filename}")
        return filename
    
    def create_full_backup(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_folder = f"{self.backup_dir}/full_backup_{timestamp}"
        
        if not os.path.exists(backup_folder):
            os.makedirs(backup_folder)
        
        print(f"[Backup] Creating full backup in {backup_folder}...")
        
        user_backup = self.backup_user_data()
        if user_backup and os.path.exists(user_backup):
            import shutil
            shutil.move(user_backup, f"{backup_folder}/user_data.json")
        
        guilds = self.api.get_guilds()
        if guilds:
            guilds_file = f"{backup_folder}/guilds.json"
            with open(guilds_file, 'w', encoding='utf-8') as f:
                json.dump(guilds, f, indent=2, ensure_ascii=False)
        
        friends = self.api.get_friends()
        if friends:
            friends_file = f"{backup_folder}/friends.json"
            with open(friends_file, 'w', encoding='utf-8') as f:
                json.dump(friends, f, indent=2, ensure_ascii=False)
        
        if os.path.exists("hosted_users.json"):
            import shutil as _shutil
            _shutil.copy("hosted_users.json", f"{backup_folder}/hosted_users.json")
            print(f"[Backup] Saved hosted_users.json")

        zip_filename = f"{backup_folder}.zip"
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(backup_folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, backup_folder)
                    zipf.write(file_path, arcname)
        
        import shutil
        shutil.rmtree(backup_folder)
        
        print(f"[Backup] Full backup created: {zip_filename}")
        return zip_filename
    
    def list_backups(self):
        if not os.path.exists(self.backup_dir):
            return []
        
        backups = []
        for file in os.listdir(self.backup_dir):
            file_path = os.path.join(self.backup_dir, file)
            if os.path.isfile(file_path):
                size = os.path.getsize(file_path)
                modified = datetime.fromtimestamp(os.path.getmtime(file_path))
                backups.append({
                    "name": file,
                    "size": size,
                    "modified": modified,
                    "path": file_path
                })
        
        return sorted(backups, key=lambda x: x["modified"], reverse=True)
    
    def restore_backup(self, backup_name):
        backup_path = os.path.join(self.backup_dir, backup_name)
        
        if not os.path.exists(backup_path):
            return False
        
        with open(backup_path, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)
        
        print(f"[Backup] Restoring from {backup_name}...")
        
        if "user" in backup_data:
            print("[Backup] User data loaded")
        
        if "friends" in backup_data:
            print(f"[Backup] {len(backup_data['friends'])} friends loaded")
        
        if "guilds" in backup_data:
            print(f"[Backup] {len(backup_data['guilds'])} guilds loaded")
        
        return backup_data