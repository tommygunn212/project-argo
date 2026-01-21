#!/usr/bin/env python3
"""
Play an Edge-TTS voice sample.

This generates audio from Edge-TTS and plays it through your speakers.
"""

import asyncio
import io
import numpy as np
import sounddevice
import edge_tts


async def play_voice_sample():
    """Generate and play a voice sample."""
    
    text = "Yes?"
    print(f"Generating voice sample: '{text}'")
    print("Using voice: en-US-AvaNeural")
    print()
    
    # Generate audio with Edge-TTS
    communicate = edge_tts.Communicate(text, voice="en-US-AvaNeural")
    
    audio_data = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.write(chunk["data"])
    
    audio_bytes = audio_data.getvalue()
    print(f"✅ Generated {len(audio_bytes)} bytes of audio")
    print()
    
    # Convert bytes to numpy array
    # Edge-TTS outputs MP3, so we need to decode it
    print("Decoding audio...")
    
    try:
        from pydub import AudioSegment
        
        # Load MP3 from bytes
        audio = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
        
        # Convert to numpy array
        samples = np.array(audio.get_array_of_samples())
        
        # Handle stereo -> mono if needed
        if audio.channels == 2:
            samples = samples.reshape((-1, 2))
            samples = samples.mean(axis=1)
        
        # Normalize to -1.0 to 1.0 range
        samples = samples.astype(np.float32) / 32768.0
        
        sample_rate = audio.frame_rate
        print(f"Sample rate: {sample_rate} Hz")
        print(f"Duration: {len(samples) / sample_rate:.2f} seconds")
        print()
        
    except ImportError:
        print("Note: pydub not installed, using raw PCM instead")
        print("Install with: pip install pydub")
        print()
        
        # Edge-TTS can also output raw PCM, but MP3 is default
        # For now, just show the size
        print(f"Audio data size: {len(audio_bytes)} bytes")
        print()
        return
    
    # Play the audio
    print("🔊 Playing audio...")
    print()
    
    sounddevice.play(samples, samplerate=sample_rate, blocking=True)
    
    print()
    print("✅ Playback complete!")


if __name__ == "__main__":
    asyncio.run(play_voice_sample())
