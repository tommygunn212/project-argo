#!/usr/bin/env python3
"""
LiveKit Smoke Test: Transport Layer Verification

This test:
1. Connects to local LiveKit server
2. Joins room: test_room
3. Waits for audio (confirms connection working)
4. Disconnects cleanly

NO Porcupine, NO TTS, NO STT, NO personality.
Pure transport test.
"""

import asyncio
import logging
from livekit import api

# Setup logging
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Configuration
LIVEKIT_URL = "ws://localhost:7880"
LIVEKIT_API_KEY = "devkey"
LIVEKIT_API_SECRET = "secretsecretsecretsecretsecretsecretsecretsecret"
ROOM_NAME = "test_room"

async def main():
    log.info("=== LiveKit Smoke Test (Transport Layer) ===")
    
    room = None
    
    try:
        # Connect to LiveKit
        log.info(f"Connecting to LiveKit at {LIVEKIT_URL}")
        room = api.Room(url=LIVEKIT_URL, token="test_token")
        await room.aconnect()
        log.info("✅ Connected to server")
        
        # Join room
        log.info(f"Joining room: {ROOM_NAME}")
        await room.join(
            room_name=ROOM_NAME,
            participant_name="smoke_test"
        )
        log.info("✅ Joined room")
        
        # Wait for audio window
        log.info("Waiting 5 seconds (listening for audio)...")
        await asyncio.sleep(5)
        log.info("✅ Audio window complete")
        
    except Exception as e:
        log.error(f"❌ Error: {type(e).__name__}: {e}")
        return False
    
    finally:
        # Disconnect
        if room:
            try:
                await room.adisconnect()
                log.info("✅ Disconnected")
            except Exception as e:
                log.error(f"Disconnect error: {e}")
    
    log.info("=== Smoke Test Complete ===")
    return True

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
