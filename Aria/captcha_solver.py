import time
import json
import re
import base64
from typing import Optional, Dict, Any

# Try to import twocaptcha, but make it optional
try:
    from twocaptcha import TwoCaptcha
    TWOCAPTCHA_AVAILABLE = True
except ImportError:
    TWOCAPTCHA_AVAILABLE = False
    TwoCaptcha = None

class CaptchaSolver:
    """Comprehensive captcha solver for Discord API captcha challenges"""
    def __init__(self, api_key: str = "", service: str = "2captcha"):
        self.api_key = api_key
        self.service = service
        self.solver = None
        self.last_solve_time = 0

        if api_key and service == "2captcha" and TWOCAPTCHA_AVAILABLE and TwoCaptcha:
            try:
                print(f"[DEBUG] Initializing TwoCaptcha with API key: {api_key[:4]}...{api_key[-4:]}")
                self.solver = TwoCaptcha(api_key)
                print("[DEBUG] TwoCaptcha initialized successfully.")
            except Exception as e:
                print(f"[ERROR] TwoCaptcha initialization failed: {e}")
                self.solver = None
        else:
            print("[DEBUG] TwoCaptcha not available or API key missing.")

    def is_enabled(self) -> bool:
        """Check if captcha solving is enabled"""
        return bool(self.api_key and self.solver is not None)

    def solve_hcaptcha(self, site_key: str, url: str, invisible: bool = False) -> Optional[str]:
        if not self.is_enabled():
            print("[DEBUG] CAPTCHA solving is not enabled.")
            return None

        if not self.solver:
            print("[ERROR] Solver is not initialized. Cannot solve CAPTCHA.")
            return None

        try:
            print(f"[DEBUG] Solving hCaptcha for site_key: {site_key}, url: {url}")
            result = self.solver.solve_captcha(
                site_key=site_key,
                page_url=url
            )
            self.last_solve_time = time.time()
            print("[DEBUG] hCaptcha solved successfully.")
            return result  # Return result directly
        except Exception as e:
            print(f"[ERROR] Failed to solve hCaptcha: {e}")
            return None

    def solve_recaptcha(self, site_key: str, url: str, version: str = "v2") -> Optional[str]:
        """Solve reCAPTCHA challenge"""
        if not self.is_enabled():
            print("[DEBUG] CAPTCHA solving is not enabled.")
            return None

        if not self.solver:
            print("[ERROR] Solver is not initialized. Cannot solve CAPTCHA.")
            return None

        try:
            print(f"[DEBUG] Solving reCAPTCHA for site_key: {site_key}, url: {url}, version: {version}")
            result = self.solver.solve_captcha(
                site_key=site_key,
                page_url=url
            )
            self.last_solve_time = time.time()
            print("[DEBUG] reCAPTCHA solved successfully.")
            return result  # Return result directly
        except Exception as e:
            print(f"[ERROR] Failed to solve reCAPTCHA: {e}")
            return None

    def solve_turnstile(self, site_key: str, url: str) -> Optional[str]:
        """Solve Cloudflare Turnstile challenge"""
        if not self.is_enabled():
            print("[DEBUG] CAPTCHA solving is not enabled.")
            return None

        if not self.solver:
            print("[ERROR] Solver is not initialized. Cannot solve CAPTCHA.")
            return None

        try:
            print(f"[DEBUG] Solving Turnstile CAPTCHA for site_key: {site_key}, url: {url}")
            result = self.solver.solve_captcha(
                site_key=site_key,
                page_url=url
            )
            self.last_solve_time = time.time()
            print("[DEBUG] Turnstile CAPTCHA solved successfully.")
            return result  # Return result directly
        except Exception as e:
            print(f"[ERROR] Failed to solve Turnstile CAPTCHA: {e}")
            return None

    def extract_captcha_from_headers(self, headers: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Extract captcha info from response headers"""
        # Check for X-Captcha-Key or similar headers Discord might send
        for header_key in headers:
            if 'captcha' in header_key.lower():
                try:
                    if header_key.lower() == 'x-captcha-key':
                        return {'site_key': headers[header_key], 'service': 'hcaptcha'}
                except:
                    pass
        return None

    def detect_captcha_type(self, response_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Detect captcha type from Discord response - handles multiple formats"""
        if not isinstance(response_data, dict):
            return None

        # Format 1: Direct captcha field (standard format)
        captcha = response_data.get('captcha', {})
        if isinstance(captcha, dict) and captcha:
            captcha_type = str(captcha.get('type', '')).lower()
            site_key = captcha.get('site_key', '')
            service = captcha.get('service', 'hcaptcha')
            
            if site_key:
                return {
                    'type': captcha_type or 'hcaptcha',
                    'site_key': site_key,
                    'service': service
                }

        # Format 2: Nested in captcha_sitekey
        if 'captcha_sitekey' in response_data:
            return {
                'type': 'hcaptcha',
                'site_key': response_data['captcha_sitekey'],
                'service': 'hcaptcha'
            }

        # Format 3: In captcha_key
        if 'captcha_key' in response_data:
            return {
                'type': 'hcaptcha',
                'site_key': response_data['captcha_key'],
                'service': 'hcaptcha'
            }

        # Format 4: reCAPTCHA v2
        if response_data.get('captcha_type') == 'recaptcha_v2':
            return {
                'type': 'recaptcha',
                'site_key': response_data.get('recaptcha_key', ''),
                'service': 'recaptcha'
            }

        # Format 5: Turnstile
        if response_data.get('captcha_type') == 'turnstile':
            return {
                'type': 'turnstile',
                'site_key': response_data.get('turnstile_key', ''),
                'service': 'turnstile'
            }

        return None

    def solve_captcha_challenge(self, captcha_info: Dict[str, str], url: str) -> Optional[str]:
        """Solve captcha based on detected type"""
        if not captcha_info:
            return None

        captcha_type = str(captcha_info.get('type', 'hcaptcha')).lower()
        site_key = captcha_info.get('site_key', '')
        
        if not site_key:
            return None

        print(f"[CAPTCHA] Detecting type: {captcha_type}, solving...")

        if captcha_type == 'hcaptcha':
            return self.solve_hcaptcha(site_key, url)
        elif captcha_type == 'recaptcha':
            return self.solve_recaptcha(site_key, url, version='v2')
        elif captcha_type == 'turnstile':
            return self.solve_turnstile(site_key, url)

        return None

    def get_captcha_ratelimit_key(self) -> Optional[str]:
        """Get the appropriate field name for captcha token based on service"""
        # Discord generically accepts "captcha_key" for most services
        return "captcha_key"