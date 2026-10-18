#!/usr/bin/env python3
"""Explicit local/LAN startup; .env data is parsed, never evaluated as shell code."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import socket
import subprocess
import uvicorn

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lan",action="store_true",help="Listen on all interfaces for same-network phone trial")
    parser.add_argument("--port",type=int,default=8767)
    parser.add_argument("--data-dir",help="Override the environment data directory (default: var/service)")
    args=parser.parse_args()
    from reversecad.visual_adviser import env_values
    for key,value in env_values(ROOT / '.env').items():
        os.environ.setdefault(key,value)
    if args.data_dir:
        os.environ["REVERSECAD_DATA_DIR"] = str((ROOT / args.data_dir).resolve())
    else:
        os.environ.setdefault("REVERSECAD_DATA_DIR",str(ROOT / "var/service"))
    for key in ["OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS"]:
        os.environ.setdefault(key,"2")
    from reversecad.service import app
    host="0.0.0.0" if args.lan else "127.0.0.1"
    try:
        local_name=subprocess.check_output(["scutil","--get","LocalHostName"],text=True).strip()+".local"
    except (OSError,subprocess.CalledProcessError):
        local_name=socket.gethostname()
    print(f"ReverseCAD: http://{'127.0.0.1' if not args.lan else local_name}:{args.port}",flush=True)
    if os.environ.get("REVERSECAD_PAIRING_TOKEN"):
        print("Pairing token: using the private server environment override (value not displayed)",flush=True)
    else:
        print(f"Pairing token file (keep private): {Path(os.environ['REVERSECAD_DATA_DIR']) / 'pairing-token'}",flush=True)
    if args.lan:
        print("Phone: use this Mac's reachable .local hostname or LAN IP. HTTP development mode is for a trusted local network; use HTTPS for shared/public networks.",flush=True)
    print("Live reasoning configured: " + str(bool(os.environ.get("OPENAI_API_KEY"))),flush=True)
    uvicorn.run(app,host=host,port=args.port,access_log=False,log_level="info")

if __name__=="__main__": main()
