import json
import asyncio
import websockets
import time
import threading

class VoiceClient:
    def __init__(self, api_client, token):
        self.api = api_client
        self.token = token
        self.voice_ws = None
        self.gateway_ws = None
        self.voice_thread = None
        self.gateway_thread = None
        self.running = False
        self.gateway_running = False
        self.voice_gateway_url = None
        self.session_id = None
        self.token_v = None
        self.endpoint = None
        self.guild_id = None
        self.channel_id = None
        self.user_id = None
        self.sequence = 0
        self.heartbeat_interval = None
        self.ssrc = None
        self.secret_key = None
        self.speaking = False
        self.is_dm_call = False
        self.call_channel_id = None
        self.voice_data_received = False
        self.gateway_connected = False
    
    def connect_to_voice(self, target_id):
        self.channel_id = target_id
        
        try:
            channel_info = self.api.request("GET", f"/channels/{target_id}")
            if channel_info and channel_info.status_code == 200:
                data = channel_info.json()
                channel_type = data.get('type', 0)
                
                if channel_type == 2:
                    self.is_dm_call = False
                    self.guild_id = data.get('guild_id')
                    print(f"Joining server voice: {target_id}")
                    return self._connect_guild_voice(target_id)
                elif channel_type in [1, 3]:
                    self.is_dm_call = True
                    self.guild_id = None
                    self.call_channel_id = target_id
                    print(f"Starting DM call: {target_id}")
                    return self._connect_dm_voice(target_id)
                else:
                    print(f"Not a voice channel")
                    return False
            else:
                print(f"No channel info")
                return False
        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def _connect_guild_voice(self, channel_id):
        if not self.guild_id:
            print(f"No guild ID")
            return False
        
        if hasattr(self.api, 'user_id'):
            self.user_id = self.api.user_id
        
        print(f"1. Updating voice state for guild {self.guild_id}")
        response = self.api.request("PATCH", f"/guilds/{self.guild_id}/voice-states/@me", data={
            "channel_id": channel_id,
            "self_mute": False,
            "self_deaf": False
        })
        
        if response and response.status_code in (200, 204):
            print(f"2. Voice state updated, starting gateway")
            self.gateway_thread = threading.Thread(target=self._gateway_thread_func, args=(channel_id,), daemon=True)
            self.gateway_thread.start()
            
            for i in range(10):
                if self.gateway_connected:
                    break
                time.sleep(1)
            
            if self.gateway_connected:
                print(f"3. Gateway connected, waiting for voice data")
                for i in range(15):
                    if self.endpoint and self.session_id and self.token_v:
                        print(f"4. Got all voice data, connecting to voice gateway")
                        self.voice_thread = threading.Thread(target=self._voice_connect_thread, daemon=True)
                        self.voice_thread.start()
                        time.sleep(3)
                        return True
                    time.sleep(1)
                print(f"Timeout waiting for voice data")
                return False
            else:
                print(f"Gateway not connected")
                return False
        else:
            print(f"Voice state failed: {response.status_code if response else 'No response'}")
            return False
    
    def _connect_dm_voice(self, channel_id):
        self.call_channel_id = channel_id
        print(f"Starting DM call gateway")
        self.gateway_thread = threading.Thread(target=self._gateway_thread_func, args=(channel_id,), daemon=True)
        self.gateway_thread.start()
        time.sleep(2)
        return True
    
    def _gateway_thread_func(self, channel_id):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._connect_to_gateway(channel_id))
    
    async def _connect_to_gateway(self, channel_id):
        try:
            print(f"Gateway: Connecting...")
            ws = await websockets.connect(
                "wss://gateway.discord.gg/?v=10&encoding=json",
                max_size=None,
                ping_interval=30,
                ping_timeout=30
            )
            
            self.gateway_ws = ws
            self.gateway_connected = True
            self.gateway_running = True
            
            await self._gateway_identify(ws)
            
            if self.is_dm_call:
                await self._start_dm_call(ws, channel_id)
            
            async for message in ws:
                await self._handle_gateway_message(ws, message)
                
        except Exception as e:
            print(f"Gateway error: {e}")
    
    async def _gateway_identify(self, ws):
        identify = {
            "op": 2,
            "d": {
                "token": self.token,
                "properties": {
                    "$os": "windows",
                    "$browser": "Chrome",
                    "$device": "desktop"
                },
                "presence": {
                    "status": "online",
                    "activities": [],
                    "afk": False
                },
                "compress": False,
                "large_threshold": 250,
                "intents": 32509
            }
        }
        await ws.send(json.dumps(identify))
        print(f"Gateway: Identified")
    
    async def _start_dm_call(self, ws, channel_id):
        call_data = {
            "op": 4,
            "d": {
                "guild_id": None,
                "channel_id": str(channel_id),
                "self_mute": False,
                "self_deaf": False,
                "self_video": False
            }
        }
        await ws.send(json.dumps(call_data))
        print(f"Gateway: Started DM call")
    
    async def _handle_gateway_message(self, ws, message):
        try:
            data = json.loads(message)
            op = data.get("op")
            t = data.get("t")
            
            if op == 10:
                self.heartbeat_interval = data["d"]["heartbeat_interval"] / 1000
                asyncio.create_task(self._gateway_heartbeat(ws))
            
            elif op == 0:
                if t == "VOICE_STATE_UPDATE":
                    voice_data = data["d"]
                    if voice_data.get("user_id") == str(self.user_id):
                        self.session_id = voice_data.get("session_id")
                        self.token_v = voice_data.get("token")
                        print(f"Gateway: Got session_id {self.session_id}")
                
                elif t == "VOICE_SERVER_UPDATE":
                    server_data = data["d"]
                    if server_data.get("guild_id") == str(self.guild_id) or self.is_dm_call:
                        self.endpoint = server_data.get("endpoint")
                        self.token_v = server_data.get("token")
                        if self.endpoint:
                            self.endpoint = self.endpoint.replace(':443', '')
                            print(f"Gateway: Got endpoint {self.endpoint}")
            
        except Exception as e:
            print(f"Gateway message error: {e}")
    
    async def _gateway_heartbeat(self, ws):
        while self.gateway_running:
            try:
                heartbeat_msg = {"op": 1, "d": self.sequence}
                await ws.send(json.dumps(heartbeat_msg))
                self.sequence += 1
                await asyncio.sleep(self.heartbeat_interval)
            except:
                break
    
    def _voice_connect_thread(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._connect_voice_gateway())
    
    async def _connect_voice_gateway(self):
        if not self.endpoint or not self.token_v or not self.session_id:
            print(f"Missing voice data")
            return
        
        print(f"Voice: Connecting to {self.endpoint}")
        
        try:
            ws = await websockets.connect(
                f"wss://{self.endpoint}/?v=4",
                max_size=None,
                ping_interval=30,
                ping_timeout=30
            )
            self.voice_ws = ws
            self.running = True
            
            await self._voice_identify(ws)
            
            async for message in ws:
                await self._handle_voice_message(ws, message)
                
        except Exception as e:
            print(f"Voice error: {e}")
        finally:
            self.running = False
    
    async def _voice_identify(self, ws):
        server_id = str(self.guild_id) if self.guild_id else None
        identify = {
            "op": 0,
            "d": {
                "server_id": server_id,
                "user_id": str(self.user_id),
                "session_id": self.session_id,
                "token": self.token_v
            }
        }
        await ws.send(json.dumps(identify))
        print(f"Voice: Identified")
    
    async def _handle_voice_message(self, ws, message):
        try:
            data = json.loads(message)
            op = data.get('op')
            
            if op == 2:
                self.ssrc = data['d']['ssrc']
                self.secret_key = data['d']['secret_key']
                self.heartbeat_interval = data['d']['heartbeat_interval'] / 1000
                
                print(f"VOICE CONNECTED!")
                asyncio.create_task(self._voice_heartbeat(ws))
                await self._select_protocol(ws)
                
            elif op == 4:
                await self._speaking(ws, True)
                
            elif op == 8:
                self.heartbeat_interval = data['d']['heartbeat_interval'] / 1000
                
        except Exception as e:
            print(f"Voice message error: {e}")
    
    async def _voice_heartbeat(self, ws):
        while self.running:
            try:
                heartbeat_msg = {"op": 3, "d": None}
                await ws.send(json.dumps(heartbeat_msg))
                await asyncio.sleep(self.heartbeat_interval)
            except:
                break
    
    async def _select_protocol(self, ws):
        select_protocol = {
            "op": 1,
            "d": {
                "protocol": "udp",
                "data": {
                    "address": "127.0.0.1",
                    "port": 0,
                    "mode": "xsalsa20_poly1305"
                }
            }
        }
        await ws.send(json.dumps(select_protocol))
    
    async def _speaking(self, ws, speaking):
        speaking_msg = {
            "op": 5,
            "d": {
                "speaking": 1 if speaking else 0,
                "delay": 0,
                "ssrc": self.ssrc
            }
        }
        await ws.send(json.dumps(speaking_msg))
        self.speaking = speaking
    
    def disconnect(self):
        self.running = False
        self.gateway_running = False

        if self.gateway_ws:
            try:
                self.gateway_ws.close()
            except:
                pass
            self.gateway_ws = None

        if self.voice_ws:
            try:
                self.voice_ws.close()
            except:
                pass
            self.voice_ws = None

        if self.guild_id and not self.is_dm_call:
            try:
                self.api.request("PATCH", f"/guilds/{self.guild_id}/voice-states/@me", data={
                    "channel_id": None
                })
                print(f"Left voice")
            except:
                pass

class SimpleVoice:
    def __init__(self, api_client, token):
        self.api = api_client
        self.token = token
        self.active_connections = {}
    
    def join_vc(self, *args, **kwargs):
        if args and isinstance(args[0], str) and args[0].isdigit():
            channel_id = args[0]
        elif kwargs.get('channel_id'):
            channel_id = kwargs['channel_id']
        else:
            return False
        
        connection_key = f"channel_{channel_id}"
        
        if self.active_connections:
            self.leave_vc()
        
        print(f"Join VC: {channel_id}")
        voice_client = VoiceClient(self.api, self.token)
        success = voice_client.connect_to_voice(channel_id)
        
        if success:
            self.active_connections[connection_key] = voice_client
            time.sleep(3)
            return True
        return False
    
    def leave_vc(self, *args, **kwargs):
        if args and isinstance(args[0], str) and args[0].isdigit():
            channel_id = args[0]
        elif kwargs.get('channel_id'):
            channel_id = kwargs['channel_id']
        else:
            channel_id = None
        
        if channel_id:
            connection_key = f"channel_{channel_id}"
            if connection_key in self.active_connections:
                success = self.active_connections[connection_key].disconnect()
                del self.active_connections[connection_key]
                return success
            return False
        else:
            if not self.active_connections:
                return False
            success = True
            for key, client in list(self.active_connections.items()):
                if not client.disconnect():
                    success = False
                del self.active_connections[key]
            return success
    
    def is_in_voice(self, *args, **kwargs):
        if args and isinstance(args[0], str) and args[0].isdigit():
            channel_id = args[0]
        elif kwargs.get('channel_id'):
            channel_id = kwargs['channel_id']
        else:
            channel_id = None
        
        if channel_id:
            connection_key = f"channel_{channel_id}"
            return connection_key in self.active_connections
        return len(self.active_connections) > 0

    def set_video(self, channel_id=None, enabled=True):
        """Toggle camera on/off in a voice channel."""
        client = None
        if channel_id:
            client = self.active_connections.get(f"channel_{channel_id}")
        elif self.active_connections:
            client = next(iter(self.active_connections.values()))
        
        if not client:
            return False, "Not in a voice channel"
        
        try:
            if client.guild_id and not client.is_dm_call:
                data = {
                    "channel_id": str(client.channel_id),
                    "self_mute": False,
                    "self_deaf": False,
                    "self_video": enabled
                }
                resp = self.api.request("PATCH", f"/guilds/{client.guild_id}/voice-states/@me", data=data)
            else:
                import asyncio, json
                payload = json.dumps({
                    "op": 4,
                    "d": {
                        "guild_id": None,
                        "channel_id": str(client.call_channel_id),
                        "self_mute": False,
                        "self_deaf": False,
                        "self_video": enabled
                    }
                })
                if client.gateway_ws:
                    asyncio.run_coroutine_threadsafe(
                        client.gateway_ws.send(payload),
                        asyncio.get_event_loop()
                    )
            return True, "Camera " + ("enabled" if enabled else "disabled")
        except Exception as e:
            return False, str(e)

    def set_stream(self, channel_id=None, enabled=True):
        """Toggle screen share / Go Live in a voice channel."""
        client = None
        if channel_id:
            client = self.active_connections.get(f"channel_{channel_id}")
        elif self.active_connections:
            client = next(iter(self.active_connections.values()))

        if not client:
            return False, "Not in a voice channel"

        try:
            guild_id = str(client.guild_id) if client.guild_id else None
            ch_id = str(client.channel_id)
            import json

            if enabled:
                payload = json.dumps({
                    "op": 18,
                    "d": {
                        "type": "guild",
                        "guild_id": guild_id,
                        "channel_id": ch_id,
                        "preferred_region": None
                    }
                })
            else:
                payload = json.dumps({
                    "op": 22,
                    "d": {
                        "guild_id": guild_id,
                        "channel_id": ch_id
                    }
                })

            if client.gateway_ws:
                import asyncio
                loop = asyncio.new_event_loop()
                loop.run_until_complete(client.gateway_ws.send(payload))
                loop.close()
            return True, "Stream " + ("started" if enabled else "stopped")
        except Exception as e:
            return False, str(e)
