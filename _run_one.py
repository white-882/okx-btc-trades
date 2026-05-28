#!/usr/bin/env python3
"""Load proxy + keys, run trader main() once"""
import os, sys, re, tomllib

bashrc = os.path.expanduser('~/.bashrc')
if os.path.exists(bashrc):
    with open(bashrc) as f:
        for line in f:
            m = re.match(r'export\s+(\w+)="?(.*?)"?\s*$', line.strip())
            if m and 'proxy' in m.group(1).lower():
                os.environ[m.group(1)] = m.group(2)

sys.path.insert(0, '/home/administrator/projects/okx-bot2')
with open(os.path.expanduser('~/.okx/config.toml'), 'rb') as f:
    c = tomllib.load(f)['default']
os.environ['OKX_API_KEY'] = c['api_key']
os.environ['OKX_SECRET'] = c['secret_key']
os.environ['OKX_PASSPHRASE'] = c['passphrase']

# Read trader_1m.py but replace the __main__ block to run once
with open('/home/administrator/projects/okx-bot2/trader_1m.py') as f:
    code = f.read()

# Remove the __main__ block and run main() once
code = code.split("if __name__=='__main__':")[0] + "\nmain()\n"
exec(code)
