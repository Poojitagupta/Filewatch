from fastapi import APIRouter, Depends, Query
from datetime import datetime, timezone
from typing import Optional

from config.database import get_db
from middleware.auth import get_current_user

router = APIRouter(prefix="/api/events", tags=["events"])


def _out(doc: dict) -> dict:
    return {
        "id":             str(doc["_id"]),
        "event_type":     doc.get("event_type"),
        "file_path":      doc.get("file_path", ""),
        "severity":       doc.get("severity", "info"),
        "message":        doc.get("message", ""),
        "old_hash":       doc.get("old_hash"),
        "new_hash":       doc.get("new_hash"),
        "directory_path": doc.get("directory_path"),
        "created_at":     doc.get("created_at"),
    }


@router.get("/stats")
async def stats(current_user: dict = Depends(get_current_user)):
    db = get_db()

    pipeline = [
        {"$match": {"user_id": current_user["id"]}},
        {"$group": {
            "_id":      None,
            "total":    {"$sum": 1},
            "files":    {"$sum": "$file_count"},
            "alerts":   {"$sum": "$alert_count"},
            "last_scan":{"$max": "$last_scan"},
        }},
    ]
    agg     = await db.directories.aggregate(pipeline).to_list(1)
    summary = agg[0] if agg else {}

    today_start  = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    alerts_today = await db.events.count_documents({
        "user_id":  current_user["id"],
        "severity": {"$in": ["warning", "critical"]},
        "created_at": {"$gte": today_start},
    })

    return {
        "directories":   summary.get("total", 0),
        "files_tracked": summary.get("files", 0),
        "alerts_today":  alerts_today,
        "last_scan":     summary.get("last_scan"),
    }


@router.get("/")
async def list_events(
    limit:    int            = Query(50, le=200),
    severity: Optional[str] = Query(None),
    dir_id:   Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    db    = get_db()
    query = {"user_id": current_user["id"]}
    if severity: query["severity"]     = severity
    if dir_id:   query["directory_id"] = dir_id

    cursor = db.events.find(query, sort=[("created_at", -1)], limit=limit)
    
    events = [_out(e) async for e in cursor]
    return {"events": events}