from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api.routes import builds, analysis, jenkins, upload
from src.storage.database import init_db

BASE_DIR = Path(__file__).parent

app = FastAPI(
    title="Jenkins Log Analyser",
    description="Agentic system for automatic root-cause analysis of Jenkins build logs",
    version="1.0.0",
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(builds.router)
app.include_router(analysis.router)
app.include_router(jenkins.router)
app.include_router(upload.router)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/builds/{build_id}", response_class=HTMLResponse)
def build_detail(request: Request, build_id: int):
    return templates.TemplateResponse("build_detail.html", {"request": request, "build_id": build_id})
