"""SourceConnector ABC — one connector per input source.

Each connector yields `Document` instances. Hashing, chunking, embedding,
and store upsert are handled by the indexer (Stream 4) so connectors stay
focused on source-specific extraction and never touch the vector store.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Iterator

from src.rag.types import Document


class SourceConnector(ABC):
    source_type: ClassVar[str]

    @abstractmethod
    def iter_documents(self) -> Iterator[Document]:
        """Yield Documents from this source. Per-item failures warn + continue;
        aggregate failures (auth, missing root dir) raise."""
        raise NotImplementedError
