#!/usr/bin/env python3
"""
Install Piper voice model en_US-lessac-medium
Downloads from HuggingFace if not already installed
"""

import urllib.request
import os
import sys

def install_piper_voice():
    # Create piper voice directory
    piper_home = os.path.expanduser('~/.local/share/piper')
    voice_dir = os.path.join(piper_home, 'en_US-lessac-medium')
    os.makedirs(voice_dir, exist_ok=True)

    voice_name = 'en_US-lessac-medium'
    model_file = os.path.join(voice_dir, f'{voice_name}.onnx')
    config_file = os.path.join(voice_dir, f'{voice_name}.json')

    print(f'[PIPER] Voice directory: {voice_dir}')
    print(f'[PIPER] Checking for existing model...')

    if os.path.exists(model_file) and os.path.exists(config_file):
        print(f'[PIPER] ✓ Voice model already exists')
        return True
    
    print(f'[PIPER] Downloading en_US-lessac-medium voice model...')
    print(f'[PIPER] This is ~50MB and may take 1-2 minutes')
    
    try:
        # Download ONNX model
        model_url = f'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/{voice_name}.onnx'
        print(f'[PIPER] Downloading ONNX model...')
        
        def download_progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                percent = min(100, (downloaded / total_size) * 100)
                print(f'[PIPER] Progress: {percent:.1f}% ({downloaded}/{total_size} bytes)', end='\r')
        
        urllib.request.urlretrieve(model_url, model_file, download_progress)
        print(f'\n[PIPER] ✓ Model downloaded to {model_file}')
        
        # Download JSON config
        config_url = f'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/{voice_name}.json'
        print(f'[PIPER] Downloading JSON config...')
        urllib.request.urlretrieve(config_url, config_file)
        print(f'[PIPER] ✓ Config downloaded to {config_file}')
        
        print('[PIPER] ✓ Voice model installation complete!')
        return True
    except Exception as e:
        print(f'[PIPER] ✗ Error downloading: {e}')
        return False

if __name__ == '__main__':
    success = install_piper_voice()
    sys.exit(0 if success else 1)
