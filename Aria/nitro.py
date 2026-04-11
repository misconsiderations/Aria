import re
import time
import threading
from datetime import datetime

class NitroSniper:
    def __init__(self, api_client):
        self.api = api_client
        self.enabled = False
        self.used_codes = set()
        self.claimed_count = 0
        self.lock = threading.Lock()
        
    def check_message(self, message_data):
        if not self.enabled:
            return
        
        content = message_data.get("content", "")
        author_id = message_data.get("author", {}).get("id", "")
        
        if author_id == self.api.user_id:
            return
        
        patterns = [
            r"discord\.gift/(\w{16,24})",
            r"discordapp\.com/gifts/(\w{16,24})",
            r"discord\.com/gifts/(\w{16,24})",
            r"discord\.com/billing/promotions/(\w{16,24})"
        ]
        
        found_codes = []
        for pattern in patterns:
            found_codes.extend(re.findall(pattern, content, re.IGNORECASE))
        
        raw_codes = re.findall(r'\b([a-zA-Z0-9]{16,24})\b', content)
        for code in raw_codes:
            if len(code) in [16, 24] and code not in found_codes:
                found_codes.append(code)
        
        for code in found_codes:
            with self.lock:
                if code in self.used_codes:
                    continue
                self.used_codes.add(code)
            
            threading.Thread(target=self._claim_code, args=(code, message_data), daemon=True).start()
    
    def _claim_code(self, code, message_data):
        start_time = time.time()
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        try:
            headers = self.api.header_spoofer.get_headers()
            
            response = self.api.session.post(
                f"https://discord.com/api/v9/entitlements/gift-codes/{code}/redeem",
                headers=headers,
                json={}
            )
            
            elapsed = (time.time() - start_time) * 1000
            
            if response.status_code == 200:
                response_data = response.json()
                if "subscription_plan" in str(response_data):
                    with self.lock:
                        self.claimed_count += 1
                    print(f"\033[1;32m[NITRO CLAIMED]\033[0m [{timestamp}] Code: {code} | {elapsed:.1f}ms")
                elif "already been redeemed" in str(response_data):
                    print(f"\033[1;33m[NITRO]\033[0m [{timestamp}] Already redeemed: {code} | {elapsed:.1f}ms")
                elif "Unknown Gift Code" in str(response_data):
                    print(f"\033[0;90m[NITRO]\033[0m [{timestamp}] Invalid code: {code} | {elapsed:.1f}ms")
            elif response.status_code == 429:
                print(f"\033[1;31m[NITRO]\033[0m [{timestamp}] Rate limited on: {code} | {elapsed:.1f}ms")
            else:
                print(f"\033[1;31m[NITRO]\033[0m [{timestamp}] Failed: {code} | status={response.status_code} | {elapsed:.1f}ms")
                
        except Exception as e:
            elapsed = (time.time() - start_time) * 1000
            print(f"\033[1;31m[NITRO ERROR]\033[0m [{timestamp}] {e} | {elapsed:.1f}ms")
    
    def toggle(self, state=True):
        self.enabled = state
        return self.enabled
    
    def clear_codes(self):
        with self.lock:
            count = len(self.used_codes)
            self.used_codes.clear()
            return count
    
    def get_stats(self):
        with self.lock:
            return {
                "enabled": self.enabled,
                "used_codes": len(self.used_codes),
                "claimed": self.claimed_count,
                "cached": len(self.used_codes),
            }

nitro_fast = None