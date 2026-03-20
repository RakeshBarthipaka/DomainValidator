from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from database import engine
from models import Base
from routers import auth_router, verify_router, lists_router
from routers.microsoft_auth import router as ms_router
import os

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="DomainValidator",
    version="1.0"
)


uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(uploads_dir, exist_ok=True)


# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(auth_router.router)
app.include_router(verify_router.router)
app.include_router(lists_router.router)
app.include_router(ms_router, prefix="/auth")   

# ── Root redirect ──────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return RedirectResponse(url="/login", status_code=303)