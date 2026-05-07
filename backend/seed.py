"""Run once to create default admin user: python seed.py"""
import asyncio
from datetime import datetime
from passlib.context import CryptContext
from motor.motor_asyncio import AsyncIOMotorClient
from config.settings import settings

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def seed():
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db     = client[settings.MONGO_DB]

    email = "admin@filewatch.io"
    if await db.users.find_one({"email": email}):
        print(f"[Seed] {email} already exists — skipping.")
        client.close()
        return

    await db.users.create_index("email", unique=True)
    await db.users.insert_one({
        "name":       "Admin",
        "email":      email,
        "password":   pwd_ctx.hash("admin123"),
        "role":       "admin",
        "created_at": datetime.utcnow(),
    })
    print(f"[Seed] Created: {email} / admin123")
    client.close()

if __name__ == "__main__":
    asyncio.run(seed())