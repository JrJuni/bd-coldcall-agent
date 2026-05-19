"""Phase 13+ ORM model package.

Each entity gets its own module (rfp_answer.py, notion_sync_map.py, ...).
Modules register themselves against `src.api.orm.Base.metadata` by being
imported here - this is the canonical list consulted by Alembic's
autogenerate.
"""
from src.api.models import discovery as _discovery  # noqa: F401
from src.api.models import interaction as _interaction  # noqa: F401
from src.api.models import news_run as _news_run  # noqa: F401
from src.api.models import notion_sync_map as _notion_sync_map  # noqa: F401
from src.api.models import rag_summary as _rag_summary  # noqa: F401
from src.api.models import rfp_answer as _rfp_answer  # noqa: F401
from src.api.models import run as _run  # noqa: F401
from src.api.models import target as _target  # noqa: F401
from src.api.models import workspace as _workspace  # noqa: F401
