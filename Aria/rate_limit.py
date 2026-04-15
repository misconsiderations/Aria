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
        self.endpoint_to_bucket = {}

    def normalize_endpoint(self, endpoint: str) -> str:
        if not endpoint:
            return "global"
        return endpoint.split("?", 1)[0]

    def parse_bucket_hash(self, headers: Dict) -> str:
        if "X-RateLimit-Bucket" in headers:
            return headers["X-RateLimit-Bucket"]
        return "global"

    def record_endpoint_bucket(self, endpoint: str, bucket_hash: str):
        normalized = self.normalize_endpoint(endpoint)
        with self.global_lock:
            self.endpoint_to_bucket[normalized] = bucket_hash

    def update_bucket(self, bucket_hash: str, headers: Dict):
        with self.locks[bucket_hash]:
            self.buckets[bucket_hash] = {
                "limit": int(headers.get("X-RateLimit-Limit", 1)),
                "remaining": int(headers.get("X-RateLimit-Remaining", 1)),
                "reset": float(headers.get("X-RateLimit-Reset-After", 0)),
                "reset_at": time.time() + float(headers.get("X-RateLimit-Reset-After", 0)),
            }

    def handle_429(self, headers: Dict, endpoint: str):
        retry_after = float(headers.get("Retry-After", 1))
        normalized = self.normalize_endpoint(endpoint)
        with self.global_lock:
            self.buckets[normalized] = {
                "limit": 0,
                "remaining": 0,
                "reset": retry_after,
                "reset_at": time.time() + retry_after,
            }
        return retry_after

    def should_wait(self, endpoint: str) -> Optional[float]:
        normalized = self.normalize_endpoint(endpoint)
        bucket_key = self.endpoint_to_bucket.get(normalized, normalized)
        bucket_data = self.buckets.get(bucket_key)
        if not bucket_data:
            return None

        current_time = time.time()
        if bucket_data["remaining"] <= 0 and current_time < bucket_data["reset_at"]:
            return bucket_data["reset_at"] - current_time

        return None

    def get_wait_time(self, endpoint: str) -> Optional[float]:
        """Get wait time for endpoint without sleeping."""
        return self.should_wait(endpoint)

    def decrement(self, endpoint: str):
        """Decrement remaining for endpoint."""
        normalized = self.normalize_endpoint(endpoint)
        bucket_key = self.endpoint_to_bucket.get(normalized, normalized)
        bucket_data = self.buckets.get(bucket_key)
        if bucket_data:
            bucket_data["remaining"] = max(0, bucket_data.get("remaining", 1) - 1)
