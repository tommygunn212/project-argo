#!/usr/bin/env python3
"""Find where Piper stores voice models"""

import os

# Check common locations
locations = [
    os.path.expanduser('~/.local/share/piper'),
    os.path.expanduser('~/.cache/piper'),
    os.getcwd() + '/.piper',
]

print('Checking voice model locations:')
for loc in locations:
    exists = 'EXISTS' if os.path.exists(loc) else 'not found'
    print(f'  {loc}: {exists}')
    if os.path.exists(loc):
        try:
            for item in os.listdir(loc):
                full_path = os.path.join(loc, item)
                if os.path.isdir(full_path):
                    files = os.listdir(full_path)
                    print(f'    {item}/ ({len(files)} files)')
                else:
                    print(f'    {item}')
        except:
            pass

# Check PIPER_HOME environment variable
piper_home = os.environ.get('PIPER_HOME')
if piper_home:
    print(f'\nPIPER_HOME env var: {piper_home}')
