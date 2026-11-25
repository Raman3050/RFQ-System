from fastapi import APIRouter

from app.api.v1 import auction, auth, rfqs

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(rfqs.router)
api_router.include_router(auction.router)
