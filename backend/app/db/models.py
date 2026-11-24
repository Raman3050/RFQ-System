"""Import every ORM model here so Alembic autogenerate can see the full metadata.

Models are added from Phase 1 onwards.
"""

from app.db.base import Base

__all__ = ["Base"]
