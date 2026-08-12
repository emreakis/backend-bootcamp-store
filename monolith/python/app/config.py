"""Configuration comes from the environment. Never from code.

Twelve-factor, and the reason it matters here: the artifact you run in Session 3 is
identical in dev and prod. Only the environment around it changes. Hard-code one
address and that stops being true.
"""

import os

IMPLEMENTATION = "python"

PORT = int(os.getenv("PORT", "8080"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "./store.db")
SCHEMA_PATH = os.getenv("SCHEMA_PATH", "../../db/schema.sql")
SEED_PATH = os.getenv("SEED_PATH", "../../db/seed.sql")
RESET_DB = os.getenv("RESET_DB", "true").lower() != "false"

# The payment stub is deterministic on purpose. A demo that fails randomly teaches
# nothing; a demo that fails on command teaches one thing at a time.
PAYMENT_DECLINE_OVER_CENTS = int(os.getenv("PAYMENT_DECLINE_OVER_CENTS", "500000"))
PAYMENT_ALWAYS_DECLINE = os.getenv("PAYMENT_ALWAYS_DECLINE", "false").lower() == "true"
