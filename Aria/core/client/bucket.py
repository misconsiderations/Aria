import time
import threading
from typing import Dict, Any, Optional, Tuple
from collections import defaultdict

class BucketHandler:
    """Advanced bucket-based rate limiter for Discord API"""

    def __init__(self):
        self.buckets: Dict[str, Dict[str, Any]] = {}
        self.endpoint_buckets: Dict[str, str] = {}
        self.global_bucket = "global"
        self.lock = threading.Lock()

    def parse_bucket_hash(self, headers: Dict[str, str]) -> str:
        """Parse bucket hash from response headers"""
        return headers.get("X-RateLimit-Bucket", self.global_bucket)

    def update_bucket(self, bucket_hash: str, headers: Dict[str, str]):
        """Update bucket information from response headers"""
        with self.lock:
            if bucket_hash not in self.buckets:
                self.buckets[bucket_hash] = {}

            bucket = self.buckets[bucket_hash]
            now = time.time()

            bucket.update({
                "limit": int(headers.get("X-RateLimit-Limit", 5)),
                "remaining": int(headers.get("X-RateLimit-Remaining", 5)),
                "reset": float(headers.get("X-RateLimit-Reset", now + 1)),
                "reset_after": float(headers.get("X-RateLimit-Reset-After", 1.0)),
                "last_update": now
            })

    def should_wait(self, bucket_hash: str) -> Optional[float]:
        """Check if we should wait before making a request"""
        with self.lock:
            if bucket_hash not in self.buckets:
                return None

            bucket = self.buckets[bucket_hash]
            now = time.time()

            # Check if bucket is expired
            if now > bucket.get("reset", 0):
                return None

            remaining = bucket.get("remaining", 5)
            if remaining <= 0:
                reset_time = bucket.get("reset", now + 1)
                if now < reset_time:
                    return reset_time - now

            return None

    def decrement(self, bucket_hash: str):
        """Decrement remaining requests for a bucket"""
        with self.lock:
            if bucket_hash in self.buckets:
                self.buckets[bucket_hash]["remaining"] = max(0, self.buckets[bucket_hash].get("remaining", 5) - 1)

    def handle_429(self, headers: Dict[str, str], endpoint: str):
        """Handle 429 response by updating bucket info"""
        bucket_hash = self.parse_bucket_hash(headers)
        self.update_bucket(bucket_hash, headers)

        # Map endpoint to bucket for future requests
        if endpoint:
            self.endpoint_buckets[endpoint] = bucket_hash

    def get_bucket_for_endpoint(self, endpoint: str) -> str:
        """Get bucket hash for an endpoint"""
        return self.endpoint_buckets.get(endpoint, self.global_bucket)

    def check_spam_risk(self, action_type: str, target_id: str) -> Tuple[bool, str]:
        """
        Check if an action poses spam risk
        Returns (can_proceed, reason)
        """
        # Basic spam protection - can be extended
        if action_type == "dm_new_user":
            # Allow DMs but with caution
            return True, "DM allowed with rate limiting"

        return True, "Action allowed"

    def cleanup_expired_buckets(self):
        """Clean up expired bucket information"""
        with self.lock:
            now = time.time()
            expired = []

            for bucket_hash, bucket in self.buckets.items():
                if now > bucket.get("reset", 0) + 300:  # Keep for 5 minutes after reset
                    expired.append(bucket_hash)

            for bucket_hash in expired:
                del self.buckets[bucket_hash]

    def get_bucket_info(self, bucket_hash: str) -> Optional[Dict[str, Any]]:
        """Get information about a bucket"""
        with self.lock:
            return self.buckets.get(bucket_hash)

    def get_all_buckets(self) -> Dict[str, Dict[str, Any]]:
        """Get all bucket information"""
        with self.lock:
            return self.buckets.copy()