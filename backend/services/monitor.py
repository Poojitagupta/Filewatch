"""
monitor.py — Core engine
Watchdog filesystem events + SHA-256 hashing + MongoDB persistence + WebSocket broadcast
"""
import asyncio
import hashlib
import os
from datetime import datetime

from bson import ObjectId
from watchdog.events import FileSystemEventHandler

from config.database import get_db
from services.ws_manager import ws_manager


from config.database import db

def hash_file(path: str) -> str:
    sha = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        return sha.hexdigest()
    except (IOError, PermissionError):
        return ""



# This variable will hold the main loop once the app starts
_main_loop = None

def run_async(coro):
    global _main_loop
    # If the loop isn't set yet, try to find it
    if _main_loop is None:
        try:
            _main_loop = asyncio.get_running_loop()
        except RuntimeError:
            print("[Monitor] Error: No running event loop found!")
            return
            
    # Safely push the task from the Watchdog thread to the FastAPI main thread
    asyncio.run_coroutine_threadsafe(coro, _main_loop)

# List of patterns to ignore (common temp/system files)
IGNORED_PATTERNS = (
    '~$',        # Microsoft Office temp files
    '~WRL',      # Word temp files
    '~WRD',      # Word temp files
    '.tmp',      # General temp files
    '.DS_Store', # macOS system files
    'desktop.ini', # Windows folder config
    '.git'       # Git directory
)

class IntegrityHandler(FileSystemEventHandler):
    def __init__(self, dir_id, user_id):
        self.dir_id = dir_id
        self.user_id = user_id

    def should_ignore(self, path):
        filename = os.path.basename(path)
        # Check if filename starts with or ends with any of our ignored patterns
        return any(filename.startswith(p) or filename.endswith(p) for p in IGNORED_PATTERNS)

    def on_created(self, event):
        if not event.is_directory and not self.should_ignore(event.src_path):
            run_async(_handle_created(self.dir_id, self.user_id, event.src_path))

    def on_modified(self, event):
        if not event.is_directory and not self.should_ignore(event.src_path):
            run_async(_handle_modified(self.dir_id, self.user_id, event.src_path))

    def on_deleted(self, event):
        if not event.is_directory and not self.should_ignore(event.src_path):
            run_async(_handle_deleted(self.dir_id, self.user_id, event.src_path))



async def _emit_event(dir_id, user_id, event_type, file_path,
                      severity, message, old_hash=None, new_hash=None):
    db = get_db()
    dir_doc  = await db.directories.find_one({"_id": ObjectId(dir_id)})
    dir_path = dir_doc["path"] if dir_doc else ""

    doc = {
        "directory_id": dir_id,
        "user_id":      user_id,
        "event_type":   event_type,
        "file_path":    file_path,
        "old_hash":     old_hash,
        "new_hash":     new_hash,
        "severity":     severity,
        "message":      message,
        "directory_path": dir_path,
        "created_at":   datetime.utcnow(),
    }
    await db.events.insert_one(doc)

    if severity in ("warning", "critical"):
        await db.directories.update_one(
            {"_id": ObjectId(dir_id)},
            {"$inc": {"alert_count": 1}}
        )

    await ws_manager.broadcast({
        "type": "event",
        "payload": {
            "dirId":     dir_id,
            "eventType": event_type,
            "filePath":  file_path,
            "severity":  severity,
            "message":   message,
            "oldHash":   old_hash,
            "newHash":   new_hash,
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


async def _handle_created(dir_id, user_id, file_path):
    new_hash = hash_file(file_path)
    if not new_hash:
        return
    db   = get_db()
    size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    await db.file_snapshots.update_one(
        {"directory_id": dir_id, "file_path": file_path},
        {"$set": {"hash_sha256": new_hash, "file_size": size,
                  "last_modified": datetime.utcnow(), "baseline_at": datetime.utcnow()}},
        upsert=True,
    )
    await db.directories.update_one(
        {"_id": ObjectId(dir_id)}, {"$inc": {"file_count": 1}}
    )
    await _emit_event(
        dir_id, user_id, "created", file_path, "info",
        f"New file detected: {os.path.basename(file_path)}",
        new_hash=new_hash,
    )