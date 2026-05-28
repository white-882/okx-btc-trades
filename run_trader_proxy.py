#!/usr/bin/env python3
"""Run trader_1m.py with proxy from ~/.bashrc"""
import os, sys, re, subprocess

# Load proxy from bashrc
bashrc = os.path.expanduser('~/.bashrc')
env = os.environ.copy()
if os.path.exists(bashrc):
    with open(bashrc) as f:
        for line in f:
            m = re.match(r'export\s+(\w+)="?(.*?)"?\s*$', line.strip())
            if m and 'proxy' in m.group(1).lower():
                env[m.group(1)] = m.group(2)
                env[m.group(1).lower()] = m.group(2)

# Run trader_1m.py as subprocess with proxy env
r = subprocess.run(
    [sys.executable, '/home/administrator/projects/okx-bot2/trader_1m.py'],
    env=env, capture_output=True, text=True, timeout=120,
    cwd='/home/administrator/projects/okx-bot2'
)
print(r.stdout)
if r.stderr:
    print(r.stderr, file=sys.stderr)
sys.exit(r.returncode)
