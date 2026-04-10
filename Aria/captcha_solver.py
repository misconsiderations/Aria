import time
import json
from typing import Optional, Dict, Any
from twocaptcha import TwoCaptcha

class CaptchaSolver:
    def __init__(self, api_key: str, service: str = "2captcha"):
        self.api_key = api_key
        self.service = service
        self.solver = None
        if api_key and service == "2captcha":
            self.solver = TwoCaptcha(api_key)

    def is_enabled(self) -> bool:
        return bool(self.api_key and self.solver)

    def solve_hcaptcha(self, site_key: str, url: str) -> Optional[str]:
        """Solve hCaptcha challenge"""
        if not self.is_enabled():
            return None

        try:
            result = self.solver.hcaptcha(
                sitekey=site_key,
                url=url
            )
            return result['code']
        except Exception as e:
            print(f"Failed to solve hCaptcha: {e}")
            return None

    def solve_recaptcha(self, site_key: str, url: str) -> Optional[str]:
        """Solve reCAPTCHA challenge"""
        if not self.is_enabled():
            return None

        try:
            result = self.solver.recaptcha(
                sitekey=site_key,
                url=url
            )
            return result['code']
        except Exception as e:
            print(f"Failed to solve reCAPTCHA: {e}")
            return None

    def solve_turnstile(self, site_key: str, url: str) -> Optional[str]:
        """Solve Cloudflare Turnstile challenge"""
        if not self.is_enabled():
            return None

        try:
            result = self.solver.turnstile(
                sitekey=site_key,
                url=url
            )
            return result['code']
        except Exception as e:
            print(f"Failed to solve Turnstile: {e}")
            return None

    def detect_captcha_type(self, response_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Detect captcha type from Discord response"""
        if not isinstance(response_data, dict):
            return None

        # Check for captcha challenge in response
        captcha = response_data.get('captcha', {})
        if not captcha:
            return None

        captcha_type = captcha.get('type', '').lower()
        site_key = captcha.get('site_key', '')
        service = captcha.get('service', 'hcaptcha')

        if not site_key:
            return None

        return {
            'type': captcha_type,
            'site_key': site_key,
            'service': service
        }

    def solve_captcha_challenge(self, captcha_info: Dict[str, str], url: str) -> Optional[str]:
        """Solve captcha based on detected type"""
        captcha_type = captcha_info.get('type', '')
        site_key = captcha_info.get('site_key', '')

        if captcha_type == 'hcaptcha':
            return self.solve_hcaptcha(site_key, url)
        elif captcha_type == 'recaptcha':
            return self.solve_recaptcha(site_key, url)
        elif captcha_type == 'turnstile':
            return self.solve_turnstile(site_key, url)

        return None