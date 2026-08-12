"""Configuration from the environment. Never from code.

`DATABASE_URL` points at a database that belongs to this service and to nothing else.
Nobody outside this container has these credentials, and nothing outside the catalog
service should ever want them — that is what "database per service" means in practice.
"""

import os

IMPLEMENTATION = "python"

PORT = int(os.getenv("PORT", "8000"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgres://store:store@localhost:5433/catalog")
