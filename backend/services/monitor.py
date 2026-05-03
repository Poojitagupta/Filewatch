"""
monitor.py — Core engine
Watchdog filesystem events + SHA-256 hashing + MongoDB persistence + WebSocket broadcast
"""

import asyncio
import hashlib
import os
from datetime import datetime
from typing import Dict

from bson import ObjectId
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

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


async def _handle_modified(dir_id, user_id, file_path):
    db  = get_db()
    snap = await db.file_snapshots.find_one(
        {"directory_id": dir_id, "file_path": file_path}
    )
    old_hash = snap["hash_sha256"] if snap else None
    new_hash = hash_file(file_path)
    if not new_hash or old_hash == new_hash:
        return

    await db.file_snapshots.update_one(
        {"directory_id": dir_id, "file_path": file_path},
        {"$set": {"hash_sha256": new_hash, "last_modified": datetime.utcnow()}},
        upsert=True,
    )
    await _emit_event(
        dir_id, user_id, "modified", file_path, "warning",
        f"Hash mismatch — file modified: {os.path.basename(file_path)}",
        old_hash=old_hash, new_hash=new_hash,
    )


async def _handle_deleted(dir_id, user_id, file_path):
    db   = get_db()
    snap = await db.file_snapshots.find_one(
        {"directory_id": dir_id, "file_path": file_path}
    )
    old_hash = snap["hash_sha256"] if snap else None
    await db.file_snapshots.delete_one({"directory_id": dir_id, "file_path": file_path})
    await db.directories.update_one(
        {"_id": ObjectId(dir_id)}, {"$inc": {"file_count": -1}}
    )
    await _emit_event(
        dir_id, user_id, "deleted", file_path, "critical",
        f"File deleted: {os.path.basename(file_path)}",
        old_hash=old_hash,
    )


class FileMonitor:
    def __init__(self):
        self._observer = Observer()
        self._observer.start()
        self._watches: Dict[str, object] = {}

    async def watch(self, dir_id: str, user_id: str, path: str):
        self.unwatch(dir_id)
        handler = IntegrityHandler(dir_id, user_id)
        handle  = self._observer.schedule(handler, path, recursive=True)
        self._watches[dir_id] = handle
        print(f"[Monitor] Watching: {path}  (id={dir_id})")

    def unwatch(self, dir_id: str):
        handle = self._watches.pop(dir_id, None)
        if handle:
            self._observer.unschedule(handle)
            print(f"[Monitor] Stopped dir_id={dir_id}")

    async def baseline_scan(self, dir_id: str, user_id: str, dir_path: str):
        print(f"[Monitor] Baseline scan: {dir_path}")
        db    = get_db()
        count = 0
        for root, _, files in os.walk(dir_path):
            for fname in files:
                fpath = os.path.join(root, fname)
                try:
                    h     = hash_file(fpath)
                    size  = os.path.getsize(fpath)
                    mtime = datetime.utcfromtimestamp(os.path.getmtime(fpath))
                    if h:
                        await db.file_snapshots.update_one(
                            {"directory_id": dir_id, "file_path": fpath},
                            {"$set": {"hash_sha256": h, "file_size": size,
                                      "last_modified": mtime,
                                      "baseline_at": datetime.utcnow()}},
                            upsert=True,
                        )
                        count += 1
                except (IOError, OSError):
                    pass

        await db.directories.update_one(
            {"_id": ObjectId(dir_id)},
            {"$set": {"file_count": count, "last_scan": datetime.utcnow()}},
        )
        await ws_manager.broadcast({
            "type": "scan_complete",
            "payload": {"dirId": dir_id, "file_count": count},
        })
        print(f"[Monitor] Done: {count} files in {dir_path}")

    async def restore(self):
        db = get_db()
        n  = 0
        async for doc in db.directories.find({"status": "active"}):
            if os.path.exists(doc["path"]):
                await self.watch(str(doc["_id"]), doc["user_id"], doc["path"])
                n += 1
        print(f"[Monitor] Restored {n} watcher(s)")

    def stop(self):
        self._observer.stop()
        self._observer.join()



def calculate_hash(file_path):
    """Generate SHA-256 hash for a file."""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except Exception:
        return None

async def scan_and_index(path: str, dir_id: str, user_id: str):
    """Walks through the directory and updates file hashes in the DB."""
    for root, _, files in os.walk(path):
        for file in files:
            file_path = os.path.join(root, file)
            file_hash = calculate_hash(file_path)
            
            if file_hash:
                # Update or Insert file metadata
                await db.files.update_one(
                    {"path": file_path, "dir_id": ObjectId(dir_id)},
                    {
                        "$set": {
                            "name": file,
                            "hash": file_hash,
                            "last_seen": datetime.utcnow(),
                            "user_id": user_id
                        }
                    },
                    upsert=True
                )
    print(f"[Monitor] Scan complete for: {path}")




monitor = FileMonitor()