import time
import datetime
import threading
from db_manager import DBManager
from memory_engine import MemoryEngine

VERBATIM_WINDOW = 6
MIN_SUMMARY_BATCH = 4
ACTIVE_SESSION_HARD_LIMIT = 160
SCRATCHPAD_LIMIT = 600

class StateManager:
    def __init__(self):
        self._engine_lock = threading.Lock()
        self.db = DBManager()
        self.memory = MemoryEngine()
        
        self.active_session = self.db.load_history(limit=50)
        self.rolling_summary = "Session just started."
        self.summary_pointer = 0

    @property
    def current_thread_id(self): return self.db.current_thread_id
    @current_thread_id.setter
    def current_thread_id(self, value): self.db.current_thread_id = value
    @property
    def current_persona(self): return self.db.current_persona
    @property
    def scratchpad(self): return self.db.scratchpad
    @scratchpad.setter
    def scratchpad(self, value): self.db.scratchpad = value
    @property
    def user_profile(self): return self.db.user_profile
    @property
    def conn(self): return self.db.conn

    def get_threads(self): return self.db.get_threads()
    def create_thread(self, name): return self.db.create_thread(name)
    def load_history(self, limit=50, thread_id=None): return self.db.load_history(limit=limit, thread_id=thread_id)
    def load_persona(self, persona_name): return self.db.load_persona(persona_name)
    def rename_thread(self, thread_id, new_name): return self.db.rename_thread(thread_id, new_name)
    def delete_thread(self, thread_id): return self.db.delete_thread(thread_id)

    def save_interaction(self, user_msg, ai_msg, internal_note=None):
        timestamp = time.time()
        iso_timestamp = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).isoformat()

        self.active_session.append({"role": "user", "content": user_msg, "iso_timestamp": iso_timestamp})
        self.active_session.append({"role": "assistant", "content": ai_msg, "iso_timestamp": iso_timestamp})

        self.db.save_chat_rows(self.current_thread_id, user_msg, ai_msg, internal_note, iso_timestamp)

        def _bg_save():
            self.memory.save_to_vector_db(user_msg, ai_msg, internal_note, timestamp, self.current_thread_id)
        threading.Thread(target=_bg_save, daemon=True).start()
        self._trim_active_session()

    def _trim_active_session(self):
        if len(self.active_session) <= ACTIVE_SESSION_HARD_LIMIT:
            return
        drop = len(self.active_session) - ACTIVE_SESSION_HARD_LIMIT
        self.active_session = self.active_session[drop:]
        self.summary_pointer = max(0, self.summary_pointer - drop)
        
    def switch_thread(self, new_thread_id):
        with self._engine_lock:
            if new_thread_id == self.current_thread_id: return
            
            if self.current_thread_id:
                self.db.freeze_thread(self.current_thread_id, self.rolling_summary, self.scratchpad)
                
            self.rolling_summary, self.scratchpad = self.db.thaw_thread(new_thread_id)
            self.active_session = self.db.load_history(limit=50, thread_id=new_thread_id)
            self.summary_pointer = 0
            self.db.current_thread_id = new_thread_id