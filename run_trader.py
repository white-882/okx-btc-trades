import tomllib, os, sys
sys.path.insert(0, '/home/administrator/projects/okx-bot2')
with open('/home/administrator/.okx/config.toml','rb') as f:
    c = tomllib.load(f)['default']
os.environ['OKX_API_KEY'] = c['api_key']
os.environ['OKX_SECRET'] = c['secret_key']
os.environ['OKX_PASSPHRASE'] = c['passphrase']
exec(open('/home/administrator/projects/okx-bot2/trader_1m.py').read())
