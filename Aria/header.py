import json
import base64
import random
import time
import hashlib
from dataclasses import dataclass, field
from typing import List, Dict
from curl_cffi.requests import Session
import ssl

@dataclass
class BrowserProfile:
    user_agent: str
    os: str
    browser: str
    browser_version: str
    os_version: str
    locale: str
    timezone: str
    screen_resolution: str = "1920x1080"
    hardware_concurrency: int = 8
    device_memory: int = 8
    fonts: list = field(default_factory=list)
    plugins: list = field(default_factory=list)

class HeaderSpoofer:
    def __init__(self, token: str):
        self.token = token
        self.fingerprint = ""
        self.cookies = ""
        self.cache_time = 0
        self._session_id = f"{int(time.time() * 1000)}"
        self._browser_session = f"session_{random.randint(100000, 999999)}"
        self.profile = self._create_consistent_profile()
        self.session = self._create_session()
        self.build_number = 284054
        self.xsp_hash = self._generate_xsp_hash()
    
    def _create_session(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return Session(impersonate="chrome120")
    
    def _create_consistent_profile(self):
        timestamp = int(time.time())
        random.seed(timestamp % 1000)
        
        locations = [
            {"timezone": "America/New_York", "locale": "en-US"},
            {"timezone": "America/Chicago", "locale": "en-US"},
            {"timezone": "America/Los_Angeles", "locale": "en-US"},
            {"timezone": "Europe/London", "locale": "en-GB"},
            {"timezone": "Europe/Paris", "locale": "fr-FR"},
            {"timezone": "Asia/Tokyo", "locale": "ja-JP"},
            {"timezone": "Australia/Sydney", "locale": "en-AU"}
        ]
        
        location_idx = timestamp % len(locations)
        location = locations[location_idx]
        
        chrome_versions = [
            {"major": "125", "full": "125.0.6422.113"},
            {"major": "124", "full": "124.0.6367.207"},
            {"major": "123", "full": "123.0.6312.122"},
        ]
        
        version_idx = (timestamp // 3600) % len(chrome_versions)
        chrome = chrome_versions[version_idx]
        
        os_versions = {
            "Windows": ["10", "11"],
            "Mac": ["13_6", "14_4"],
            "Linux": ["x86_64"]
        }
        
        os_type = "Windows"
        os_version = random.choice(os_versions[os_type])
        
        resolutions = ["1920x1080", "2560x1440", "3840x2160", "1366x768", "1536x864"]
        resolution_idx = (timestamp // 1000) % len(resolutions)
        
        return BrowserProfile(
            user_agent=f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome['full']} Safari/537.36",
            os=os_type,
            browser="Chrome",
            browser_version=chrome['full'],
            os_version=os_version,
            locale=location['locale'],
            timezone=location['timezone'],
            screen_resolution=resolutions[resolution_idx],
            hardware_concurrency=random.choice([8, 12, 16]),
            device_memory=random.choice([8, 16, 32]),
            fonts=["Arial", "Helvetica", "Times New Roman", "Verdana", "Georgia", "Courier New"],
            plugins=["Chrome PDF Plugin", "Chrome PDF Viewer", "Native Client", "Widevine Content Decryption Module"]
        )
    
    def _generate_xsp_hash(self):
        data = f"{self.profile.os}{self.profile.browser}{self.profile.locale}{self.build_number}"
        return hashlib.md5(data.encode()).hexdigest()[:8]
    
    def fetch_fingerprint(self):
        if time.time() - self.cache_time < 3600 and self.fingerprint:
            return self.fingerprint, self.cookies
        
        try:
            headers = {
                "User-Agent": self.profile.user_agent,
                "Accept": "application/json",
                "Accept-Language": self.profile.locale,
            }
            
            response = self.session.get(
                "https://discord.com/api/v9/experiments",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.fingerprint = data.get("fingerprint", self._fallback_fingerprint())
                
                cookie_parts = []
                for cookie_name, cookie_value in response.cookies.items():
                    cookie_parts.append(f"{cookie_name}={cookie_value}")
                
                self.cookies = "; ".join(cookie_parts) + f"; locale={self.profile.locale}"
                self.cache_time = time.time()
            else:
                self.fingerprint = self._fallback_fingerprint()
                self.cookies = self._default_cookies()
                
        except Exception as e:
            print(f"Fingerprint fetch error: {e}")
            self.fingerprint = self._fallback_fingerprint()
            self.cookies = self._default_cookies()
        
        return self.fingerprint, self.cookies
    
    def _fallback_fingerprint(self):
        base = int(time.time() * 1000)
        return f"{base}.{random.randint(100000000000000000, 999999999999999999)}"
    
    def _default_cookies(self):
        timestamp = int(time.time())
        return f"__dcfduid={timestamp}abcdef; __sdcfduid={timestamp}ghijkl; locale={self.profile.locale}"
    
    def generate_super_properties(self):
        props = {
            "os": self.profile.os,
            "browser": self.profile.browser,
            "device": "",
            "system_locale": self.profile.locale,
            "browser_user_agent": self.profile.user_agent,
            "browser_version": self.profile.browser_version,
            "os_version": self.profile.os_version,
            "referrer": "",
            "referring_domain": "",
            "release_channel": "stable",
            "client_build_number": self.build_number,
            "client_event_source": None,
            "design_id": 0
        }
        
        xsp_json = json.dumps(props, separators=(',', ':'))
        xsp_b64 = base64.b64encode(xsp_json.encode()).decode()
        return xsp_b64
    
    def generate_sec_ch_ua(self):
        major_version = self.profile.browser_version.split('.')[0]
        return f'"Chromium";v="{major_version}", "Google Chrome";v="{major_version}", "Not=A?Brand";v="99"'
    
    def get_headers(self, additional_headers: Dict = None):
        fingerprint, cookies = self.fetch_fingerprint()
        
        headers = {
            "Authorization": self.token,
            "User-Agent": self.profile.user_agent,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": f"{self.profile.locale},en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/channels/@me",
            "Sec-Ch-Ua": self.generate_sec_ch_ua(),
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": f'"{self.profile.os}"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Dnt": "1",
            "Upgrade-Insecure-Requests": "1",
            "X-Debug-Options": "bugReporterEnabled",
            "X-Discord-Locale": self.profile.locale,
            "X-Discord-Timezone": self.profile.timezone,
            "X-Super-Properties": self.generate_super_properties(),
            "X-Fingerprint": fingerprint,
            "Cookie": cookies,
            "X-Track": hashlib.md5(str(time.time()).encode()).hexdigest(),
            "X-Super-Properties-Hash": self.xsp_hash
        }
        
        if additional_headers:
            headers.update(additional_headers)
        
        return headers
    
    def get_websocket_headers(self):
        return {
            "User-Agent": self.profile.user_agent,
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": self.profile.locale,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-WebSocket-Extensions": "permessage-deflate; client_max_window_bits",
            "Sec-WebSocket-Key": base64.b64encode(str(time.time()).encode()).decode()[:24],
            "Sec-WebSocket-Version": "13",
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Origin": "https://discord.com",
            "Sec-WebSocket-Protocol": "json"
        }
    
    def rotate_profile(self):
        self.profile = self._create_consistent_profile()
        self.xsp_hash = self._generate_xsp_hash()
        self.cache_time = 0
        return self.profile