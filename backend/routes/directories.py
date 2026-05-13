from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from bson import ObjectId
import asyncio
import os

from config.database import get_db
from middleware.auth import get_current_user
from models.schemas import DirectoryCreate
from services import monitor
from services.monitor import scan_and_index 
from services.monitor import monitor

router = APIRouter(prefix="/api/directories", tags=["directories"])


def _out(doc: dict) -> dict:
    return {
        "id":          str(doc["_id"]),
        "path":        doc["path"],
        "label":       doc.get("label"),
        "status":      doc.get("status", "active"),
        "file_count":  doc.get("file_count", 0),
        "alert_count": doc.get("alert_count", 0),
        "last_scan":   doc.get("last_scan"),
        "created_at":  doc.get("created_at"),
    }


@router.get("")
async def list_dirs(current_user: dict = Depends(get_current_user)):
    db     = get_db()
    cursor = db.directories.find({"user_id": current_user["id"]}, sort=[("created_at", -1)])
    dirs   = [_out(d) async for d in cursor]
    return {"directories": dirs}


@router.post("", status_code=201)
async def add_dir(body: DirectoryCreate, current_user: dict = Depends(get_current_user)):
    db = get_db()

    if not os.path.exists(body.path):
        raise HTTPException(status_code=400, detail=f"Path does not exist on server: {body.path}")

    if await db.directories.find_one({"user_id": current_user["id"], "path": body.path}):
        raise HTTPException(status_code=409, detail="Directory already being monitored")

    doc = {
        "user_id":     current_user["id"],
        "path":        body.path,
        "label":       body.label,
        "status":      "active",
        "file_count":  0,
        "alert_count": 0,
        "last_scan":   None,
        "created_at":  datetime.utcnow(),
    }
    result    = await db.directories.insert_one(doc)
    dir_id    = str(result.inserted_id)
    doc["_id"] = result.inserted_id

    await monitor.watch(dir_id, current_user["id"], body.path)
    asyncio.create_task(monitor.baseline_scan(dir_id, current_user["id"], body.path))

    return {"directory": _out(doc)}


@router.delete("{dir_id}")
async def remove_dir(dir_id: str, current_user: dict = Depends(get_current_user)):
    db  = get_db()
    doc = await db.directories.find_one({"_id": ObjectId(dir_id), "user_id": current_user["id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Directory not found")

    monitor.unwatch(dir_id)
    await db.directories.delete_one({"_id": ObjectId(dir_id)})
    await db.file_snapshots.delete_many({"directory_id": dir_id})
    return {"message": "Directory removed from monitoring"}


@router.post("{dir_id}/scan")
async def trigger_scan(dir_id: str, current_user: dict = Depends(get_current_user)):
    db  = get_db()
    doc = await db.directories.find_one({"_id": ObjectId(dir_id), "user_id": current_user["id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Directory not found")

    asyncio.create_task(monitor.baseline_scan(dir_id, current_user["id"], doc["path"]))
    return {"message": "Scan initiated"}


@router.post("/{dir_id}/scan")
async def scan_directory(dir_id: str, current_user: dict = Depends(get_current_user)):
    # 1. Find the directory in the database
    directory = await db.directories.find_one({"_id": ObjectId(dir_id), "user_id": current_user["id"]})
    if not directory:
        raise HTTPException(status_code=404, detail="Directory not found")

    # 2. Trigger the scan logic from your monitor service
    # This will re-hash all files and compare them to the DB
    try:
        await monitor.scan_and_index(directory["path"], str(directory["_id"]), current_user["id"])
        
        # 3. Update the "last_scan" time in the database
        await db.directories.update_one(
            {"_id": ObjectId(dir_id)},
            {"$set": {"last_scan": datetime.utcnow()}}
        )
        return {"message": "Scan completed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")
    

@router.post("/{dir_id}/scan")
async def manual_scan(dir_id: str, current_user: dict = Depends(get_current_user)):
    directory = await db.directories.find_one({
        "_id": ObjectId(dir_id), 
        "user_id": current_user["id"]
    })
    
    if not directory:
        raise HTTPException(status_code=404, detail="Directory not found")

    # Run the scan
    await scan_and_index(directory["path"], dir_id, current_user["id"])
    
    # Update last scan time
    await db.directories.update_one(
        {"_id": ObjectId(dir_id)},
        {"$set": {"last_scan": datetime.utcnow()}}
    )
    
    return {"status": "success", "message": f"Scanned {directory['path']}"}