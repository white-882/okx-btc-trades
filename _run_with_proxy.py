#!/usr/bin/env python3
"""Wrapper: load proxy from .bashrc and run trader_1m.py"""
import os, sys, re, tomllib

bashrc = os.path.expanduser('~/.bashrc')
if os.path.exists(bashrc):
    with open(bashrc) as f:
        for line in f:
            m = re.match(r'export\s+(\w+)="?(.*?)"?\s*$', line.strip())
            if m and 'proxy' in m.group(1).lower():
                os.environ[m.group(1)] = m.group(2)

# Also set lowercase variants that curl uses
for k, v in list(os.environ.items()):
    if 'PROXY' in k:
        os.environ[k.lower()] = v

sys.path.insert(0, '/home/administrator/projects/okx-bot2')
with open(os.path.expanduser('~/.okx/config.toml'), 'rb') as f:
    c = tomllib.load(f)['default']
os.environ['OKX_API_KEY'] = c['api_key']
os.environ['OKX_SECRET'] = c['secret_key']
os.environ['OKX_PASSPHRASE'] = c['passphrase']

print("Proxy env:", {k:v for k,v in os.environ.items() if 'proxy' in k.lower()}, flush=True)

with open('/home/administrator/projects/okx-bot2/trader_1m.py') as f:
    exec(f.read())
