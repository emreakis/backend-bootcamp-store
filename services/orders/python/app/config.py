"""Configuration from the environment. Never from code.

Seven variables, five of them about what to do when somebody else fails. Catalog has
two. That ratio is the price of being the service in the middle.

Note what is NOT here: a hostname anybody typed. `catalog` and `payments` are service
names the platform resolves — compose's DNS today, a Kubernetes Service tomorrow, with
no code change. Hard-coding an address is how you make an image that only runs in one
place.
"""

import os

IMPLEMENTATION = "python"

PORT = int(os.getenv("PORT", "8080"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgres://store:store@localhost:5434/orders")

CATALOG_URL = os.getenv("CATALOG_URL", "http://localhost:8000")
PAYMENTS_ADDR = os.getenv("PAYMENTS_ADDR", "localhost:50051")

# Policy, not guesswork. 2000 ms is a statement about how long a checkout may wait on
# a charge, made by the people who own checkout — not an estimate of how fast payments
# happens to be today.
#
# All four are read here and then, in this starter, quietly ignored. That is exercise 3.
CATALOG_TIMEOUT_MS = int(os.getenv("CATALOG_TIMEOUT_MS", "1000"))
PAYMENTS_TIMEOUT_MS = int(os.getenv("PAYMENTS_TIMEOUT_MS", "2000"))
PAYMENTS_RETRY_MAX = int(os.getenv("PAYMENTS_RETRY_MAX", "2"))
BREAKER_FAILURE_THRESHOLD = int(os.getenv("BREAKER_FAILURE_THRESHOLD", "5"))
BREAKER_RESET_MS = int(os.getenv("BREAKER_RESET_MS", "10000"))
