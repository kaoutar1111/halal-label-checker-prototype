"""
Database module for Halal Label Checker.
Stores scan history in SQLite.
"""

import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ScanDatabase:
    """
    SQLite database for storing scan history.
    """
    
    def __init__(self, db_path: str = "halal_checker.db"):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_database(self):
        """Create database tables if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_path TEXT,
                    raw_text TEXT,
                    ocr_confidence REAL,
                    verdict TEXT,
                    verdict_details TEXT,
                    highlighted_text TEXT,
                    match_results TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scans_created_at 
                ON scans(created_at DESC)
            """)
            
            conn.commit()
            
        logger.info(f"Database initialized at {self.db_path}")
    
    def save_scan(
        self,
        image_path: str,
        raw_text: str,
        ocr_confidence: float,
        verdict: str,
        verdict_details: Dict,
        highlighted_text: Dict,
        match_results: List[Dict]
    ) -> int:
        """
        Save a scan to the database.
        
        Returns:
            ID of the inserted scan
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO scans (
                    image_path, raw_text, ocr_confidence, verdict,
                    verdict_details, highlighted_text, match_results
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                image_path,
                raw_text,
                ocr_confidence,
                verdict,
                json.dumps(verdict_details, ensure_ascii=False),
                json.dumps(highlighted_text, ensure_ascii=False),
                json.dumps(match_results, ensure_ascii=False)
            ))
            
            conn.commit()
            scan_id = cursor.lastrowid
            
        logger.info(f"Saved scan with ID: {scan_id}")
        return scan_id
    
    def get_scan(self, scan_id: int) -> Optional[Dict]:
        """
        Get a single scan by ID.
        
        Returns:
            Scan data as dict or None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM scans WHERE id = ?", (scan_id,))
            row = cursor.fetchone()
            
            if row:
                return self._row_to_dict(row)
            
        return None
    
    def get_recent_scans(self, limit: int = 50) -> List[Dict]:
        """
        Get recent scans.
        
        Args:
            limit: Maximum number of scans to return
        
        Returns:
            List of scan dicts
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM scans 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (limit,))
            
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]
    
    def delete_scan(self, scan_id: int) -> bool:
        """
        Delete a scan by ID.
        
        Returns:
            True if deleted, False if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM scans WHERE id = ?", (scan_id,))
            deleted = cursor.rowcount > 0
            
            conn.commit()
            
        return deleted
    
    def clear_all_scans(self):
        """Delete all scans from database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM scans")
            conn.commit()
            
        logger.info("All scans deleted")
    
    def get_statistics(self) -> Dict:
        """Get scan statistics."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) as total FROM scans")
            total = cursor.fetchone()["total"]
            
            cursor.execute("""
                SELECT verdict, COUNT(*) as count 
                FROM scans 
                GROUP BY verdict
            """)
            verdict_counts = {row["verdict"]: row["count"] for row in cursor.fetchall()}
            
            cursor.execute("SELECT AVG(ocr_confidence) as avg_conf FROM scans")
            avg_confidence = cursor.fetchone()["avg_conf"] or 0.0
            
            return {
                "total_scans": total,
                "verdict_counts": verdict_counts,
                "average_confidence": avg_confidence
            }
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """Convert sqlite3.Row to dictionary."""
        data = dict(row)
        
        # Parse JSON fields
        for field in ["verdict_details", "highlighted_text", "match_results"]:
            if field in data and data[field]:
                try:
                    data[field] = json.loads(data[field])
                except json.JSONDecodeError:
                    data[field] = {}
            else:
                data[field] = {}
        
        # Format timestamp
        if "created_at" in data and data["created_at"]:
            data["created_at"] = str(data["created_at"])
        
        return data


# Module-level convenience
_default_db: Optional[ScanDatabase] = None


def get_database(db_path: str = "halal_checker.db") -> ScanDatabase:
    """Get or create default database instance."""
    global _default_db
    if _default_db is None:
        _default_db = ScanDatabase(db_path)
    return _default_db
