import random
import requests

class ProxyManager:
    def __init__(self, proxy_list=None):
        self.proxies = proxy_list or [
            # Add your proxies here, e.g., "socks5://user:pass@proxy1:port"
        ]
    
    def get_random_proxy(self):
        if not self.proxies:
            return {}
        proxy = random.choice(self.proxies)
        return {"http": proxy, "https": proxy}
    
    def test_proxy(self, proxy):
        try:
            response = requests.get("https://httpbin.org/ip", proxies=proxy, timeout=5)
            return response.status_code == 200
        except:
            return False