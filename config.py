"""
Settings shared by the agent, the dashboard and the evals.

Kept in one place because they used to be copied into each file, and a
model name written twice is a model name that will eventually differ
between the agent you chat with and the dashboard you read.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent

# Loaded here so that importing config is enough for any entry point to see
# the key. Real environment variables win over .env, which is what lets CI
# or a one-off shell override either setting without editing the file.
load_dotenv(PROJECT_ROOT / ".env")

# Every Claude call in the project -- agent, dashboard analysis, brief,
# themes and the eval judge -- uses this model.
#
# Eval pass rates describe a prompt AND a model together. Change this and
# earlier results stop being comparable, so rerun the evals and record the
# model alongside the numbers.
MODEL = os.environ.get("MARKET_AGENT_MODEL", "claude-sonnet-4-5")
