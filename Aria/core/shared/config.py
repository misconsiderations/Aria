from typing import Optional

class ConfigContainer:
    """Simple configuration container"""

    def __init__(self):
        self.token: Optional[str] = None
        self.debug: bool = False
        self.prefix: str = ";"
        self.client: str = "mobile"
        self.state: str = "online"

# Global instance
container = ConfigContainer()
<parameter name="filePath">/workspaces/Aria/Aria/core/shared/config.py