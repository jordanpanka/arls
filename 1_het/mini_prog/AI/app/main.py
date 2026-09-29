from fastapi import FastAPI
from app.routers import chat_router
from app.routers import file_router

app = FastAPI(title="AI Service")

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(chat_router.router)
app.include_router(file_router.router)