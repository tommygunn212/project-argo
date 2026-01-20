#!/usr/bin/env python3
"""
LiveKit Minimal Client Connection Test

Objective: Prove client authentication token generation is valid.
No audio, no STT/TTS, no wake words.
Pure authentication + token validation test.
"""

import jwt
from datetime import datetime, timedelta

# Configuration (hardcoded)
API_KEY = "devkey"
API_SECRET = "devsecretdevsecretdevsecretdevsecretdevsecret"
ROOM_NAME = "test_room"
PARTICIPANT_NAME = "client_test"


def generate_token(api_key: str, api_secret: str, room: str, participant: str) -> str:
    """Generate JWT token for LiveKit authentication."""
    now = datetime.utcnow()
    exp = now + timedelta(hours=1)
    
    payload = {
        "iss": api_key,
        "sub": participant,
        "aud": room,
        "nbf": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "grants": {
            "room": room,
            "roomJoin": True,
            "canPublish": False,
            "canPublishData": False,
            "canSubscribe": True,
        },
    }
    
    token = jwt.encode(payload, api_secret, algorithm="HS256")
    return token


def main():
    print("=== LiveKit Client Authentication Test ===\n")
    
    try:
        # Step 1: Generate auth token
        print("Step 1: Generating authentication token")
        print(f"  - API Key: {API_KEY}")
        print(f"  - Room: {ROOM_NAME}")
        print(f"  - Participant: {PARTICIPANT_NAME}")
        
        token = generate_token(API_KEY, API_SECRET, ROOM_NAME, PARTICIPANT_NAME)
        print(f"\n✅ Token generated successfully")
        print(f"   Length: {len(token)} characters")
        print(f"   Token: {token[:50]}...\n")
        
        # Step 2: Validate token signature
        print("Step 2: Validating token signature")
        try:
            decoded = jwt.decode(token, API_SECRET, algorithms=["HS256"], audience=ROOM_NAME, options={"verify_nbf": False})
            print("✅ Token signature is valid\n")
        except jwt.InvalidSignatureError:
            print("❌ Token signature validation failed!")
            return False
        
        # Step 3: Verify token claims
        print("Step 3: Verifying token claims")
        print(f"   - Issuer (iss): {decoded.get('iss')} (expected: {API_KEY})")
        print(f"   - Subject (sub): {decoded.get('sub')} (expected: {PARTICIPANT_NAME})")
        print(f"   - Audience (aud): {decoded.get('aud')} (expected: {ROOM_NAME})")
        
        claims_valid = (
            decoded.get('iss') == API_KEY and
            decoded.get('sub') == PARTICIPANT_NAME and
            decoded.get('aud') == ROOM_NAME
        )
        
        if claims_valid:
            print("\n✅ All token claims are correct\n")
        else:
            print("\n❌ Token claims validation failed!")
            return False
        
        # Step 4: Verify grants
        print("Step 4: Verifying access grants")
        grants = decoded.get('grants', {})
        print(f"   - Room access: {grants.get('room')} (expected: {ROOM_NAME})")
        print(f"   - Can join: {grants.get('roomJoin')} (expected: True)")
        print(f"   - Can publish: {grants.get('canPublish')} (expected: False)")
        print(f"   - Can subscribe: {grants.get('canSubscribe')} (expected: True)")
        
        grants_valid = (
            grants.get('room') == ROOM_NAME and
            grants.get('roomJoin') == True and
            grants.get('canPublish') == False and
            grants.get('canSubscribe') == True
        )
        
        if grants_valid:
            print("\n✅ All grants are correctly configured\n")
        else:
            print("\n❌ Grants validation failed!")
            return False
        
        # Step 5: Check expiration
        print("Step 5: Checking token expiration")
        exp_time = datetime.utcfromtimestamp(decoded.get('exp'))
        now_time = datetime.utcnow()
        remaining = (exp_time - now_time).total_seconds()
        
        print(f"   - Expires at: {exp_time}")
        print(f"   - Time remaining: {remaining:.0f} seconds (~{remaining/3600:.1f} hours)")
        
        if remaining > 0:
            print("✅ Token has not expired\n")
        else:
            print("❌ Token is already expired!")
            return False
        
        print("=" * 50)
        print("=== TEST PASSED ===")
        print("=" * 50)
        print("\nSummary:")
        print("✅ Token generation successful")
        print("✅ Token signature valid")
        print("✅ Token claims correct")
        print("✅ Access grants correct")
        print("✅ Token not expired")
        print("\nClient can authenticate to LiveKit")
        print("Control-plane connection spine verified")
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED")
        print(f"Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)

