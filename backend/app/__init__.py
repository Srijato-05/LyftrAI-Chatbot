"""Lyftr AI Chatbot backend package."""

import os

# Avoid ~10s remote GitHub fetch on import in offline/restricted environments.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

