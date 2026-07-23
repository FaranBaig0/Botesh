import sqlite3
from datetime import datetime

class JobDB:
    """Persistent SQLite database connection, deduplication & target manager."""

    def __init__(self, path: str = "jobs.db"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        # Enable WAL mode and set busy timeout to prevent database locks
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA busy_timeout = 30000;")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_jobs (
                job_id VARCHAR(255),
                url_source VARCHAR(500),
                first_seen TIMESTAMP,
                content_hash VARCHAR(64),
                PRIMARY KEY (job_id, url_source)
            )
            """
        )
        # Migrate existing database to add content_hash column if missing
        try:
            self.conn.execute("ALTER TABLE seen_jobs ADD COLUMN content_hash VARCHAR(64)")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracked_targets (
                channel_id INTEGER PRIMARY KEY,
                label TEXT NOT NULL,
                user_query TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    def get_job_status(self, job_id: str, url_source: str, current_hash: str) -> str:
        """Returns 'NEW' if not seen, 'UPDATED' if hash changed, or 'SEEN' if already processed."""
        row = self.conn.execute(
            "SELECT content_hash FROM seen_jobs WHERE job_id = ? AND url_source = ?",
            (job_id, url_source),
        ).fetchone()
        
        if row is None:
            return "NEW"
            
        stored_hash = row[0]
        if stored_hash is None:
            # Update legacy database record with the new hash silently to avoid double posting older posts
            self.conn.execute(
                "UPDATE seen_jobs SET content_hash = ? WHERE job_id = ? AND url_source = ?",
                (current_hash, job_id, url_source),
            )
            self.conn.commit()
            return "SEEN"
            
        if stored_hash != current_hash:
            return "UPDATED"
            
        return "SEEN"

    def is_new(self, job_id: str, url_source: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen_jobs WHERE job_id = ? AND url_source = ?",
            (job_id, url_source),
        ).fetchone()
        return row is None

    def mark_seen(self, job_id: str, url_source: str, content_hash: str = None):
        self.conn.execute(
            """
            INSERT INTO seen_jobs (job_id, url_source, first_seen, content_hash)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(job_id, url_source) DO UPDATE SET
                content_hash = excluded.content_hash,
                first_seen = excluded.first_seen
            """,
            (job_id, url_source, datetime.now().isoformat(), content_hash),
        )
        self.conn.commit()

    def add_target(self, channel_id: int, label: str, user_query: str):
        """Adds or updates a tracked search target in SQLite."""
        self.conn.execute(
            """
            INSERT INTO tracked_targets (channel_id, label, user_query)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                label = excluded.label,
                user_query = excluded.user_query
            """,
            (channel_id, label, user_query),
        )
        self.conn.commit()

    def remove_target(self, channel_id: int) -> bool:
        """Removes a tracked target by channel_id."""
        cursor = self.conn.execute(
            "DELETE FROM tracked_targets WHERE channel_id = ?",
            (channel_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def get_all_targets(self) -> list[dict]:
        """Returns list of tracked targets formatted for the scraper."""
        cursor = self.conn.execute(
            "SELECT channel_id, label, user_query FROM tracked_targets"
        )
        rows = cursor.fetchall()
        return [
            {"channel_id": r[0], "label": r[1], "userQuery": r[2]}
            for r in rows
        ]

    def seed_initial_targets(self, targets: list[dict]):
        """Seeds initial targets if tracked_targets table is empty."""
        existing = self.get_all_targets()
        if not existing and targets:
            for t in targets:
                cid = t.get("channel_id")
                label = t.get("label", "default")
                query = t.get("userQuery", "python")
                if cid:
                    self.add_target(cid, label, query)

    def cleanup_old_jobs(self, days: int = 30) -> int:
        """Removes seen job records older than specified days."""
        cursor = self.conn.execute(
            """
            DELETE FROM seen_jobs
            WHERE first_seen < datetime('now', '-' || ? || ' days')
            """,
            (days,)
        )
        self.conn.commit()
        if cursor.rowcount > 0:
            print(f"🧹 [Database] Cleaned up {cursor.rowcount} seen_jobs records older than {days} days.")
        return cursor.rowcount

    def count_recent_jobs(self, hours: int = 1) -> int:
        """Counts how many jobs were marked seen in the last specified hours."""
        row = self.conn.execute(
            """
            SELECT COUNT(*) FROM seen_jobs
            WHERE first_seen >= datetime('now', '-' || ? || ' hours')
            """,
            (hours,)
        ).fetchone()
        return row[0] if row else 0

    def close(self):
        self.conn.close()

