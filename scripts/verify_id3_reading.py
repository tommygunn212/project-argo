
import os
import sys
import logging

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.music_index import MusicIndex

# Setup logging
logging.basicConfig(level=logging.INFO)

def test_single_file_read():
    print("--- Testing ID3 Tag Reading Capability ---")
    
    # Path to a file likely to exist (from previous dir/logs)
    test_file = r"I:\My Music\music set1\Billboard Top 100 of 1983\Billboard Top 100 of 1983\088 - Moving Pictures - What About Me.mp3"
    
    if not os.path.exists(test_file):
        print(f"File not found: {test_file}")
        # Try finding any mp3 in the root
        for f in os.listdir(r"I:\My Music"):
            if f.endswith(".mp3"):
                test_file = os.path.join(r"I:\My Music", f)
                break
    
    print(f"Testing file: {test_file}")
    
    # Create the indexer (dummy paths, we just want to call the private method)
    indexer = MusicIndex(r"I:\My Music", "dummy_index.json")
    
    # Check mutagen availability
    try:
        from mutagen.easyid3 import EasyID3
        print(f"Mutagen available: Yes")
        
        try:
            tags = EasyID3(test_file)
            print(f"Raw Tags in file: {tags}")
        except Exception as e:
            print(f"Error reading tags locally: {e}")
            
    except ImportError:
        print("Mutagen available: NO")

    # Directly call the record builder
    # _build_track_record is what we modified
    record = indexer._build_track_record(test_file)
    
    if record:
        print("\n[RESULT]")
        print(f"Filename: {record['filename']}")
        print(f"Artist  : {record['artist']} (Source: {'ID3 Tag' if record['artist'] != 'Unknown' else 'Folder'})")
        print(f"Song    : {record['song']}   (Source: {'ID3 Tag' if record['song'] != record['name'] else 'Filename'})")
        print(f"Genre   : {record['genre']}")
        print(f"\nIf 'Artist' looks like a real band name and not a folder name, IT WORKS!")
    else:
        print("Failed to build record.")

if __name__ == "__main__":
    print(f"Python Executable: {sys.executable}")
    test_single_file_read()
