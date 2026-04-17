#!/usr/bin/env python3
"""
Discord Gateway Compression Comparison
Shows the difference between compressed and uncompressed connections
"""

import asyncio
import json
from async_gateway import AsyncDiscordGateway

async def test_connection(compress: bool):
    """Test a connection with or without compression"""
    print(f"\n{'='*50}")
    print(f"Testing {'COMPRESSED' if compress else 'UNCOMPRESSED'} connection")
    print(f"{'='*50}")

    with open('config.json', 'r') as f:
        config = json.load(f)
        token = config.get('token')

    if not token or token == "token here":
        print("❌ Please set your token in config.json")
        return

    gateway = AsyncDiscordGateway(token, client_type="web", compress=compress)

    def on_ready(data):
        user = data.get('user', {})
        print(f"✅ Connected as {user.get('username')}#{user.get('discriminator', '0')}")
        print(f"🗜️ Compression: {'Enabled (zlib-stream)' if compress else 'Disabled'}")

    gateway.on_ready = on_ready

    try:
        # Run for 30 seconds to test
        await asyncio.wait_for(gateway.connect(), timeout=30.0)
    except asyncio.TimeoutError:
        print("⏰ Test completed (30s timeout)")
    except KeyboardInterrupt:
        print("\n👋 Test interrupted")
    except Exception as e:
        print(f"❌ Error: {e}")

async def main():
    print("🧪 Discord Gateway Compression Test")
    print("This will test both compressed and uncompressed connections")

    # Test uncompressed first
    await test_connection(compress=False)

    # Wait a bit between tests
    await asyncio.sleep(2)

    # Test compressed
    await test_connection(compress=True)

    print(f"\n{'='*50}")
    print("📊 RESULTS:")
    print("- Compressed: Lower latency, stealthier, recommended")
    print("- Uncompressed: Simpler, good for testing")
    print("- Use compression for production bots!")
    print(f"{'='*50}")

if __name__ == "__main__":
    asyncio.run(main())