"""
monitor.py — Core engine
Watchdog filesystem events + SHA-256 hashing + MongoDB persistence + WebSocket broadcast
"""
import hashlib
import asyncio

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