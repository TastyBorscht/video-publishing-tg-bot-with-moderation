"""
Database module for video submission bot.
Handles all database operations with SQLite using parameterized queries.
"""
import aiosqlite
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None

    async def connect(self):
        """Initialize database connection and create tables if needed."""
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row
        await self._create_tables()
        logger.info(f"Database connected: {self.db_path}")

    async def close(self):
        """Close database connection."""
        if self.db:
            await self.db.close()
            logger.info("Database connection closed")

    async def _create_tables(self):
        """Create tables and indexes if they don't exist."""
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                is_anonymous BOOLEAN NOT NULL,
                status TEXT NOT NULL,
                scheduled_time TIMESTAMP,
                moderation_message_id INTEGER,
                user_message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                published_at TIMESTAMP,
                rejected_at TIMESTAMP
            )
        """)

        # Create blacklist table
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS blacklist (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                added_by INTEGER NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reason TEXT
            )
        """)

        # Create indexes for performance
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_status ON videos(status)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_time ON videos(scheduled_time)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_created_at ON videos(created_at)"
        )

        await self.db.commit()
        logger.info("Database tables and indexes created/verified")

    async def insert_video(
        self,
        file_id: str,
        user_id: int,
        username: Optional[str],
        is_anonymous: bool,
        status: str = "pending",
        user_message_id: Optional[int] = None
    ) -> int:
        """Insert a new video submission. Returns the video ID."""
        cursor = await self.db.execute(
            """
            INSERT INTO videos
            (file_id, user_id, username, is_anonymous, status, user_message_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_id, user_id, username, is_anonymous, status, user_message_id)
        )
        await self.db.commit()
        return cursor.lastrowid

    async def update_status(
        self,
        video_id: int,
        status: str,
        **kwargs
    ) -> None:
        """Update video status and optional fields."""
        # Build dynamic update query based on kwargs
        fields = ["status = ?"]
        values = [status]

        if "is_anonymous" in kwargs:
            fields.append("is_anonymous = ?")
            values.append(kwargs["is_anonymous"])

        if "moderation_message_id" in kwargs:
            fields.append("moderation_message_id = ?")
            values.append(kwargs["moderation_message_id"])

        if "file_id" in kwargs:
            fields.append("file_id = ?")
            values.append(kwargs["file_id"])

        if "scheduled_time" in kwargs:
            fields.append("scheduled_time = ?")
            values.append(kwargs["scheduled_time"])

        if "published_at" in kwargs:
            fields.append("published_at = ?")
            values.append(kwargs["published_at"])

        if "rejected_at" in kwargs:
            fields.append("rejected_at = ?")
            values.append(kwargs["rejected_at"])

        values.append(video_id)

        query = f"UPDATE videos SET {', '.join(fields)} WHERE id = ?"
        await self.db.execute(query, values)
        await self.db.commit()

    async def get_video_by_id(self, video_id: int) -> Optional[Dict[str, Any]]:
        """Get video record by ID."""
        cursor = await self.db.execute(
            "SELECT * FROM videos WHERE id = ?",
            (video_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_video_by_moderation_message(
        self,
        moderation_message_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get video record by moderation message ID."""
        cursor = await self.db.execute(
            "SELECT * FROM videos WHERE moderation_message_id = ?",
            (moderation_message_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_next_queued_video(self) -> Optional[Dict[str, Any]]:
        """Get the next video in queue (FIFO by created_at)."""
        cursor = await self.db.execute(
            """
            SELECT * FROM videos
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT 1
            """,
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_pending_videos(self) -> List[Dict[str, Any]]:
        """Get all pending videos."""
        cursor = await self.db.execute(
            """
            SELECT * FROM videos
            WHERE status = 'pending'
            ORDER BY created_at ASC
            """,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_scheduled_videos(self) -> List[Dict[str, Any]]:
        """Get all scheduled videos that haven't been published yet."""
        cursor = await self.db.execute(
            """
            SELECT * FROM videos
            WHERE status = 'scheduled'
            AND scheduled_time IS NOT NULL
            ORDER BY scheduled_time ASC
            """,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_video(self, video_id: int) -> None:
        """Delete a video record (only for timeout/cleanup cases)."""
        await self.db.execute(
            "DELETE FROM videos WHERE id = ?",
            (video_id,)
        )
        await self.db.commit()

    async def get_pending_videos_by_user_message(
        self,
        user_id: int,
        user_message_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get pending video by user message ID."""
        cursor = await self.db.execute(
            """
            SELECT * FROM videos
            WHERE user_id = ?
            AND user_message_id = ?
            AND status = 'pending'
            """,
            (user_id, user_message_id)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    # ============================================================================
    # Blacklist methods
    # ============================================================================

    async def is_blacklisted(self, user_id: int) -> bool:
        """Check if a user is blacklisted."""
        cursor = await self.db.execute(
            "SELECT 1 FROM blacklist WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        return row is not None

    async def add_to_blacklist(
        self,
        user_id: int,
        added_by: int,
        username: Optional[str] = None,
        reason: Optional[str] = None
    ) -> None:
        """Add a user to the blacklist."""
        await self.db.execute(
            """
            INSERT OR REPLACE INTO blacklist (user_id, username, added_by, reason)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, username, added_by, reason)
        )
        await self.db.commit()

    async def remove_from_blacklist(self, user_id: int) -> bool:
        """Remove a user from the blacklist. Returns True if user was blacklisted."""
        cursor = await self.db.execute(
            "DELETE FROM blacklist WHERE user_id = ?",
            (user_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def clear_blacklist(self) -> int:
        """Clear the entire blacklist. Returns number of users removed."""
        cursor = await self.db.execute("DELETE FROM blacklist")
        await self.db.commit()
        return cursor.rowcount

    async def get_blacklist(self) -> List[Dict[str, Any]]:
        """Get all blacklisted users."""
        cursor = await self.db.execute(
            """
            SELECT * FROM blacklist
            ORDER BY added_at DESC
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
