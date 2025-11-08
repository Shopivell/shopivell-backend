# app/security.py
from fastapi.security import OAuth2PasswordBearer

# This will tell FastAPI where the login endpoint is
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
