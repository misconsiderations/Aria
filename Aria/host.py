import json
import time
import threading
import subprocess
import os
import sys
import shutil

HOSTED_USERS_FILE = "hosted_users.json"

class HostManager:
    def __init__(self):
        self.active_tokens = {}   # token_id -> runtime data
        self.processes = {}
        self.saved_users = {}     # token_id -> persisted settings
        self.lock = threading.Lock()
        self.hosting_enabled = True  # owner toggle — allows non-owners to use +host
        self._load_saved_users()
        # Removed: self._print_startup_summary()  <- This was causing duplicate loading

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_saved_users(self):
        try:
            if os.path.exists(HOSTED_USERS_FILE):
                with open(HOSTED_USERS_FILE, "r") as f:
                    self.saved_users = json.load(f)
        except Exception:
            self.saved_users = {}
    
    def print_loaded_users_summary(self):
        """
        Call this ONCE after all initialization is complete.
        This prevents duplicate user loading at startup.
        """
        total = len(self.saved_users)
        print(f"\033[1;36m[HOST]\033[0m Loaded hosted users: {total}")
        seen_users = set()  # Track which users we've printed to prevent duplicates
        
        for entry in self.saved_users.values():
            user_id = entry.get("user_id", "unknown")
            if user_id in seen_users:
                continue  # Skip duplicate users
            
            seen_users.add(user_id)
            username = entry.get("username") or "unknown"
            uid = entry.get("uid") or "unknown"
            owner = entry.get("owner") or "unknown"
            print(
                f"\033[1;36m[HOSTED USER]\033[0m user={username} | user_id={user_id} | uid={uid} | owner={owner}"
            )

    def _save_users(self):
        try:
            with open(HOSTED_USERS_FILE, "w") as f:
                json.dump(self.saved_users, f, indent=4)
        except Exception as e:
            print(f"Host save error: {e}")

    # ------------------------------------------------------------------

    def can_use_command(self, user_id):
        return True

    def host_token(self, owner_id, token_input, prefix="+", user_id=None, username=None):
        if not token_input:
            return False, "No token"

        token = self._clean_token(token_input)
        if not token:
            return False, "Bad token"

        with self.lock:
            for tid, data in self.active_tokens.items():
                if data["token"] == token:
                    return False, "Already hosted"

            config_file = f"hosted_{int(time.time())}.json"
            with open(config_file, "w") as f:
                json.dump({"token": token, "prefix": prefix}, f)

            process = self._run_their_bot(config_file, token)
            if not process:
                return False, "Start failed"

            token_id = str(int(time.time()))
            entry = {
                "uid": token_id,
                "user_id": user_id or "",
                "username": username or "",
                "token": token,
                "prefix": prefix,
                "owner": owner_id,
                "config": config_file,
            }
            self.active_tokens[token_id] = entry
            self.processes[token_id] = process

            # Persist (no process handle)
            self.saved_users[token_id] = {k: v for k, v in entry.items() if k != "config"}
            self._save_users()

            print(
                f"\033[1;36m[HOST]\033[0m Started hosting | user={entry['username'] or 'unknown'} "
                f"| user_id={entry['user_id'] or 'unknown'} | uid={entry['uid']} | owner={owner_id}"
            )

            return True, "Hosting token"
    
    def _clean_token(self, token_input):
        token_input = token_input.strip('"\' ')
        
        if token_input.startswith("{"):
            try:
                data = json.loads(token_input)
                return data.get("token", "")
            except:
                return token_input
        
        return token_input if "." in token_input else ""
    
    def _run_their_bot(self, config_file, token):
        try:
            runner_code = f"""
import sys, os, json, time, subprocess, shutil

temp_dir = "hosted_bot_{{int(time.time())}}"
os.makedirs(temp_dir, exist_ok=True)

for file in os.listdir("."):
    if file.endswith(".py"):
        shutil.copy(file, os.path.join(temp_dir, file))

os.chdir(temp_dir)

main_py_content = ""
with open("main.py", "r") as f:
    main_py_content = f.read()

lines = main_py_content.split('\\n')
new_lines = []

i = 0
while i < len(lines):
    line = lines[i]
    
    if line.strip().startswith('@bot.command(name="host"'):
        i += 2
        continue
    
    if line.strip().startswith('@bot.command(name="stophost"'):
        i += 2
        continue
    
    if line.strip().startswith('@bot.command(name="listhosted"'):
        i += 2
        continue
    
    new_lines.append(line)
    i += 1

with open("main.py", "w") as f:
    f.write('\\n'.join(new_lines))

with open("config.json", "w") as f:
    json.dump({{"token": "{token}", "prefix": ";"}}, f)

subprocess.run([sys.executable, "main.py"])
"""
            
            runner_file = f"runner_{int(time.time())}.py"
            with open(runner_file, "w") as f:
                f.write(runner_code)
            
            process = subprocess.Popen(
                [sys.executable, runner_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            threading.Thread(target=self._cleanup, args=(runner_file, config_file, process), daemon=True).start()
            return process
            
        except Exception as e:
            print(f"Host error: {e}")
            return None
    
    def stop_hosting(self, owner_id):
        with self.lock:
            to_stop = []
            for token_id, data in self.active_tokens.items():
                if data["owner"] == owner_id:
                    to_stop.append((token_id, data))
            
            for token_id, data in to_stop:
                if token_id in self.processes:
                    try:
                        self.processes[token_id].terminate()
                    except:
                        pass
                    del self.processes[token_id]
                del self.active_tokens[token_id]
                # Remove from persistent store
                self.saved_users.pop(token_id, None)
                print(
                    f"\033[1;36m[HOST]\033[0m Stopped hosting | user={data.get('username') or 'unknown'} "
                    f"| user_id={data.get('user_id') or 'unknown'} | uid={token_id} | owner={owner_id}"
                )
            self._save_users()

            if to_stop:
                return True, f"Stopped {len(to_stop)}"
            return False, "None"
    
    def stop_all(self):
        """Stop every hosted token regardless of owner."""
        with self.lock:
            count = len(self.active_tokens)
            for token_id in list(self.active_tokens.keys()):
                data = self.active_tokens[token_id]
                if token_id in self.processes:
                    try:
                        self.processes[token_id].terminate()
                    except:
                        pass
                    del self.processes[token_id]
                del self.active_tokens[token_id]
                self.saved_users.pop(token_id, None)
                print(
                    f"\033[1;36m[HOST]\033[0m Force-stopped | user={data.get('username') or 'unknown'} "
                    f"| user_id={data.get('user_id') or 'unknown'} | uid={token_id} | owner={data.get('owner') or 'unknown'}"
                )
            self._save_users()
            return count

    def list_hosted(self, requester_id):
        """Return only entries owned by requester_id."""
        with self.lock:
            return [v for v in self.saved_users.values() if v.get("owner") == requester_id]

    def list_all_hosted(self):
        """Return all saved hosted-user dicts (owner-only view)."""
        with self.lock:
            return list(self.saved_users.values())
    
    def _cleanup(self, runner_file, config_file, process):
        process.wait()
        try:
            if os.path.exists(runner_file):
                os.remove(runner_file)
            if os.path.exists(config_file):
                os.remove(config_file)
        except:
            pass
    
    def cleanup(self):
        with self.lock:
            for token_id in list(self.active_tokens.keys()):
                if token_id in self.processes:
                    try:
                        self.processes[token_id].terminate()
                    except:
                        pass
                del self.active_tokens[token_id]

host_manager = HostManager()
