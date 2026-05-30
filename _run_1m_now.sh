#!/bin/bash
. /home/administrator/.bashrc
export OKX_SECRET=*** OKX_PASSPHRASE" = "$OKX_PASSPHRASE"
echo "OKX_SECRET_KEY = ${OKX_SECRET_KEY:0:8}..."
echo "http_proxy = $http_proxy"
cd /home/administrator/projects/okx-bot2
python3 trader_1m.py
