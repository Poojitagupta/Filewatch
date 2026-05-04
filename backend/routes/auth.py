import bcrypt
from fastapi import APIRouter, HTTPException, Depends
from passlib.context import CryptContext
from datetime import datetime
from bson import ObjectId

from config.database import get_db
from middleware.auth import create_token, get_current_user
from models.schemas import UserRegister, UserLogin, TokenResponse, UserOut

router = APIRouter(tags=["auth"])
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _user_out(doc: dict) -> UserOut:
    return UserOut(
        id=str(doc["_id"]),
        name=doc["name"],
        email=doc["email"],
        role=doc.get("role", "admin"),
        created_at=doc.get("created_at", datetime.utcnow()),
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: UserRegister):
    db = get_db()
    if await db.users.find_one({"email": body.email}):
        raise HTTPException(status_code=409, detail="Email already registered")

    doc = {
        "name":       body.name,
        "email":      body.email,
        "password":   pwd_ctx.hash(body.password),
        "role":       "admin",
        "created_at": datetime.utcnow(),
    }
    result   = await db.users.insert_one(doc)
    doc["_id"] = result.inserted_id
    token    = create_token({"id": str(result.inserted_id), "email": body.email,
                              "name": body.name, "role": "admin"})
    return TokenResponse(token=token, user=_user_out(doc))


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin):
    db   = get_db()
    user = await db.users.find_one({"email": body.email})
    # Check password using direct bcrypt
    is_valid = bcrypt.checkpw(
        body.password.encode('utf-8'), 
        user["password"].encode('utf-8')
    )

    if not user or not is_valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token({"id": str(user["_id"]), "email": user["email"],
                           "name": user["name"], "role": user.get("role", "admin")})
    return TokenResponse(token=token, user=_user_out(user))


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    db   = get_db()
    user = await db.users.find_one({"_id": ObjectId(current_user["id"])})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": _user_out(user)}