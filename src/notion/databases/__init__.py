"""Phase 13+ - per-entity Notion database modules.

Each module describes one Notion database:
  - Property schema (used by bootstrap_notion.py to create the DB).
  - ORM <-> Notion property mappers.
  - Page body builder (children blocks).

Add a new entity by dropping a new module and listing it in
`src/notion/databases/__init__.py` if global iteration is needed
(currently not - bootstrap calls each module explicitly).
"""
