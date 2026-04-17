import asyncio
import websockets
import json
import time
import threading
import zlib
from typing import Optional, Dict, Any, Callable

class AsyncDiscordGateway:
    """Async Discord Gateway client with zlib-stream compression support"""

    def __init__(self, token: str, client_type: str = "web", compress: bool = True):
        self.token = token
        self.client_type = client_type
        self.compress = compress
        self.ws: Optional[websockets.WebSocketServerProtocol] = None
        self.sequence: Optional[int] = None
        self.session_id: Optional[str] = None
        self.heartbeat_interval: Optional[float] = None
        self.last_heartbeat: float = time.time()
        self.connected = False
        self.identified = False

        # Compression support
        self.decompressor: Optional[zlib.decompressobj] = None
        self.buffer = bytearray()

        # Callbacks
        self.on_message: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_ready: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None
        self.on_close: Optional[Callable[[int, str], None]] = None
        self.on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None
        self.on_payload: Optional[Callable[[Dict[str, Any]], None]] = None

    async def connect(self):
        """Connect to Discord Gateway with optional compression"""
        base_url = "wss://gateway.discord.gg/?v=10&encoding=json"
        url = base_url + ("&compress=zlib-stream" if self.compress else "")

        # Initialize compression if enabled
        if self.compress:
            self.decompressor = zlib.decompressobj()
            self.buffer = bytearray()

        try:
            async with websockets.connect(url) as websocket:
                self.ws = websocket
                self.connected = True
                print(f"🔌 Connected to Discord Gateway {'(compressed)' if self.compress else '(uncompressed)'}")

                # Start heartbeat task
                heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                try:
                    async for message in websocket:
                        if self.compress:
                            await self._handle_compressed_message(message)
                        else:
                            await self._handle_message(message)
                except websockets.exceptions.ConnectionClosed as e:
                    print("🔌 Gateway connection closed")
                    if self.on_close:
                        try:
                            self.on_close(int(getattr(e, "code", 1000) or 1000), str(getattr(e, "reason", "")))
                        except Exception:
                            pass
                finally:
                    heartbeat_task.cancel()
                    self.connected = False

        except Exception as e:
            print(f"❌ Gateway connection error: {e}")
            if self.on_error:
                self.on_error(e)

    async def _handle_compressed_message(self, message: bytes):
        """Handle zlib-stream compressed messages"""
        try:
            # Add new data to buffer
            self.buffer.extend(message)

            # Check if this is the end of a data packet (ends with 0x00 0x00 0xff 0xff)
            if len(message) >= 4 and message[-4:] == b'\x00\x00\xff\xff':
                # Decompress the buffer
                decompressed = self.decompressor.decompress(self.buffer)

                # Handle multiple messages in one packet (split by newlines)
                messages = decompressed.decode('utf-8').strip().split('\n')

                for msg in messages:
                    if msg.strip():
                        await self._handle_message(msg)

                # Clear buffer for next packet
                self.buffer = bytearray()

        except Exception as e:
            print(f"❌ Error decompressing message: {e}")
            # Fallback to treating as uncompressed
            try:
                await self._handle_message(message.decode('utf-8'))
            except:
                print("❌ Failed to handle message as uncompressed too")

    async def _handle_message(self, message: str):
        """Handle incoming gateway messages"""
        try:
            data = json.loads(message)
            op = data.get('op')
            event_type = data.get('t')
            event_data = data.get('d')

            if self.on_payload:
                try:
                    self.on_payload(data)
                except Exception:
                    pass

            # Update sequence
            if 's' in data and data['s'] is not None:
                self.sequence = data['s']

            # Handle different opcodes
            if op == 10:  # Hello
                self.heartbeat_interval = event_data['heartbeat_interval'] / 1000
                await self._identify()
                print(f"📡 Heartbeat interval: {self.heartbeat_interval}s")

            elif op == 11:  # Heartbeat ACK
                self.last_heartbeat = time.time()
                print("💓 Heartbeat acknowledged")

            elif op == 0:  # Dispatch (events)
                await self._handle_event(event_type, event_data)

            elif op == 9:  # Invalid Session
                print("❌ Invalid session, reconnecting...")
                self.identified = False
                await asyncio.sleep(5)
                await self._identify()

            elif op == 7:  # Reconnect
                print("🔄 Gateway requested reconnect")
                return  # This will close the connection and trigger reconnect

        except json.JSONDecodeError:
            print(f"❌ Failed to parse message: {message}")
        except Exception as e:
            print(f"❌ Error handling message: {e}")

    async def _handle_event(self, event_type: str, event_data: Dict[str, Any]):
        """Handle Discord events"""
        if event_type == 'READY':
            self.session_id = event_data.get('session_id')
            user = event_data.get('user', {})
            username = user.get('username', 'Unknown')
            user_id = user.get('id', 'Unknown')
            self.identified = True
            print(f"✅ READY! Logged in as {username} ({user_id})")

            if self.on_ready:
                self.on_ready(event_data)

        elif event_type == 'MESSAGE_CREATE':
            if self.on_message:
                self.on_message(event_data)

        if self.on_event:
            try:
                self.on_event(event_type, event_data)
            except Exception:
                pass

        # Add more event handlers as needed

    async def _identify(self):
        """Send stealthy identify payload with capabilities and client state"""
        if self.identified:
            print("⚠️ Already identified, skipping")
            return

        # Stealth identify payload mimicking Chrome desktop client
        identify_payload = {
            "op": 2,  # Identify
            "d": {
                "token": self.token,
                "capabilities": 16381,  # Modern client capabilities
                "properties": {
                    "os": "Windows",
                    "browser": "Chrome",
                    "device": "",
                    "system_locale": "en-US",
                    "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "browser_version": "120.0.0.0",
                    "os_version": "10",
                    "referrer": "",
                    "referring_domain": "",
                    "referrer_current": "",
                    "referring_domain_current": "",
                    "release_channel": "stable",
                    "client_build_number": 250000,  # Latest build number
                    "client_event_source": None
                },
                "presence": {
                    "status": "online",
                    "since": 0,
                    "activities": [],
                    "afk": False
                },
                "compress": False,  # Let zlib-stream handle compression
                "client_state": {
                    "guild_versions": {},
                    "highest_last_message_id": "0",
                    "read_state_version": 0,
                    "user_guild_settings_version": -1,
                    "user_settings_version": -1,
                    "private_channels_version": "0",
                    "api_code_version": 0
                }
            }
        }

        # Adjust properties based on client type
        if self.client_type == "mobile":
            identify_payload["d"]["properties"].update({
                "os": "Android",
                "browser": "Discord Android",
                "device": "phone",
                "browser_user_agent": "Discord/250000 CFNetwork/1404.0.5 Darwin/22.3.0",
                "browser_version": "250000",
                "os_version": "11"
            })
        elif self.client_type == "web":
            # Keep desktop Chrome properties
            pass

        await self.ws.send(json.dumps(identify_payload))
        print("🔐 Sent stealth identify payload")

    async def _heartbeat_loop(self):
        """Maintain heartbeat to keep connection alive"""
        await asyncio.sleep(self.heartbeat_interval * 0.1)  # Small delay before first heartbeat

        while self.connected:
            if self.heartbeat_interval:
                heartbeat_payload = {
                    "op": 1,  # Heartbeat
                    "d": self.sequence
                }

                try:
                    await self.ws.send(json.dumps(heartbeat_payload))
                    print(f"💓 Sent heartbeat (seq: {self.sequence})")
                    await asyncio.sleep(self.heartbeat_interval)
                except Exception as e:
                    print(f"❌ Heartbeat error: {e}")
                    break
            else:
                await asyncio.sleep(1)

    async def send_message(self, channel_id: str, content: str):
        """Send a message (requires MESSAGE_CREATE permission)"""
        if not self.identified:
            print("❌ Not identified, cannot send message")
            return

        message_payload = {
            "type": 0,
            "content": content,
            "tts": False,
            "flags": 0
        }

        # This would need to be sent via HTTP API, not gateway
        # Gateway is for receiving events, HTTP API for sending
        print(f"📤 Would send message to {channel_id}: {content}")
        print("💡 Note: Messages should be sent via Discord HTTP API, not gateway")

    async def send_json(self, payload: Dict[str, Any]) -> bool:
        """Send a JSON payload over the gateway connection."""
        if not self.ws or not self.connected:
            return False
        try:
            await self.ws.send(json.dumps(payload))
            return True
        except Exception:
            return False

    def run(self):
        """Run the gateway client"""
        asyncio.run(self.connect())

# Example usage
async def main():
    # Replace with your actual token
    token = "YOUR_DISCORD_TOKEN_HERE"

    gateway = AsyncDiscordGateway(token)

    # Set up event handlers
    def on_ready(data):
        print("🎉 Bot is ready!")

    def on_message(data):
        content = data.get('content', '')
        author = data.get('author', {}).get('username', 'Unknown')
        print(f"📨 {author}: {content}")

    gateway.on_ready = on_ready
    gateway.on_message = on_message

    await gateway.connect()

if __name__ == "__main__":
    # Run with: python async_gateway.py
    client = AsyncDiscordGateway("YOUR_TOKEN_HERE")
    client.run()