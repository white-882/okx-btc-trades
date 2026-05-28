#!/usr/bin/env python3
"""Wrapper for trader_1m.py with error-resilient OKX client"""
import subprocess, json, sys, os, hmac, base64, hashlib
from datetime import datetime, timezone

# Add the project dir to path
sys.path.insert(0, '/home/administrator/projects/okx-bot2')

# Monkey-patch before importing the trader module
import trader_1m as t

# Save original
_orig_okx_request = t.okx_request

def safe_okx_request(method, path, body=""):
    """Error-resilient OKX request wrapper"""
    try:
        result = _orig_okx_request(method, path, body)
        return result
    except (json.JSONDecodeError, Exception) as e:
        return {"code": "-1", "msg": f"OKX error: {str(e)[:200]}", "data": []}

# Apply monkey-patch
t.okx_request = safe_okx_request

# Also patch the individual functions to be safe
_orig_get_positions = t.get_positions
_orig_get_balance = t.get_balance
_orig_place_order = t.place_order
_orig_close_position = t.close_position

def safe_get_positions():
    try:
        return _orig_get_positions()
    except Exception as e:
        return []

def safe_get_balance():
    try:
        return _orig_get_balance()
    except Exception as e:
        return 0

def safe_place_order(side, sz, pos_side=None):
    try:
        return _orig_place_order(side, sz, pos_side)
    except Exception as e:
        return {"code": "-1", "msg": str(e)}

def safe_close_position(side, sz):
    try:
        return _orig_close_position(side, sz)
    except Exception as e:
        return {"code": "-1", "msg": str(e)}

t.get_positions = safe_get_positions
t.get_balance = safe_get_balance
t.place_order = safe_place_order
t.close_position = safe_close_position

# Run main
if __name__ == '__main__':
    # Single run (not the 5x loop), to give a quick report
    t.main()
