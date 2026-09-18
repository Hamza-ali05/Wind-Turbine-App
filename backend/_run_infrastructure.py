import logging

from app.services.infrastructure import acquire_infrastructure

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

summary = acquire_infrastructure(force=True)
print("SUMMARY", summary)
