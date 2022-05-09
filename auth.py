import os

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

load_dotenv()

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 5

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


class Project(BaseModel):
    id: int
    name: str


class User(BaseModel):
    id: int
    projects: list[Project]


async def get_current_user(token: str = Depends(oauth2_scheme)):
    secret_key = os.environ["JWT_SECRET_KEY"]
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise credentials_exception
    if not payload.get("user_id"):
        raise credentials_exception
    return User(id=payload.get("user_id"), projects=payload.get("projects"))
