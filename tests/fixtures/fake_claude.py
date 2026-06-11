#!/usr/bin/env python3
"""Fake claude CLI for real-subprocess executor tests.

Mimics the flags the real claude binary accepts:
  -p <prompt>  --output-format json  --structured-output  --model <model>
Exits 0 and prints a valid legacy-format JSON response.
"""

import argparse
import json
import sys

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("-p", dest="prompt", default="")
parser.add_argument("--output-format", dest="output_format", default="json")
parser.add_argument("--structured-output", action="store_true")
parser.add_argument("--model", dest="model", default="sonnet")
parser.add_argument("--dangerously-skip-permissions", action="store_true")
parser.add_argument("--context", dest="context", default=None)
parser.add_argument("--resume", dest="resume", default=None)
args, _ = parser.parse_known_args()

print(json.dumps({"result": f"echo: {args.prompt}", "tokens_used": 42, "model": args.model}))
sys.exit(0)
