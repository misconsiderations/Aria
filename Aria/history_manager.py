import json
import time
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from api_client import DiscordAPIClient
from mongo_store import get_mongo_store

class CircuitBreaker:
    """Circuit breaker pattern to prevent repeated failures"""
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half-open
    
    def call(self, func, *args, **kwargs):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
            else:
                raise Exception("Circuit breaker is open")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e
    
    def _on_success(self):
        self.failure_count = 0
        self.state = "closed"
    
    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"

class HistoryManager:
    def __init__(self, api_client: DiscordAPIClient):
        self.api = api_client
        self.history_file = "history_data.json"
        self.backup_file = "history_data_backup.json"
        self._store = get_mongo_store()
        self._store_key = "history_data"
        self.profiles: Dict[str, List[Dict]] = {}  # user_id -> list of profile snapshots
        self.servers: Dict[str, List[Dict]] = {}   # server_id -> list of server snapshots
        self.users_to_scrape: set = set()          # user IDs queued for profile scraping
        self.recent_users: set = set()             # recently seen user IDs from gateway messages
        self.scraping_interval = 3600  # 1 hour default
        self.scraping_thread = None
        self.scraping_active = False
        
        # Circuit breakers for different operations
        self.api_circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        self.scrape_circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=300)
        
        # Health monitoring
        self.last_successful_api_call = time.time()
        self.consecutive_failures = 0
        self.max_consecutive_failures = 10
        
        # Data validation and cleanup
        self.max_profiles_per_user = 10
        self.max_servers_per_guild = 5
        self.max_recent_users = 10000  # Prevent memory bloat
        self.member_profile_cache: Dict[str, Dict[str, Any]] = {}
        self.member_failure_log_ts: Dict[str, float] = {}
        self.user_guild_index: Dict[str, Set[str]] = defaultdict(set)
        self.connected_accounts: Dict[str, Dict[str, Any]] = {}
        self._save_lock = threading.Lock()
        
        self.load_history()

    def _apply_loaded_history(self, data: Dict[str, Any]) -> bool:
        if not isinstance(data, dict):
            return False

        self.profiles = data.get('profiles', {})
        self.servers = data.get('servers', {})
        self.users_to_scrape = set(data.get('users_to_scrape', []))
        self.recent_users = set(data.get('recent_users', []))
        self.user_guild_index = defaultdict(
            set,
            {
                user_id: {
                    guild_id
                    for guild_id in guild_ids
                    if isinstance(guild_id, str) and guild_id.isdigit()
                }
                for user_id, guild_ids in data.get('user_guild_index', {}).items()
                if isinstance(user_id, str) and user_id.isdigit() and isinstance(guild_ids, list)
            }
        )
        connected_accounts = data.get('connected_accounts', {})
        self.connected_accounts = connected_accounts if isinstance(connected_accounts, dict) else {}
        self._validate_and_clean_data()
        return True

    def load_history(self):
        """Load historical data from file with validation and backup recovery"""
        try:
            mongo_data = self._store.load_document(self._store_key, None)
            if self._apply_loaded_history(mongo_data):
                return

            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Validate data structure
                if not self._apply_loaded_history(data):
                    raise ValueError("Invalid data structure")
                    
        except Exception as e:
            print(f"[History] Error loading history: {e}, attempting backup recovery")
            self._recover_from_backup()
            
        # Ensure we have valid data structures
        if not isinstance(self.profiles, dict):
            self.profiles = {}
        if not isinstance(self.servers, dict):
            self.servers = {}
        if not isinstance(self.users_to_scrape, set):
            self.users_to_scrape = set()
        if not isinstance(self.recent_users, set):
            self.recent_users = set()
        if not isinstance(self.user_guild_index, defaultdict):
            self.user_guild_index = defaultdict(set)

    def _validate_and_clean_data(self):
        """Validate and clean historical data"""
        # Clean profiles
        valid_profiles = {}
        for user_id, snapshots in self.profiles.items():
            if isinstance(snapshots, list) and len(snapshots) > 0:
                # Keep only valid snapshots and limit count
                valid_snapshots = [s for s in snapshots if isinstance(s, dict) and 'timestamp' in s]
                valid_snapshots.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                valid_profiles[user_id] = valid_snapshots[:self.max_profiles_per_user]
        self.profiles = valid_profiles
        
        # Clean servers
        valid_servers = {}
        for server_id, snapshots in self.servers.items():
            if isinstance(snapshots, list) and len(snapshots) > 0:
                valid_snapshots = [s for s in snapshots if isinstance(s, dict) and 'timestamp' in s]
                valid_snapshots.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                valid_servers[server_id] = valid_snapshots[:self.max_servers_per_guild]
        self.servers = valid_servers
        
        # Clean user sets
        self.users_to_scrape = {uid for uid in self.users_to_scrape if isinstance(uid, str) and uid.isdigit()}
        self.recent_users = {uid for uid in self.recent_users if isinstance(uid, str) and uid.isdigit()}
        self.user_guild_index = defaultdict(
            set,
            {
                user_id: {
                    guild_id
                    for guild_id in guild_ids
                    if isinstance(guild_id, str) and guild_id.isdigit()
                }
                for user_id, guild_ids in self.user_guild_index.items()
                if isinstance(user_id, str) and user_id.isdigit() and isinstance(guild_ids, (set, list, tuple))
            }
        )
        self.connected_accounts = {
            user_id: snapshot
            for user_id, snapshot in self.connected_accounts.items()
            if isinstance(user_id, str) and user_id.isdigit() and isinstance(snapshot, dict)
        }
        
        # Limit recent users to prevent memory bloat
        if len(self.recent_users) > self.max_recent_users:
            self.recent_users = set(list(self.recent_users)[:self.max_recent_users])

    def _recover_from_backup(self):
        """Recover from backup file if main file is corrupted"""
        try:
            if os.path.exists(self.backup_file):
                with open(self.backup_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if self._apply_loaded_history(data):
                    print("[History] Successfully recovered from backup")
                    return
            else:
                print("[History] No backup available, starting fresh")
        except Exception as e:
            print(f"[History] Backup recovery failed: {e}, starting fresh")
        
        # Reset to empty state
        self.profiles = {}
        self.servers = {}
        self.users_to_scrape = set()
        self.recent_users = set()
        self.user_guild_index = defaultdict(set)
        self.connected_accounts = {}

    def save_history(self):
        """Save historical data to file with backup and atomic writes"""
        with self._save_lock:
            try:
                data = {
                    'profiles': self.profiles,
                    'servers': self.servers,
                    'users_to_scrape': list(self.users_to_scrape),
                    'recent_users': list(self.recent_users),
                    'user_guild_index': {
                        user_id: sorted(guild_ids)
                        for user_id, guild_ids in self.user_guild_index.items()
                        if guild_ids
                    },
                    'connected_accounts': self.connected_accounts,
                    'last_updated': time.time(),
                    'version': '2.0'  # For future compatibility
                }

                if self._store.save_document(self._store_key, data):
                    return
                
                # Create backup of current file
                if os.path.exists(self.history_file):
                    import shutil
                    shutil.copy2(self.history_file, self.backup_file)
                
                # Atomic write using a unique temp file to avoid concurrent save collisions.
                temp_file = f"{self.history_file}.{threading.get_ident()}.tmp"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False, default=str)
                
                # Atomic move
                os.replace(temp_file, self.history_file)
                
            except Exception as e:
                print(f"[History] Error saving history: {e}")
                # Try to restore from backup
                if os.path.exists(self.backup_file):
                    try:
                        os.replace(self.backup_file, self.history_file)
                        print("[History] Restored from backup after save failure")
                    except Exception as restore_e:
                        print(f"[History] Backup restore failed: {restore_e}")

    def _should_log_member_failure(self, server_id: str, cooldown_seconds: int = 3600) -> bool:
        """Rate-limit repeated member-list failure logs per server."""
        now = time.time()
        last = self.member_failure_log_ts.get(server_id, 0)
        if now - last >= cooldown_seconds:
            self.member_failure_log_ts[server_id] = now
            return True
        return False

    def is_healthy(self) -> bool:
        """Check if the history system is healthy"""
        try:
            # Check the active persistence backend.
            if self._store.enabled:
                if self._store.load_document(self._store_key, None) is None and self._store.last_error:
                    return False
            elif not os.access(os.path.dirname(self.history_file) or '.', os.W_OK):
                return False
            
            # Check if API is responsive (within last 5 minutes)
            if time.time() - self.last_successful_api_call > 300:
                return False
            
            # Check if we haven't had too many consecutive failures
            if self.consecutive_failures > self.max_consecutive_failures:
                return False
            
            # Check data integrity
            if not isinstance(self.profiles, dict) or not isinstance(self.servers, dict):
                return False
            if not isinstance(self.user_guild_index, defaultdict):
                return False
            
            return True
            
        except Exception:
            return False

    def perform_health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check"""
        health_status = {
            'healthy': True,
            'issues': [],
            'metrics': {
                'profiles_count': len(self.profiles),
                'servers_count': len(self.servers),
                'queued_users': len(self.users_to_scrape),
                'recent_users': len(self.recent_users),
                'last_api_call': time.time() - self.last_successful_api_call,
                'consecutive_failures': self.consecutive_failures
            }
        }
        
        # Check active storage backend access.
        if self._store.enabled:
            if self._store.load_document(self._store_key, None) is None and self._store.last_error:
                health_status['issues'].append(f"MongoDB access failed: {self._store.last_error}")
                health_status['healthy'] = False
        else:
            try:
                with open(self.history_file + '.health', 'w') as f:
                    f.write('test')
                os.remove(self.history_file + '.health')
            except Exception as e:
                health_status['issues'].append(f"File system access failed: {e}")
                health_status['healthy'] = False
        
        # Check API connectivity
        if time.time() - self.last_successful_api_call > 300:
            health_status['issues'].append("API not responsive for 5+ minutes")
            health_status['healthy'] = False
        
        # Check for excessive failures
        if self.consecutive_failures > self.max_consecutive_failures:
            health_status['issues'].append(f"Too many consecutive failures: {self.consecutive_failures}")
            health_status['healthy'] = False
        
        # Check data integrity
        try:
            self._validate_and_clean_data()
        except Exception as e:
            health_status['issues'].append(f"Data validation failed: {e}")
            health_status['healthy'] = False
        
        return health_status

    def collect_recent_user(self, message_data: Dict[str, Any]):
        """Collect user ID from a gateway message for later scraping."""
        try:
            author = message_data.get("author", {})
            user_id = author.get("id")
            if user_id and user_id != self.api.user_id:
                self.recent_users.add(user_id)
        except Exception as e:
            print(f"[History] Error collecting user from message: {e}")

    def _safe_api_call(self, method: str, endpoint: str, **kwargs) -> Optional[Any]:
        """Make API calls with circuit breaker and error handling"""
        try:
            result = self.api_circuit_breaker.call(self.api.request, method, endpoint, **kwargs)
            if result and result.status_code in [200, 201, 204]:
                self.last_successful_api_call = time.time()
                self.consecutive_failures = 0
                return result
            else:
                self.consecutive_failures += 1
                return None
        except Exception as e:
            self.consecutive_failures += 1
            print(f"[History] API call failed ({method} {endpoint}): {e}")
            return None

    def _safe_json_parse(self, response) -> Optional[Any]:
        """Safely parse JSON response"""
        try:
            if response and hasattr(response, 'json'):
                return response.json()
        except Exception as e:
            print(f"[History] JSON parse error: {e}")
        return None

    def get_recent_users(self, clear_after: bool = True) -> set:
        """Get recently seen user IDs from gateway messages"""
        users = self.recent_users.copy()
        if clear_after:
            self.recent_users.clear()
        return users

    def _extract_connection_summary(self, connected_accounts: Any) -> List[Dict[str, Any]]:
        """Return a stable subset of connected account metadata."""
        if not isinstance(connected_accounts, list):
            return []

        summary = []
        for account in connected_accounts:
            if not isinstance(account, dict):
                continue
            summary.append({
                'type': account.get('type'),
                'name': account.get('name'),
                'id': account.get('id'),
                'verified': account.get('verified'),
                'visibility': account.get('visibility')
            })
        return summary

    def _extract_badges(self, profile_payload: Dict[str, Any]) -> List[Any]:
        """Extract badge identifiers from the richer profile payload."""
        badges = profile_payload.get('badges', [])
        if isinstance(badges, list):
            return [badge.get('id', badge) if isinstance(badge, dict) else badge for badge in badges]
        return []

    def _merge_profile_snapshot(
        self,
        user_id: str,
        basic_user: Optional[Dict[str, Any]],
        profile_payload: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Combine core user data, rich profile data, and cached guild member context."""
        cached = self.member_profile_cache.get(user_id, {})
        latest = self.profiles.get(user_id, [])[-1] if self.profiles.get(user_id) else {}
        payload_user = profile_payload.get('user', {}) if isinstance(profile_payload, dict) else {}
        user_profile = profile_payload.get('user_profile', {}) if isinstance(profile_payload, dict) else {}
        guild_member = profile_payload.get('guild_member', {}) if isinstance(profile_payload, dict) else {}
        guild_member_profile = profile_payload.get('guild_member_profile', {}) if isinstance(profile_payload, dict) else {}
        mutual_guilds = profile_payload.get('mutual_guilds', []) if isinstance(profile_payload, dict) else []

        source_guild_ids = sorted(set(self.user_guild_index.get(user_id, set())))
        mutual_guild_count = len(mutual_guilds) if isinstance(mutual_guilds, list) else 0

        return {
            'timestamp': time.time(),
            'user_id': user_id,
            'username': payload_user.get('username') or (basic_user or {}).get('username') or cached.get('username') or latest.get('username') or f"user_{user_id[-4:]}",
            'legacy_username': profile_payload.get('legacy_username') if isinstance(profile_payload, dict) else latest.get('legacy_username'),
            'global_name': payload_user.get('global_name') or (basic_user or {}).get('global_name') or user_profile.get('global_name') or cached.get('global_name') or latest.get('global_name'),
            'discriminator': payload_user.get('discriminator') or (basic_user or {}).get('discriminator') or cached.get('discriminator') or latest.get('discriminator', '0000'),
            'avatar': payload_user.get('avatar') or (basic_user or {}).get('avatar') or cached.get('avatar') or latest.get('avatar'),
            'banner': user_profile.get('banner') or payload_user.get('banner') or (basic_user or {}).get('banner') or latest.get('banner'),
            'accent_color': user_profile.get('accent_color') or payload_user.get('accent_color') or (basic_user or {}).get('accent_color') or latest.get('accent_color'),
            'public_flags': payload_user.get('public_flags') or (basic_user or {}).get('public_flags') or latest.get('public_flags'),
            'flags': payload_user.get('flags') or (basic_user or {}).get('flags') or latest.get('flags'),
            'bot': payload_user.get('bot', (basic_user or {}).get('bot', cached.get('bot', latest.get('bot', False)))),
            'system': payload_user.get('system', (basic_user or {}).get('system', latest.get('system', False))),
            'mfa_enabled': (basic_user or {}).get('mfa_enabled', latest.get('mfa_enabled')),
            'verified': (basic_user or {}).get('verified', latest.get('verified')),
            'email': (basic_user or {}).get('email', latest.get('email')),
            'locale': (basic_user or {}).get('locale', latest.get('locale')),
            'premium_type': (basic_user or {}).get('premium_type', latest.get('premium_type')),
            'bio': user_profile.get('bio') or latest.get('bio'),
            'pronouns': user_profile.get('pronouns') or latest.get('pronouns'),
            'connected_accounts': self._extract_connection_summary(profile_payload.get('connected_accounts', [])) if isinstance(profile_payload, dict) else latest.get('connected_accounts', []),
            'badges': self._extract_badges(profile_payload) if isinstance(profile_payload, dict) else latest.get('badges', []),
            'mutual_guild_count': mutual_guild_count,
            'mutual_friend_count': profile_payload.get('mutual_friends_count') if isinstance(profile_payload, dict) else latest.get('mutual_friend_count'),
            'guild_bio': guild_member_profile.get('bio') or cached.get('guild_bio') or latest.get('guild_bio'),
            'guild_pronouns': guild_member_profile.get('pronouns') or cached.get('guild_pronouns') or latest.get('guild_pronouns'),
            'nick': guild_member.get('nick') or cached.get('nick') or latest.get('nick'),
            'roles': guild_member.get('roles') or cached.get('roles') or latest.get('roles', []),
            'joined_at': guild_member.get('joined_at') or cached.get('joined_at') or latest.get('joined_at'),
            'premium_since': guild_member.get('premium_since') or cached.get('premium_since') or latest.get('premium_since'),
            'guild_avatar': guild_member.get('avatar') or cached.get('guild_avatar') or latest.get('guild_avatar'),
            'guild_banner': guild_member_profile.get('banner') or cached.get('guild_banner') or latest.get('guild_banner'),
            'source_guild_ids': source_guild_ids,
        }

    def _get_basic_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Fetch core user metadata when available."""
        response = self._safe_api_call("GET", f"/users/{user_id}")
        if not response or response.status_code != 200:
            return None
        data = self._safe_json_parse(response)
        return data if isinstance(data, dict) else None

    def _get_rich_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the richer profile payload used elsewhere in the bot."""
        response = self._safe_api_call("GET", f"/users/{user_id}/profile")
        if not response or response.status_code != 200:
            return None
        data = self._safe_json_parse(response)
        return data if isinstance(data, dict) else None

    def can_read_channel_messages(self, channel_id: str) -> bool:
        """Check if the bot can read messages in a channel by attempting a minimal request"""
        try:
            # Try to get just 1 message to check permissions
            response = self._safe_api_call("GET", f"/channels/{channel_id}/messages?limit=1")
            return response is not None and response.status_code == 200
        except Exception:
            return False

    def collect_user_ids_from_messages(self, channel_id: str, limit: int = 100) -> set:
        """Collect user IDs from recent messages in a channel with robust error handling"""
        user_ids = set()
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                response = self._safe_api_call("GET", f"/channels/{channel_id}/messages?limit={limit}")
                if response and response.status_code == 200:
                    data = self._safe_json_parse(response)
                    if data and isinstance(data, list):
                        for message in data:
                            if isinstance(message, dict):
                                author = message.get("author", {})
                                user_id = author.get("id")
                                if user_id and isinstance(user_id, str) and user_id.isdigit():
                                    user_ids.add(user_id)
                        
                        print(f"[History] Collected {len(user_ids)} user IDs from channel {channel_id}")
                        return user_ids
                
                # If we get here, the request failed
                status_code = response.status_code if response else "No response"
                if status_code == 403:
                    print(f"[History] Access denied to channel {channel_id} - skipping")
                    return set()  # Don't retry on permission errors
                elif status_code == 404:
                    print(f"[History] Channel {channel_id} not found - skipping")
                    return set()
                elif attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    print(f"[History] Retrying channel {channel_id} in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    print(f"[History] Failed to access channel {channel_id} after {max_retries} attempts")
                    return set()
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[History] Error accessing channel {channel_id}, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    print(f"[History] Final error accessing channel {channel_id}: {e}")
                    return set()
        
        return user_ids

    def scrape_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Scrape a user's profile information with robust error handling"""
        if not user_id or not isinstance(user_id, str) or not user_id.isdigit():
            return None
            
        try:
            basic_user = self._get_basic_user(user_id)
            rich_profile = self._get_rich_profile(user_id)

            if not basic_user and not rich_profile:
                return self._build_fallback_profile(user_id)

            profile_snapshot = self._merge_profile_snapshot(user_id, basic_user, rich_profile)
            
            # Validate required fields
            if not profile_snapshot.get('username'):
                return self._build_fallback_profile(user_id)
            
            print(f"[History] Successfully scraped profile for {profile_snapshot.get('username', 'Unknown')}#{profile_snapshot.get('discriminator', '0000')}")
            return profile_snapshot

        except Exception as e:
            print(f"[History] Error scraping profile for user {user_id}: {e}")
            return self._build_fallback_profile(user_id)

    def _build_fallback_profile(self, user_id: str) -> Dict[str, Any]:
        """Build a minimal profile snapshot when full user profile access is unavailable."""
        cached = self.member_profile_cache.get(user_id, {})
        existing = self.profiles.get(user_id, [])
        latest = existing[-1] if existing else {}
        return {
            'timestamp': time.time(),
            'user_id': user_id,
            'username': cached.get('username') or latest.get('username') or f"user_{user_id[-4:]}",
            'global_name': cached.get('global_name') or latest.get('global_name'),
            'discriminator': cached.get('discriminator') or latest.get('discriminator', '0000'),
            'avatar': cached.get('avatar') or latest.get('avatar'),
            'banner': latest.get('banner'),
            'accent_color': latest.get('accent_color'),
            'public_flags': latest.get('public_flags'),
            'flags': latest.get('flags'),
            'bot': cached.get('bot', latest.get('bot', False)),
            'system': latest.get('system', False),
            'mfa_enabled': latest.get('mfa_enabled'),
            'verified': latest.get('verified'),
            'email': latest.get('email'),
            'locale': latest.get('locale'),
            'premium_type': latest.get('premium_type'),
            'bio': latest.get('bio'),
            'pronouns': latest.get('pronouns'),
            'connected_accounts': latest.get('connected_accounts', []),
            'badges': latest.get('badges', []),
            'mutual_guild_count': latest.get('mutual_guild_count', len(self.user_guild_index.get(user_id, set()))),
            'mutual_friend_count': latest.get('mutual_friend_count'),
            'guild_bio': cached.get('guild_bio') or latest.get('guild_bio'),
            'guild_pronouns': cached.get('guild_pronouns') or latest.get('guild_pronouns'),
            'nick': cached.get('nick') or latest.get('nick'),
            'roles': cached.get('roles') or latest.get('roles', []),
            'joined_at': cached.get('joined_at') or latest.get('joined_at'),
            'premium_since': cached.get('premium_since') or latest.get('premium_since'),
            'guild_avatar': cached.get('guild_avatar') or latest.get('guild_avatar'),
            'guild_banner': cached.get('guild_banner') or latest.get('guild_banner'),
            'source_guild_ids': sorted(set(self.user_guild_index.get(user_id, set()))) or latest.get('source_guild_ids', [])
        }

    def scrape_server_data(self, server_id: str) -> Optional[Dict[str, Any]]:
        """Scrape a server's information"""
        try:
            # Get server details
            server_response = self.api.request("GET", f"/guilds/{server_id}")
            if not server_response or server_response.status_code != 200:
                return None

            server_data = server_response.json()

            # Get server member count (approximate)
            members_response = self.api.request("GET", f"/guilds/{server_id}/preview")
            member_count = None
            if members_response and members_response.status_code == 200:
                preview_data = members_response.json()
                member_count = preview_data.get('approximate_member_count')

            # Get channels
            channels_response = self.api.request("GET", f"/guilds/{server_id}/channels")
            channels = []
            if channels_response and channels_response.status_code == 200:
                channels_data = channels_response.json()
                channels = [{
                    'id': ch.get('id'),
                    'name': ch.get('name'),
                    'type': ch.get('type'),
                    'position': ch.get('position'),
                    'parent_id': ch.get('parent_id')
                } for ch in channels_data]

            # Get roles
            roles_response = self.api.request("GET", f"/guilds/{server_id}/roles")
            roles = []
            if roles_response and roles_response.status_code == 200:
                roles_data = roles_response.json()
                roles = [{
                    'id': r.get('id'),
                    'name': r.get('name'),
                    'color': r.get('color'),
                    'position': r.get('position'),
                    'permissions': r.get('permissions'),
                    'managed': r.get('managed'),
                    'mentionable': r.get('mentionable')
                } for r in roles_data]

            server_snapshot = {
                'timestamp': time.time(),
                'server_id': server_id,
                'name': server_data.get('name'),
                'icon': server_data.get('icon'),
                'banner': server_data.get('banner'),
                'splash': server_data.get('splash'),
                'discovery_splash': server_data.get('discovery_splash'),
                'owner_id': server_data.get('owner_id'),
                'region': server_data.get('region'),
                'afk_channel_id': server_data.get('afk_channel_id'),
                'afk_timeout': server_data.get('afk_timeout'),
                'verification_level': server_data.get('verification_level'),
                'default_message_notifications': server_data.get('default_message_notifications'),
                'explicit_content_filter': server_data.get('explicit_content_filter'),
                'features': server_data.get('features', []),
                'mfa_level': server_data.get('mfa_level'),
                'application_id': server_data.get('application_id'),
                'system_channel_id': server_data.get('system_channel_id'),
                'system_channel_flags': server_data.get('system_channel_flags'),
                'rules_channel_id': server_data.get('rules_channel_id'),
                'vanity_url_code': server_data.get('vanity_url_code'),
                'description': server_data.get('description'),
                'premium_tier': server_data.get('premium_tier'),
                'premium_subscription_count': server_data.get('premium_subscription_count'),
                'preferred_locale': server_data.get('preferred_locale'),
                'public_updates_channel_id': server_data.get('public_updates_channel_id'),
                'max_video_channel_users': server_data.get('max_video_channel_users'),
                'approximate_member_count': member_count,
                'channels': channels,
                'roles': roles
            }

            return server_snapshot

        except Exception as e:
            print(f"Error scraping server {server_id}: {e}")
            return None

    def add_profile_snapshot(self, user_id: str, profile_data: Dict[str, Any]):
        """Add a profile snapshot to history"""
        if user_id not in self.profiles:
            self.profiles[user_id] = []

        # Keep only last 10 snapshots per user to prevent file bloat
        self.profiles[user_id].append(profile_data)
        if len(self.profiles[user_id]) > 10:
            self.profiles[user_id] = self.profiles[user_id][-10:]

        self.save_history()

    def add_server_snapshot(self, server_id: str, server_data: Dict[str, Any]):
        """Add a server snapshot to history"""
        if server_id not in self.servers:
            self.servers[server_id] = []

        # Keep only last 5 snapshots per server
        self.servers[server_id].append(server_data)
        if len(self.servers[server_id]) > 5:
            self.servers[server_id] = self.servers[server_id][-5:]

        self.save_history()

    def record_connected_account_ids(
        self,
        token_user_id: str,
        friend_user_ids: List[str],
        permitted_guild_ids: List[str],
    ):
        """Store ID-only connected account history without triggering richer profile/guild scrapes."""
        if not token_user_id or not str(token_user_id).isdigit():
            return

        clean_friend_ids = sorted({str(user_id) for user_id in friend_user_ids if str(user_id).isdigit()})
        clean_guild_ids = sorted({str(guild_id) for guild_id in permitted_guild_ids if str(guild_id).isdigit()})
        self.connected_accounts[str(token_user_id)] = {
            'timestamp': time.time(),
            'user_id': str(token_user_id),
            'friend_user_ids': clean_friend_ids,
            'permitted_guild_ids': clean_guild_ids,
        }
        self.save_history()

    def get_connected_account_ids(self, token_user_id: str) -> Dict[str, Any]:
        return self.connected_accounts.get(str(token_user_id), {})

    def get_user_history(self, user_id: str) -> List[Dict[str, Any]]:
        """Get historical profile data for a user"""
        return self.profiles.get(user_id, [])

    def get_server_history(self, server_id: str) -> List[Dict[str, Any]]:
        """Get historical data for a server"""
        return self.servers.get(server_id, [])

    def scrape_all_guild_members(self, server_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """Scrape member information from a server with robust error handling"""
        members = []
        if not server_id or not isinstance(server_id, str) or not server_id.isdigit():
            return members
            
        try:
            after = None
            while len(members) < limit:
                params = {'limit': min(1000, limit - len(members))}
                if after:
                    params['after'] = after

                # Use API client request path (includes header spoof + rate-limit handling).
                response = self._safe_api_call("GET", f"/guilds/{server_id}/members", params=params)
                if not response or response.status_code != 200:
                    if self._should_log_member_failure(server_id):
                        print(f"[History] Failed to get members for server {server_id}")
                    break

                data = self._safe_json_parse(response)
                if not data or not isinstance(data, list):
                    break

                for member in data:
                    if not isinstance(member, dict) or 'user' not in member:
                        continue
                        
                    member_snapshot = {
                        'timestamp': time.time(),
                        'user_id': member['user']['id'],
                        'username': member['user']['username'],
                        'global_name': member['user'].get('global_name'),
                        'discriminator': member['user'].get('discriminator'),
                        'avatar': member['user'].get('avatar'),
                        'bot': member['user'].get('bot', False),
                        'joined_at': member.get('joined_at'),
                        'nick': member.get('nick'),
                        'roles': member.get('roles', []),
                        'premium_since': member.get('premium_since'),
                        'deaf': member.get('deaf', False),
                        'mute': member.get('mute', False),
                        'pending': member.get('pending', False)
                    }
                    
                    # Validate required fields
                    if member_snapshot.get('user_id') and member_snapshot.get('username'):
                        members.append(member_snapshot)
                        self.user_guild_index[member_snapshot['user_id']].add(server_id)
                        self.member_profile_cache[member_snapshot['user_id']] = {
                            'username': member_snapshot.get('username'),
                            'global_name': member_snapshot.get('global_name'),
                            'discriminator': member_snapshot.get('discriminator'),
                            'avatar': member_snapshot.get('avatar'),
                            'bot': member_snapshot.get('bot', False),
                            'nick': member_snapshot.get('nick'),
                            'roles': member_snapshot.get('roles', []),
                            'joined_at': member_snapshot.get('joined_at'),
                            'premium_since': member_snapshot.get('premium_since'),
                            'guild_id': server_id
                        }

                if len(data) < 1000:
                    break

                after = data[-1]['user']['id'] if data else None
                if not after:
                    break

        except Exception as e:
            print(f"[History] Error scraping members for server {server_id}: {e}")

        return members

    def add_user_to_scrape(self, user_id: str):
        """Add a user ID to the list of users to scrape profiles for"""
        if user_id not in self.users_to_scrape:
            self.users_to_scrape.add(user_id)
            self.save_history()
            return True
        return False
    
    def get_users_to_scrape(self) -> set:
        """Get the set of user IDs that should be scraped"""
        return self.users_to_scrape.copy()
    
    def scrape_queued_users(self):
        """Scrape profiles for all queued user IDs"""
        if not self.users_to_scrape:
            print("[History] No users queued for scraping")
            return
        
        scraped_count = 0
        user_ids = list(self.users_to_scrape)
        
        print(f"[History] Scraping profiles for {len(user_ids)} queued users...")
        
        for user_id in user_ids:
            if not self.scraping_active:
                break
                
            try:
                profile_data = self.scrape_user_profile(user_id)
                if profile_data:
                    self.add_profile_snapshot(user_id, profile_data)
                    self.users_to_scrape.remove(user_id)  # Remove from queue after successful scrape
                    scraped_count += 1
                
                time.sleep(0.2)  # Rate limit protection
                
            except Exception as e:
                print(f"[History] Error scraping profile for user {user_id}: {e}")
                continue
        
        self.save_history()
        print(f"[History] Successfully scraped {scraped_count} user profiles")

    def get_user_profile_changes(self, user_id: str) -> List[Dict[str, Any]]:
        """Analyze profile changes over time"""
        history = self.get_user_history(user_id)
        if len(history) < 2:
            return []

        changes = []
        prev_profile = history[0]

        for profile in history[1:]:
            change = {
                'timestamp': profile['timestamp'],
                'changes': {}
            }

            # Check for changes in key fields
            fields_to_check = [
                'username', 'global_name', 'avatar', 'banner', 'bio', 'pronouns',
                'nick', 'guild_bio', 'guild_pronouns', 'accent_color'
            ]
            for field in fields_to_check:
                if prev_profile.get(field) != profile.get(field):
                    change['changes'][field] = {
                        'from': prev_profile.get(field),
                        'to': profile.get(field)
                    }

            if change['changes']:
                changes.append(change)

            prev_profile = profile

        return changes

    def get_server_changes(self, server_id: str) -> List[Dict[str, Any]]:
        """Analyze server changes over time"""
        history = self.get_server_history(server_id)
        if len(history) < 2:
            return []

        changes = []
        prev_server = history[0]

        for server in history[1:]:
            change = {
                'timestamp': server['timestamp'],
                'changes': {}
            }

            # Check for changes in key fields
            fields_to_check = ['name', 'icon', 'banner', 'description', 'premium_subscription_count', 'approximate_member_count']
            for field in fields_to_check:
                if prev_server.get(field) != server.get(field):
                    change['changes'][field] = {
                        'from': prev_server.get(field),
                        'to': server.get(field)
                    }

            if change['changes']:
                changes.append(change)

            prev_server = server

        return changes
    
    def start_background_scraping(self, interval_seconds: int = 3600):
        """Background scraping is disabled in favor of manual exports."""
        return False, "Background scraping is disabled. Use +export for real-time account data."
    
    def stop_background_scraping(self):
        """Background scraping is disabled in favor of manual exports."""
        self.scraping_active = False
        return False, "Background scraping is disabled. Use +export for real-time account data."
    
    def _scraping_worker(self):
        """Background worker thread for periodic scraping"""
        while self.scraping_active:
            try:
                print("[History] Starting periodic server data scrape...")
                self._scrape_all_servers()
                
                # Also process any queued users
                if self.users_to_scrape:
                    print(f"[History] Processing {len(self.users_to_scrape)} queued users...")
                    self.scrape_queued_users()
                
                # Save history to persist recent users
                self.save_history()
                
                print(f"[History] Scrape complete. Sleeping for {self.scraping_interval} seconds...")
            except Exception as e:
                print(f"[History] Error in background scraping: {e}")
            
            # Sleep for the interval, but check every 10 seconds if we should stop
            for _ in range(0, self.scraping_interval, 10):
                if not self.scraping_active:
                    break
                time.sleep(10)
    
    def _scrape_all_servers(self):
        """Scrape all accessible servers and collect user IDs for profile scraping with circuit breaker"""
        try:
            # Use circuit breaker for the main scraping operation
            return self.scrape_circuit_breaker.call(self._perform_server_scraping)
        except Exception as e:
            print(f"[History] Server scraping circuit breaker activated: {e}")
            return

    def _perform_server_scraping(self):
        """Actual server scraping logic"""
        guilds = self.api.get_guilds(force=False)
        if not guilds:
            print("[History] Failed to get guild list - circuit breaker may activate")
            raise Exception("Cannot get guild list")

        current_guild_ids = {guild.get("id") for guild in guilds if isinstance(guild, dict)}
        
        # Clean up servers the bot is no longer in
        servers_to_remove = []
        for server_id in self.servers:
            if server_id not in current_guild_ids:
                servers_to_remove.append(server_id)
        
        for server_id in servers_to_remove:
            print(f"[History] Removing data for server {server_id} (bot no longer member)")
            del self.servers[server_id]
        
        if servers_to_remove:
            self.save_history()
        
        scraped_count = 0
        user_ids_collected = set()
        
        for guild in guilds:
            if not self.scraping_active:  # Allow stopping mid-scrape
                break
            
            if not isinstance(guild, dict):
                continue
                
            guild_id = guild.get("id")
            guild_name = guild.get("name", "Unknown")
            
            if not guild_id or not isinstance(guild_id, str):
                continue
            
            try:
                # Scrape server data
                server_data = self.scrape_server_data(guild_id)
                if server_data:
                    self.add_server_snapshot(guild_id, server_data)
                    scraped_count += 1
                    
                    # Extract user IDs from server data (owner, etc.)
                    if 'owner_id' in server_data and server_data['owner_id']:
                        user_ids_collected.add(server_data['owner_id'])
                
                # Collect user IDs from server members instead of message history
                members = []
                try:
                    members = self.scrape_all_guild_members(guild_id, limit=500)  # Get up to 500 members
                    for member in members:
                        if member.get('user_id'):
                            user_ids_collected.add(member['user_id'])
                    if members:
                        print(f"[History] Collected {len(members)} members from server {guild_name}")
                except Exception as e:
                    print(f"[History] Error collecting members from server {guild_name}: {e}")
            
            except Exception as e:
                print(f"[History] Error scraping {guild_name}: {e}")
                continue
        
        print(f"[History] Successfully scraped {scraped_count} servers")
        
        # Process collected user IDs
        if user_ids_collected:
            print(f"[History] Found {len(user_ids_collected)} unique users to profile")
            profiles_scraped = 0
            
            for user_id in user_ids_collected:
                if not self.scraping_active:
                    break
                    
                try:
                    profile_data = self.scrape_user_profile(user_id)
                    if profile_data:
                        self.add_profile_snapshot(user_id, profile_data)
                        profiles_scraped += 1
                    
                    time.sleep(0.2)  # Rate limit protection
                    
                except Exception as e:
                    print(f"[History] Error scraping profile for user {user_id}: {e}")
                    continue
            
            print(f"[History] Successfully scraped {profiles_scraped} user profiles")