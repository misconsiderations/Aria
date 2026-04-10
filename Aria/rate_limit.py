import json
import time
import threading
from collections import defaultdict
from typing import Dict, Optional

class RateLimiter:
    def __init__(self):
        self.buckets = defaultdict(dict)
        self.locks = defaultdict(threading.Lock)
        self.global_lock = threading.Lock()
    
    def parse_bucket_hash(self, headers: Dict) -> str:
        if "X-RateLimit-Bucket" in headers:
            return headers["X-RateLimit-Bucket"]
        
        return "global"
    
    def update_bucket(self, bucket_hash: str, headers: Dict):
        with self.locks[bucket_hash]:
            self.buckets[bucket_hash] = {
                "limit": int(headers.get("X-RateLimit-Limit", 1)),
                "remaining": int(headers.get("X-RateLimit-Remaining", 1)),
                "reset": float(headers.get("X-RateLimit-Reset-After", 0)),
                "reset_at": time.time() + float(headers.get("X-RateLimit-Reset-After", 0))
            }
    
    def handle_429(self, headers: Dict, endpoint: str):
        retry_after = float(headers.get("Retry-After", 1))
        with self.global_lock:
            self.buckets[endpoint] = {
                "limit": 0,
                "remaining": 0,
                "reset": retry_after,
                "reset_at": time.time() + retry_after
            }
        return retry_after
    
    def should_wait(self, endpoint: str) -> Optional[float]:
        bucket_data = self.buckets.get(endpoint)
        if not bucket_data:
            return None
        
        current_time = time.time()
        
        if bucket_data["remaining"] <= 0:
            if current_time < bucket_data["reset_at"]:
                return bucket_data["reset_at"] - current_time
        
        return None
    
    def decrement(self, endpoint: str):
        if endpoint in self.buckets:
            with self.locks[endpoint]:
                if self.buckets[endpoint]["remaining"] > 0:
                    self.buckets[endpoint]["remaining"] -= 1
    
    def get_wait_time(self, endpoint: str) -> float:
        wait = self.should_wait(endpoint)
        if wait:
            time.sleep(wait)
            return wait
        return 0.0