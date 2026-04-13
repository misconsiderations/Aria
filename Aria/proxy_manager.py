import random
import requests
import time

class ProxyManager:
    def __init__(self, proxy_list=None):
        self.proxies = proxy_list or []
        self.last_fetch = 0
        self.fetch_interval = 3600  # Refresh every hour
        if not self.proxies:
            self._fetch_from_github()
    
    def _fetch_from_github(self):
        """Fetch free proxies from GitHub repo."""
        try:
            url = "https://raw.githubusercontent.com/claude89757/free_https_proxies/main/proxies.txt"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                lines = response.text.strip().split('\n')
                # Filter and format proxies (assuming format: ip:port or protocol://ip:port)
                self.proxies = [
                    line.strip() if line.strip().startswith(('http://', 'https://', 'socks5://')) 
                    else f"http://{line.strip()}"
                    for line in lines if line.strip() and not line.startswith('#')
                ]
                self.last_fetch = time.time()
                if self.proxies:
                    print(f"[PROXY] Loaded {len(self.proxies)} proxies from GitHub")
        except Exception as e:
            print(f"[PROXY] Failed to fetch from GitHub: {e}")
    
    def refresh(self):
        """Refresh proxies if interval has passed."""
        if time.time() - self.last_fetch > self.fetch_interval:
            self._fetch_from_github()
    
    def get_random_proxy(self):
        """Get a random proxy from the list."""
        self.refresh()
        if not self.proxies:
            return {}
        proxy = random.choice(self.proxies)
        return {"http": proxy, "https": proxy}
    
    def test_proxy(self, proxy):
        """Test if a proxy is working."""
        try:
            response = requests.get("https://httpbin.org/ip", proxies=proxy, timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def get_all_proxies(self):
        """Return all available proxies."""
        self.refresh()
        return self.proxies.copy()