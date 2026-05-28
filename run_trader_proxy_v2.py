#!/usr/bin/env python3
"""Run trader_1m.py ONCE with proxy from bashrc + credentials from config.toml"""
import os, sys, re, subprocess, tomllib

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

# Load OKX credentials from config.toml
with open(os.path.expanduser('~/.okx/config.toml'), 'rb') as f:
    cfg = tomllib.load(f)['default']
env['OKX_API_KEY'] = cfg['api_key']
env['OKX_SECRET'] = cfg['secret_key']
env['OKX_PASSPHRASE'] = cfg['passphrase']

# Check if demo mode
demo = cfg.get('demo', False)
print(f"Mode: {'DEMO (simulated)' if demo else 'LIVE'}")

# Quick OKX connectivity test
test = subprocess.run(
    ['curl', '-s', '--connect-timeout', '10', 'https://www.okx.com/api/v5/public/time'],
    env=env, capture_output=True, text=True, timeout=15
)
if test.returncode != 0 or not test.stdout.strip():
    print("ERROR: OKX unreachable even with proxy")
    # Fallback to signal-only
    r = subprocess.run(
        [sys.executable, '/home/administrator/projects/okx-bot2/report_signal.py'],
        capture_output=True, text=True, timeout=60
    )
    print(r.stdout)
    sys.exit(1)

print("OKX: Reachable via proxy")

# Create single-run version of trader with DEMO flag set correctly
code = open('/home/administrator/projects/okx-bot2/trader_1m.py').read()

# Set DEMO based on config
if demo:
    code = code.replace('DEMO = False', 'DEMO = True')

# Replace 5-iteration loop with single call
code = code.replace(
    "for run in range(5):\n        main()\n        if run < 4:\n            time.sleep(60)",
    "main()"
)

tmp = '/tmp/trader_1m_v2.py'
with open(tmp, 'w') as f:
    f.write(code)

r = subprocess.run(
    [sys.executable, tmp],
    env=env, capture_output=True, text=True, timeout=90,
    cwd='/home/administrator/projects/okx-bot2'
)
print(r.stdout)
if r.stderr:
    # Filter out the known RuntimeWarning
    for line in r.stderr.strip().split('\n'):
        if 'RuntimeWarning' not in line and 'divide by zero' not in line:
            print("STDERR:", line, file=sys.stderr)

os.unlink(tmp)
