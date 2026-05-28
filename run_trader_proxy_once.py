#!/usr/bin/env python3
"""Run trader_1m.py ONCE with proxy from ~/.bashrc - for cron"""
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

# Quick test: check if OKX is reachable via proxy
test = subprocess.run(
    ['curl', '-s', '--connect-timeout', '10', 'https://www.okx.com/api/v5/public/time'],
    env=env, capture_output=True, text=True, timeout=15
)
okx_works = test.returncode == 0 and test.stdout.strip()

# If OKX works, run 1 iteration of trader; otherwise, fall back to signal-only
if okx_works:
    print("OKX: Reachable via proxy")
    # Patch trader to run just 1 iteration
    code = open('/home/administrator/projects/okx-bot2/trader_1m.py').read()
    # Replace the 5-iteration loop with single call
    code = code.replace(
        "for run in range(5):\n        main()\n        if run < 4:\n            time.sleep(60)",
        "main()"
    )
    # Create temp file
    tmp = '/tmp/trader_1m_once.py'
    with open(tmp, 'w') as f:
        f.write(code)
    r = subprocess.run(
        [sys.executable, tmp],
        env=env, capture_output=True, text=True, timeout=60,
        cwd='/home/administrator/projects/okx-bot2'
    )
    print(r.stdout)
    if r.stderr:
        print("STDERR:", r.stderr[:500], file=sys.stderr)
    os.unlink(tmp)
else:
    print("OKX: UNREACHABLE (even with proxy) — signal analysis only")
    # Run signal check from our existing report script
    r = subprocess.run(
        [sys.executable, '/home/administrator/projects/okx-bot2/report_signal.py'],
        capture_output=True, text=True, timeout=60
    )
    print(r.stdout)
