#!/usr/bin/env python3
"""Fake rate-limited CLI for real-subprocess executor tests.

Always exits 1 and writes a rate-limit message to stderr so that
ClaudeExecutor.check_rate_limit() returns True after running it.
"""

import sys

sys.stderr.write("Error: rate limit exceeded — too many requests\n")
sys.exit(1)
