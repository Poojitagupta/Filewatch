import asyncio

from motor.motor_asyncio import AsyncIOMotorClient
from config.settings import settings

client: AsyncIOMotorClient = None
db = None


async def connect_db():
    import services.monitor as monitor_service
    monitor_service._main_loop = asyncio.get_running_loop()
    global client, db
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB]

    await client.admin.command("ping")
    print(f"[DB] MongoDB connected → {settings.MONGO_DB}")

    await db.users.create_index("email", unique=True)
    await db.directories.create_index([("user_id", 1), ("path", 1)], unique=True)
    await db.file_snapshots.create_index([("directory_id", 1), ("file_path", 1)], unique=True)
    await db.events.create_index([("user_id", 1), ("created_at", -1)])
    await db.events.create_index([("directory_id", 1), ("created_at", -1)])
    await db.events.create_index("severity")
    print("[DB] Indexes ensured")


async def close_db():
    global client
    if client:
        client.close()
        print("[DB] MongoDB connection closed")


def get_db():
    return db