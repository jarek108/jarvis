import json
import os
from typing import List, Dict, Any, Optional

class Session:
    def __init__(self, session_id: str, storage_path: Optional[str] = None):
        self.session_id = session_id
        self.storage_path = storage_path
        self.history: List[Dict[str, Any]] = []
        self.context: Dict[str, Any] = {}
        self.active_mode: Optional[str] = None

    def add_turn(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        self.history.append({
            "role": role,
            "content": content,
            "metadata": metadata or {}
        })

    def save(self):
        if not self.storage_path:
            return
        
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        data = {
            "session_id": self.session_id,
            "history": self.history,
            "context": self.context,
            "active_mode": self.active_mode
        }
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    @classmethod
    def load(cls, storage_path: str) -> "Session":
        if not os.path.exists(storage_path):
            # Return a fresh session if file missing, assuming ID from filename
            session_id = os.path.basename(storage_path).replace(".json", "")
            return cls(session_id, storage_path)
            
        with open(storage_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        session = cls(data["session_id"], storage_path)
        session.history = data.get("history", [])
        session.context = data.get("context", {})
        session.active_mode = data.get("active_mode")
        return session

class SessionManager:
    def __init__(self, sessions_dir: str):
        self.sessions_dir = sessions_dir
        os.makedirs(self.sessions_dir, exist_ok=True)
        self.active_sessions: Dict[str, Session] = {}

    def get_session(self, session_id: str) -> Session:
        if session_id in self.active_sessions:
            return self.active_sessions[session_id]
            
        storage_path = os.path.join(self.sessions_dir, f"{session_id}.json")
        session = Session.load(storage_path)
        self.active_sessions[session_id] = session
        return session

    def close_session(self, session_id: str):
        if session_id in self.active_sessions:
            self.active_sessions[session_id].save()
            del self.active_sessions[session_id]
