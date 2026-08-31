# db_manager.py — SQLite persistence, thread CRUD, persona JSON loader
# Part of Osia Build 2.0 (Phase 1.8 refactor)
#
# This module owns ALL disk I/O for structured data:
#   - SQLite connection, schema, chat history rows
#   - Thread freeze/thaw (summary + scratchpad persistence)
#   - Persona JSON file loading from personas/
#   - User profile loading from user_profile.json

import os
import json
import sqlite3

# --- CONFIGURATION ---
SQL_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "my_chat_history.db")
PERSONAS_DIR = "personas"


class DBManager:
    """Manages SQLite chat storage, thread state, and persona configuration."""

    def __init__(self, sql_db_path=None, personas_dir=None):
        self.sql_db_path = sql_db_path or SQL_DB_PATH
        self.personas_dir = personas_dir or os.path.join(os.path.dirname(os.path.dirname(__file__)), PERSONAS_DIR)

        # Thread state
        self.current_thread_id = 1

        # Persona state
        self.current_persona = {}

        # Boot
        self._init_sqlite()
        self.user_profile = self._load_profile()
        self.scratchpad = self._load_latest_scratchpad() or "No current internal notes."
        self.load_persona("default")

    # -------------------------------------------------------------------------
    # INTERNAL: Schema + Boot
    # -------------------------------------------------------------------------
    def _init_sqlite(self):
        self.conn = sqlite3.connect(self.sql_db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                last_summary TEXT DEFAULT '',
                last_scratchpad TEXT DEFAULT '',
                created_at TEXT
            )
        ''')

        # Ensure a default thread exists so the app never boots to nothing
        self.cursor.execute(
            "INSERT OR IGNORE INTO threads (id, name, created_at) VALUES (1, 'Starting Thread', datetime('now', 'utc'))"
        )

        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER DEFAULT 1,
                role TEXT,
                content TEXT,
                iso_timestamp TEXT,
                FOREIGN KEY(thread_id) REFERENCES threads(id)
            )
        """)
        self.conn.commit()

    def _load_profile(self):
        try:
            profile_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "user_profile.json")
            if os.path.exists(profile_path):
                with open(profile_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            return "User Profile: Developer building a context-aware AI system."
        except Exception:
            return "User Profile: Unknown."

    def _load_latest_scratchpad(self):
        """Load the most recent system_note (scratchpad dump) from chat_history."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT content FROM chat_history WHERE role = 'system_note' "
                "ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row and row[0]:
                print("   -> Loaded persisted scratchpad from DB.")
                return row[0]
        except Exception as e:
            print(f"⚠️ Failed to load scratchpad: {e}")
        return None

    # -------------------------------------------------------------------------
    # CHAT HISTORY: Save + Load
    # -------------------------------------------------------------------------
    def save_chat_rows(self, thread_id, user_msg, ai_msg, internal_note, iso_timestamp):
        """Insert user/assistant (and optional system_note) rows into chat_history."""
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO chat_history (thread_id, role, content, iso_timestamp) VALUES (?, ?, ?, ?)",
            (thread_id, "user", user_msg, iso_timestamp),
        )
        cursor.execute(
            "INSERT INTO chat_history (thread_id, role, content, iso_timestamp) VALUES (?, ?, ?, ?)",
            (thread_id, "assistant", ai_msg, iso_timestamp),
        )
        if internal_note:
            cursor.execute(
                "INSERT INTO chat_history (thread_id, role, content, iso_timestamp) VALUES (?, ?, ?, ?)",
                (thread_id, "system_note", internal_note, iso_timestamp),
            )
        self.conn.commit()

    def load_history(self, limit=50, thread_id=None):
        """Fetch chat history for a thread, ordered oldest-first."""
        if thread_id is None:
            thread_id = self.current_thread_id
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT role, content, iso_timestamp FROM chat_history "
                "WHERE role != 'system_note' AND thread_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (thread_id, limit),
            )
            rows = cursor.fetchall()
            return [{"role": r[0], "content": r[1], "iso_timestamp": r[2]} for r in reversed(rows)]
        except Exception as e:
            print(f"❌ Error loading history: {e}")
            return []

    # -------------------------------------------------------------------------
    # THREADS: CRUD + Freeze/Thaw
    # -------------------------------------------------------------------------
    def get_threads(self):
        """Returns list of tuples: [(id, name, created_at), ...] ordered newest first."""
        try:
            self.cursor.execute("SELECT id, name, created_at FROM threads ORDER BY id DESC")
            return self.cursor.fetchall()
        except Exception as e:
            print(f"⚠️ Failed to fetch threads: {e}")
            return [(1, "General", None)]

    def create_thread(self, name):
        """Creates a new thread and returns its ID."""
        try:
            self.cursor.execute("INSERT INTO threads (name) VALUES (?)", (name,))
            self.conn.commit()
            new_id = self.cursor.lastrowid
            print(f"✨ Created Thread {new_id}: '{name}'")
            return new_id
        except Exception as e:
            print(f"❌ Failed to create thread: {e}")
            return None

    def freeze_thread(self, thread_id, summary, scratchpad):
        """Persist the rolling summary + scratchpad for a thread before switching away."""
        try:
            self.cursor.execute(
                "UPDATE threads SET last_summary = ?, last_scratchpad = ? WHERE id = ?",
                (summary, scratchpad, thread_id),
            )
            self.conn.commit()
        except Exception as e:
            print(f"⚠️ Failed to freeze thread state: {e}")

    def rename_thread(self, thread_id, new_name):
        """Rename an existing thread."""
        try:
            self.cursor.execute(
                "UPDATE threads SET name = ? WHERE id = ?",
                (new_name, thread_id),
            )
            self.conn.commit()
            print(f"✏️ Renamed Thread {thread_id} to '{new_name}'")
            return True
        except Exception as e:
            print(f"❌ Failed to rename thread: {e}")
            return False

    def delete_thread(self, thread_id):
        """Delete a thread and all its chat history rows."""
        if thread_id == self.current_thread_id:
            print("⚠️ Cannot delete the currently active thread.")
            return False
        try:
            self.cursor.execute(
                "DELETE FROM chat_history WHERE thread_id = ?", (thread_id,)
            )
            self.cursor.execute(
                "DELETE FROM threads WHERE id = ?", (thread_id,)
            )
            self.conn.commit()
            print(f"🗑️ Deleted Thread {thread_id} and its history.")
            return True
        except Exception as e:
            print(f"❌ Failed to delete thread: {e}")
            return False

    def get_thread_message_count(self, thread_id):
        """Return the number of user+assistant messages in a thread."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM chat_history WHERE thread_id = ? AND role != 'system_note'",
                (thread_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def thaw_thread(self, thread_id):
        """Load the saved summary + scratchpad for a thread. Returns (summary, scratchpad)."""
        try:
            self.cursor.execute(
                "SELECT last_summary, last_scratchpad FROM threads WHERE id = ?",
                (thread_id,),
            )
            row = self.cursor.fetchone()
            if row:
                summary = row[0] if row[0] else "Session just started."
                scratchpad = row[1] if row[1] else "No current internal notes."
                return summary, scratchpad
            else:
                print("⚠️ Thread not found in DB, starting fresh.")
                return "Session just started.", "No current internal notes."
        except Exception as e:
            print(f"❌ Error loading thread state: {e}")
            return "Session just started.", "No current internal notes."

    # -------------------------------------------------------------------------
    # PERSONAS
    # -------------------------------------------------------------------------
    def load_persona(self, persona_name):
        """Loads a JSON persona file from the personas/ directory."""
        filename = persona_name if persona_name.endswith(".json") else f"{persona_name}.json"
        path = os.path.join(self.personas_dir, filename)

        try:
            with open(path, "r", encoding="utf-8") as f:
                self.current_persona = json.load(f)
            print(f"🎭 Persona switched to: {self.current_persona.get('name', 'Unknown')}")
            return True
        except FileNotFoundError:
            print(f"⚠️ Persona file not found: {path}. Falling back to hardcoded default.")
            self.current_persona = {
                "role_definition": "You are Osia, a helpful AI assistant with persistent memory.",
                "style_guidelines": ["Be helpful and clear.", "Use a casual friendly tone."],
            }
            return False

    # -------------------------------------------------------------------------
    # CLEANUP
    # -------------------------------------------------------------------------
    def close(self):
        """Close the SQLite connection gracefully."""
        if self.conn:
            try:
                self.conn.close()
                print("🔌 SQLite connection closed.")
            except Exception:
                pass
