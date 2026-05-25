"""Semantic memory system for Ouroboros.

Provides long-term, never-forget memory with entity linking and multi-signal retrieval.
"""

import sqlite3
import json
import re
import datetime
from typing import Optional, List, Dict, Any


class SemanticMemory:
    """SQLite-based semantic memory with FTS5 full-text search."""

    def __init__(self, db_path: str = "memory.db"):
        """Initialize semantic memory.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self._create_tables()

    def _create_tables(self):
        """Create FTS5 virtual table for memories."""
        # Main memories table with FTS5
        self.conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memories
            USING fts5(
                id UNINDEXED,
                text,
                created_at UNINDEXED,
                metadata UNINDEXED,
                entities,
                tags UNINDEXED
            )
            """
        )

        # Entity index for fast entity lookups
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entity_index (
                entity TEXT PRIMARY KEY,
                memory_ids TEXT,
                last_updated TIMESTAMP
            )
            """
        )

        self.conn.commit()

    def _extract_entities(self, text: str) -> List[str]:
        """Extract entities from text using regex.

        Extracts:
        - Capitalized words (proper nouns)
        - Numbers
        - Common entity patterns

        Args:
            text: Input text.

        Returns:
            List of extracted entities.
        """
        # Match capitalized words, numbers, and common patterns
        patterns = [
            r"\b([A-Z][a-z]+)\b",  # Individual capitalized words
            r"\b(\d{4}-\d{2}-\d{2})\b",  # ISO dates
            r"\b(\d+)\b",  # Numbers
        ]

        entities = []
        for pattern in patterns:
            matches = re.findall(pattern, text)
            entities.extend(matches)

        # Remove duplicates and sort
        return sorted(list(set(entities)))

    def add_memory(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> int:
        """Add a memory to the database.

        Args:
            text: Memory text content.
            metadata: Optional metadata dict.
            tags: Optional list of tags.

        Returns:
            Memory ID.
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        entities = self._extract_entities(text)
        meta_str = json.dumps(metadata or {}, ensure_ascii=False)
        tags_str = ",".join(tags or [])
        entities_str = ",".join(entities)

        cursor = self.conn.execute(
            """
            INSERT INTO memories (text, created_at, metadata, entities, tags)
            VALUES (?, ?, ?, ?, ?)
            """,
            (text, now, meta_str, entities_str, tags_str),
        )
        self.conn.commit()

        memory_id = cursor.lastrowid

        # Update entity index
        for entity in entities:
            self.conn.execute(
                """
                INSERT INTO entity_index (entity, memory_ids, last_updated)
                VALUES (?, ?, ?)
                ON CONFLICT(entity) DO UPDATE SET
                    memory_ids = memory_ids || "," || ?,
                    last_updated = ?
                """,
                (entity, str(memory_id), now, str(memory_id), now),
            )
        self.conn.commit()

        return memory_id

    def get_memories(
        self, query: str, limit: int = 10, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Search memories by keyword using FTS5.

        Args:
            query: Search query.
            limit: Max results.
            offset: Result offset.

        Returns:
            List of matching memories.
        """
        cursor = self.conn.execute(
            """
            SELECT rowid, text, created_at, metadata, entities, tags
            FROM memories
            WHERE memories MATCH ?
            ORDER BY rank
            LIMIT ? OFFSET ?
            """,
            (query, limit, offset),
        )

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "id": row[0],
                    "text": row[1],
                    "created_at": row[2],
                    "metadata": json.loads(row[3]),
                    "entities": row[4].split(",") if row[4] else [],
                    "tags": row[5].split(",") if row[5] else [],
                }
            )

        return results

    def search_by_entity(
        self, entity: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search memories by entity.

        Args:
            entity: Entity to search for.
            limit: Max results.

        Returns:
            List of memories containing the entity.
        """
        cursor = self.conn.execute(
            """
            SELECT rowid, text, created_at, metadata, entities, tags
            FROM memories
            WHERE entities LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (f"%{entity}%", limit),
        )

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "id": row[0],
                    "text": row[1],
                    "created_at": row[2],
                    "metadata": json.loads(row[3]),
                    "entities": row[4].split(",") if row[4] else [],
                    "tags": row[5].split(",") if row[5] else [],
                }
            )

        return results

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most recent memories.

        Args:
            limit: Max results.

        Returns:
            List of recent memories.
        """
        cursor = self.conn.execute(
            """
            SELECT rowid, text, created_at, metadata, entities, tags
            FROM memories
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "id": row[0],
                    "text": row[1],
                    "created_at": row[2],
                    "metadata": json.loads(row[3]),
                    "entities": row[4].split(",") if row[4] else [],
                    "tags": row[5].split(",") if row[5] else [],
                }
            )

        return results

    def close(self):
        """Close database connection."""
        self.conn.close()
