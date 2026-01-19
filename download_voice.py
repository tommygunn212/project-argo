#!/usr/bin/env python3
"""
Download specific Piper voice model
Usage: python download_voice.py <voice_name>
Example: python download_voice.py en_GB-alan
"""

import sys
import urllib.request
import os
from pathlib import Path

# Voice models available from Piper
VOICE_MODELS = {
    "en_US-amy": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx",
    "en_US-lessac": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
    "en_GB-alan": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/en_GB-alan-medium.onnx",
    "en_GB-alba": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alba/medium/en_GB-alba-medium.onnx",
}

def download_voice(voice_name):
    """Download voice model to piper directory"""
    
    if voice_name not in VOICE_MODELS:
        print(f"❌ Voice '{voice_name}' not found")
        print(f"Available: {', '.join(VOICE_MODELS.keys())}")
        return False
    
    url = VOICE_MODELS[voice_name]
    
    # Determine output path
    piper_dir = Path(__file__).parent / "audio" / "piper"
    piper_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{voice_name}-medium.onnx"
    output_path = piper_dir / filename
    
    print(f"📥 Downloading {voice_name}...")
    print(f"   URL: {url}")
    print(f"   To: {output_path}")
    
    try:
        # Download with progress
        def progress_hook(block_num, block_size, total_size):
            downloaded = block_num * block_size
            percent = min(downloaded * 100 / total_size, 100)
            mb_downloaded = downloaded / (1024 * 1024)
            mb_total = total_size / (1024 * 1024)
            print(f"\r   Progress: {percent:.1f}% ({mb_downloaded:.1f}/{mb_total:.1f} MB)", end="")
        
        urllib.request.urlretrieve(url, output_path, progress_hook)
        
        if output_path.exists():
            size_mb = output_path.stat().st_size / (1024 * 1024)
            print(f"\n✅ Downloaded {voice_name} ({size_mb:.1f} MB)")
            return True
        else:
            print(f"\n❌ Download failed")
            return False
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python download_voice.py <voice_name>")
        print(f"Available voices: {', '.join(VOICE_MODELS.keys())}")
        sys.exit(1)
    
    voice = sys.argv[1]
    success = download_voice(voice)
    sys.exit(0 if success else 1)
