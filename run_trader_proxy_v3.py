#!/usr/bin/env python3
"""Run trader_1m.py ONCE with proxy + correct credentials"""
import os, sys, re, subprocess, tomllib

bashrc = os.path.expanduser('~/.bashrc')
env = os.environ.copy()
if os.path.exists(bashrc):
    with open(bashrc) as f:
        for line in f:
            m = re.match(r'export\s+(\w+)="?(.*?)"?\s*$', line.strip())
            if m and 'proxy' in m.group(1).lower():
                env[m.group(1)] = m.group(2)
                env[m.group(1).lower()] = m.group(2)

with open(os.path.expanduser('~/.okx/config.toml'), 'rb') as f:
    cfg = tomllib.load(f)['default']
env['OKX_API_KEY'] = cfg['api_key']
env['OKX_SECRET'] = cfg['secret_key']
env['OKX_PASSPHRASE'] = cfg['passphrase']

# Try LIVE mode (no x-simulated-trading header)
code = open('/home/administrator/projects/okx-bot2/trader_1m.py').read()
# Keep DEMO = False (default)

code = code.replace(
    "for run in range(5):\n        main()\n        if run < 4:\n            time.sleep(60)",
    "main()"
)

tmp = '/tmp/trader_1m_v3.py'
with open(tmp, 'w') as f:
    f.write(code)

r = subprocess.run(
    [sys.executable, tmp],
    env=env, capture_output=True, text=True, timeout=90,
    cwd='/home/administrator/projects/okx-bot2'
)
print("Mode: LIVE (DEMO=False)")
print(r.stdout)
if r.stderr:
    for line in r.stderr.strip().split('\n'):
        if 'RuntimeWarning' not in line and 'divide by zero' not in line:
            print("STDERR:", line)

os.unlink(tmp)
