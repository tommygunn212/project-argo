#!/usr/bin/env python3
"""
Test WebSocket connection to ARGO backend
"""
import asyncio
import pytest
import websockets
import json
import sys

@pytest.mark.asyncio
async def test_websocket():
    uri = "ws://localhost:8001/ws"
    
    print(f"[WEBSOCKET TEST] Connecting to {uri}...")
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"[WEBSOCKET TEST] ✓ Connected!")
            
            # Try to receive messages from the server
            print(f"[WEBSOCKET TEST] Listening for messages (5 seconds)...")
            
            try:
                for i in range(5):
                    msg = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    try:
                        data = json.loads(msg)
                        print(f"[WEBSOCKET TEST] Message {i+1}: {data}")
                    except:
                        print(f"[WEBSOCKET TEST] Message {i+1}: {msg[:100]}")
            except asyncio.TimeoutError:
                print(f"[WEBSOCKET TEST] No messages received (backend may be idle)")
            
            print(f"[WEBSOCKET TEST] ✓ WebSocket is working!")
            return True
            
    except ConnectionRefusedError:
        print(f"[WEBSOCKET TEST] ✗ Connection refused - backend not running on port 8001")
        return False
    except Exception as e:
        print(f"[WEBSOCKET TEST] ✗ Error: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_websocket())
    sys.exit(0 if result else 1)
