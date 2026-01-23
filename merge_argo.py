import os

# ONLY include these specific extensions
ALLOWED_EXTS = {'.py', '.md', '.env', '.txt', '.yaml', '.yml'}
# STRICTLY ignore these directories
FORBIDDEN_DIRS = {
    '.venv', '.git', '__pycache__', 'node_modules', 
    'audio', 'logs', 'backups', 'temp', 'dist', 'build'
}

output_filename = "ARGO_SLIM_CONTEXT.txt"
file_count = 0

print(f"🧹 Cleaning and packing {os.getcwd()}...")

with open(output_filename, "w", encoding="utf-8") as outfile:
    for root, dirs, files in os.walk("."):
        # Modify dirs in-place to skip forbidden folders
        dirs[:] = [d for d in dirs if d not in FORBIDDEN_DIRS]
        
        for file in files:
            if any(file.endswith(ext) for ext in ALLOWED_EXTS):
                # Don't include the output file itself
                if file == output_filename or file == "merge_argo.py":
                    continue
                    
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as infile:
                        content = infile.read()
                        # Skip files that are individually too large (likely logs)
                        if len(content) > 500000: # 500kb limit per file
                            print(f"⚠️ Skipped {file} (Too large, likely a log)")
                            continue
                            
                        outfile.write(f"\n\n{'='*30}\nFILE: {filepath}\n{'='*30}\n\n")
                        outfile.write(content)
                        file_count += 1
                        print(f"✅ Added: {filepath}")
                except Exception as e:
                    print(f"❌ Error {filepath}: {e}")

print(f"\n✨ Done! Packed {file_count} files. The new file should be much smaller (likely < 2MB).")
