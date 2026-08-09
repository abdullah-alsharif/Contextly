"""Router registration. Business routes (/api/v1) land in later phases."""
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")
