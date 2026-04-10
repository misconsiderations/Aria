import random
import time
from typing import Dict, Any
from curl_cffi.requests import Session

class HeaderGenerator:
    """Original header generator for fallback"""

    def __init__(self, token: str):
        self.token = token
        self.session = self._create_session()

    def _create_session(self) -> Session:
        """Create a basic session with headers"""
        session = Session()

        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }

        session.headers.update(headers)
        return session

    def get_headers(self) -> Dict[str, str]:
        """Get basic headers"""
        return dict(self.session.headers)