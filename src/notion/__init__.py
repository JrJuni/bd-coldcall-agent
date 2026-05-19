"""Phase 13A - Notion write layer.

This package owns Notion API writes. The existing `src/rag/connectors/
notion.py` stays read-only (RAG ingestion); keeping the two surfaces
separate avoids tangling indexer state with write retries.

Module layout:
  - `writer.py`      - generic NotionWriter (create/update/find_by_id).
  - `config.py`      - load workspace ids from config/notion.yaml + .env.
  - `databases/`     - per-entity property schemas + ORM <-> Notion
                       mappers. One file per entity.
"""
