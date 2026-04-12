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
        self._stop_events = {}    # token_id -> threading.Event for keepalive control
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
                    # Ensure UID is always present
                    for token_id, user_data in self.saved_users.items():
                        if "uid" not in user_data:
                            user_data["uid"] = "unknown"
        except Exception:
            self.saved_users = {}
    
    def print_loaded_users_summary(self):
        """
        Call this ONCE after all initialization is complete.
        This prevents duplicate user loading at startup.
        """
        total = len(self.saved_users)
        pass  # hosted user summary suppressed — hosted bots have their own logs

    def _save_users(self):
        try:
            with open(HOSTED_USERS_FILE, "w") as f:
                json.dump(self.saved_users, f, indent=4)
        except Exception as e:
            print(f"Host save error: {e}")

    # ------------------------------------------------------------------

    def can_use_command(self, user_id):
        """Hosted users can only manage their own tokens, not other users' tokens"""
        user_id = str(user_id)
        for entry in self.saved_users.values():
            if str(entry.get("owner")) == user_id:
                return True
        return False

    def is_token_owner(self, user_id, token_id):
        """Check if user owns this token"""
        token_id = str(token_id)
        user_id = str(user_id)
        if token_id in self.saved_users:
            return str(self.saved_users[token_id].get("owner")) == user_id
        return False

    def host_token(self, owner_id, token_input, prefix=";", user_id=None, username=None):
        if not token_input:
            return False, "No token"

        token = self._clean_token(token_input)
        if not token:
            return False, "Bad token"

        with self.lock:
            for tid, data in self.active_tokens.items():
                if data["token"] == token:
                    return False, "Already hosted"

            token_id = str(int(time.time() * 1000))
            config_file = f"hosted_{token_id}.json"
            with open(config_file, "w") as f:
                json.dump({"token": token, "prefix": prefix}, f)

            process = self._run_their_bot(
                config_file,
                token,
                prefix=prefix,
                hosted_uid=token_id,
                owner_id=owner_id,
                user_id=user_id,
                username=username,
            )
            if not process:
                return False, "Start failed"

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

            pass  # hosted bot start suppressed — output goes to hosted log

        self._start_keepalive(token_id)
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
    
    def _run_their_bot(self, config_file, token, prefix=";", hosted_uid=None, owner_id=None, user_id=None, username=None):
        try:
            runner_code = f"""
import sys, os, json, time, subprocess, shutil

temp_dir = "hosted_bot_{hosted_uid}"
first_run = not os.path.exists(temp_dir)
os.makedirs(temp_dir, exist_ok=True)

if first_run:
    # First launch: copy everything and write fresh config
    for file in os.listdir("."):
        if file.endswith(".py") or file.endswith(".json"):
            try:
                shutil.copy(file, os.path.join(temp_dir, file))
            except Exception:
                pass
    with open(os.path.join(temp_dir, "config.json"), "w") as f:
        json.dump({{"token": "{token}", "prefix": "{prefix}"}}, f)
else:
    # Restart: refresh .py files only — preserve .json files so saved prefix persists
    for file in os.listdir("."):
        if file.endswith(".py"):
            try:
                shutil.copy(file, os.path.join(temp_dir, file))
            except Exception:
                pass

os.chdir(temp_dir)

env = os.environ.copy()
env["HOSTED_TOKEN"] = "true"
env["HOSTED_UID"] = {hosted_uid!r}
env["HOSTED_OWNER_ID"] = {owner_id!r}
env["HOSTED_USER_ID"] = {user_id!r}
env["HOSTED_USERNAME"] = {username!r}

subprocess.run([sys.executable, "main.py"], env=env)
"""
            # Fixed runner filename per token so keepalive restarts work cleanly
            runner_file = f"runner_{hosted_uid}.py"
            with open(runner_file, "w") as f:
                f.write(runner_code)

            # Each hosted bot writes to its own log — keeps main console clean
            log_dir = "hosted_logs"
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, f"hosted_{hosted_uid}.log")
            log_file = open(log_path, "a")

            process = subprocess.Popen(
                [sys.executable, runner_file],
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            log_file.close()  # parent closes; child keeps its own fd copy
            return process

        except Exception as e:
            print(f"Host error: {e}")
            return None

    def _start_keepalive(self, token_id):
        """Spawn a daemon watchdog that auto-restarts a hosted bot when it crashes."""
        stop_event = threading.Event()
        self._stop_events[token_id] = stop_event

        def _monitor():
            restart_count = 0
            while not stop_event.is_set():
                time.sleep(5)
                if stop_event.is_set():
                    break

                with self.lock:
                    process = self.processes.get(token_id)
                if process is None:
                    break

                ret = process.poll()
                if ret is None:
                    # Still running — nothing to do
                    continue

                # Process exited
                if stop_event.is_set():
                    break

                restart_count += 1
                with self.lock:
                    saved = self.saved_users.get(token_id, {})
                uname = saved.get("username") or "unknown"
                uid = saved.get("uid") or token_id
                pass  # keepalive restart suppressed — output goes to hosted log
                time.sleep(5)
                if stop_event.is_set():
                    break

                with self.lock:
                    saved = self.saved_users.get(token_id)
                if not saved:
                    break
                token = saved.get("token")
                if not token:
                    break

                new_process = self._run_their_bot(
                    f"hosted_{token_id}.json",
                    token,
                    prefix=saved.get("prefix", ";"),
                    hosted_uid=token_id,
                    owner_id=saved.get("owner"),
                    user_id=saved.get("user_id"),
                    username=saved.get("username"),
                )
                if new_process and not stop_event.is_set():
                    with self.lock:
                        self.processes[token_id] = new_process
                else:
                    break  # failed to restart — give up silently

        threading.Thread(target=_monitor, daemon=True, name=f"keepalive-{token_id}").start()
    
    def stop_hosting(self, owner_id):
        with self.lock:
            to_stop = []
            for token_id, data in self.active_tokens.items():
                if str(data["owner"]) == str(owner_id):
                    to_stop.append((token_id, data))
            
            for token_id, data in to_stop:
                stop_event = self._stop_events.pop(token_id, None)
                if stop_event:
                    stop_event.set()
                if token_id in self.processes:
                    try:
                        self.processes[token_id].terminate()
                    except:
                        pass
                    del self.processes[token_id]
                del self.active_tokens[token_id]
                # Remove from persistent store
                self.saved_users.pop(token_id, None)
                pass  # stop suppressed — hosted bots have their own logs
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
                stop_event = self._stop_events.pop(token_id, None)
                if stop_event:
                    stop_event.set()
                if token_id in self.processes:
                    try:
                        self.processes[token_id].terminate()
                    except:
                        pass
                    del self.processes[token_id]
                del self.active_tokens[token_id]
                self.saved_users.pop(token_id, None)
                pass  # force-stop suppressed
            self._save_users()
            return count

    def list_hosted(self, requester_id):
        """Return only entries owned by requester_id."""
        with self.lock:
            requester_id = str(requester_id)
            return [v for v in self.saved_users.values() if str(v.get("owner")) == requester_id]

    def list_hosted_entries(self, requester_id=None):
        """Return sorted (token_id, entry) pairs, optionally filtered by owner."""
        with self.lock:
            entries = []
            for token_id, data in self.saved_users.items():
                if requester_id is not None and str(data.get("owner")) != str(requester_id):
                    continue
                entry = data.copy()
                entry.setdefault("uid", token_id)
                entry["token_id"] = token_id
                entries.append((token_id, entry))

        entries.sort(key=lambda item: (
            str(item[1].get("username") or "").lower(),
            str(item[1].get("user_id") or ""),
            str(item[1].get("uid") or item[0]),
        ))
        return entries

    def remove_hosts(self, requester_id=None, selectors=None, all_hosts=False):
        """Remove hosted entries by index, uid, token_id, or user_id."""
        scoped_entries = self.list_hosted_entries(None if all_hosts else requester_id)
        if not scoped_entries:
            return 0

        selector_values = [str(sel).strip() for sel in (selectors or []) if str(sel).strip()]
        selected_ids = []

        if selector_values:
            for selector in selector_values:
                matched = False
                if selector.isdigit():
                    index = int(selector) - 1
                    if 0 <= index < len(scoped_entries):
                        selected_ids.append(scoped_entries[index][0])
                        matched = True
                if matched:
                    continue

                for token_id, entry in scoped_entries:
                    if selector in {
                        str(token_id),
                        str(entry.get("uid") or ""),
                        str(entry.get("user_id") or ""),
                    }:
                        selected_ids.append(token_id)
                        matched = True
                if matched:
                    continue
        else:
            selected_ids = [token_id for token_id, _ in scoped_entries]

        removed = 0
        with self.lock:
            for token_id in list(dict.fromkeys(selected_ids)):
                data = self.saved_users.get(token_id)
                if not data:
                    continue
                stop_event = self._stop_events.pop(token_id, None)
                if stop_event:
                    stop_event.set()
                proc = self.processes.pop(token_id, None)
                if proc:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                self.active_tokens.pop(token_id, None)
                self.saved_users.pop(token_id, None)
                removed += 1
            self._save_users()

        return removed

    def list_all_hosted(self):
        """Return all saved hosted-user dicts (owner-only view)."""
        with self.lock:
            return list(self.saved_users.values())

    def restore_hosted_users(self):
        """Restart persisted hosted users on startup in the main controller process."""
        with self.lock:
            saved_entries = [(token_id, data.copy()) for token_id, data in self.saved_users.items()]

        restored = 0

        for token_id, data in saved_entries:
            token = data.get("token")
            if not self._is_token_valid(token):
                continue

            with self.lock:
                if token_id in self.active_tokens:
                    continue

            prefix = data.get("prefix", ";")
            config_file = f"hosted_{token_id}.json"
            process = self._run_their_bot(
                config_file,
                token,
                prefix=prefix,
                hosted_uid=data.get("uid") or token_id,
                owner_id=data.get("owner"),
                user_id=data.get("user_id"),
                username=data.get("username"),
            )
            if not process:
                continue

            entry = {
                "uid": data.get("uid") or token_id,
                "user_id": data.get("user_id", ""),
                "username": data.get("username", ""),
                "token": token,
                "prefix": prefix,
                "owner": data.get("owner", ""),
                "config": config_file,
            }

            with self.lock:
                self.active_tokens[token_id] = entry
                self.processes[token_id] = process

            self._start_keepalive(token_id)
            restored += 1

        if restored:
            pass  # restore count suppressed

        return restored
    
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
                stop_event = self._stop_events.pop(token_id, None)
                if stop_event:
                    stop_event.set()
                if token_id in self.processes:
                    try:
                        self.processes[token_id].terminate()
                    except:
                        pass
                    self.processes.pop(token_id, None)
                del self.active_tokens[token_id]

    def _remove_invalid_users(self):
        """Remove users with invalid tokens from the hosted list."""
        with self.lock:
            invalid_users = [tid for tid, data in self.saved_users.items() if not self._is_token_valid(data.get("token"))]
            for tid in invalid_users:
                del self.saved_users[tid]
            self._save_users()

    def _is_token_valid(self, token):
        """Check if a token is valid."""
        return token and len(token) > 10  # Example validation logic

    def rehost_user(self, user_id, username, uid):
        """Re-add a user to the hosted list if rehosted."""
        with self.lock:
            if user_id not in self.saved_users:
                self.saved_users[user_id] = {
                    "username": username,
                    "uid": uid,
                    "owner": user_id
                }
                self._save_users()

host_manager = HostManager()
