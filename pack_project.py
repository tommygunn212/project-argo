import os

# Files to ignore (logs, git, virtual envs, binaries, audio)
IGNORE_DIRS = {'.git', '__pycache__', 'venv', 'env', '.idea', '.vscode', 'logs', 'audio', 'porcupine_key'}
IGNORE_EXTENSIONS = {'.pyc', '.wav', '.mp3', '.exe', '.dll', '.so', '.ppn', '.onnx'}
# Files to explicitly include
INCLUDE_EXTENSIONS = {'.py', '.json', '.md', '.txt', '.bat', '.sh', '.env'}

def pack_project():
    output_file = "argo_full_code.txt"
    
    with open(output_file, 'w', encoding='utf-8') as outfile:
        # Write a file tree first
        outfile.write("=== PROJECT FILE STRUCTURE ===\n")
        for root, dirs, files in os.walk("."):
            # Modify dirs in-place to skip ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            level = root.replace(os.getcwd(), '').count(os.sep)
            indent = ' ' * 4 * (level)
            outfile.write('{}{}/\n'.format(indent, os.path.basename(root)))
            subindent = ' ' * 4 * (level + 1)
            for f in files:
                if any(f.endswith(ext) for ext in INCLUDE_EXTENSIONS):
                    outfile.write('{}{}\n'.format(subindent, f))
        
        outfile.write("\n\n=== FILE CONTENTS ===\n\n")

        # Walk again to write contents
        for root, dirs, files in os.walk("."):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for filename in files:
                if any(filename.endswith(ext) for ext in INCLUDE_EXTENSIONS):
                    filepath = os.path.join(root, filename)
                    
                    # specific exclusion for the output file itself and the packer
                    if filename in ["argo_full_code.txt", "pack_project.py"]:
                        continue

                    outfile.write(f"\n{'='*60}\n")
                    outfile.write(f"FILE PATH: {filepath}\n")
                    outfile.write(f"{'='*60}\n")
                    
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as infile:
                            outfile.write(infile.read())
                    except Exception as e:
                        outfile.write(f"[Error reading file: {e}]")
                    
                    outfile.write("\n")

    print(f"Done! All code packed into: {output_file}")

if __name__ == "__main__":
    pack_project()
