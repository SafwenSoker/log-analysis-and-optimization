from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api.auth import require_api_key
from src.api.routes import builds, analysis, jenkins, upload, model
from src.storage.database import init_db

BASE_DIR = Path(__file__).parent

app = FastAPI(
    title="Jenkins Log Analyser",
    description="Intelligent platform for automated test failure analysis",
    version="2.0.0",
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

_auth = Depends(require_api_key)
app.include_router(builds.router,   dependencies=[_auth])
app.include_router(analysis.router, dependencies=[_auth])
app.include_router(jenkins.router,  dependencies=[_auth])
app.include_router(upload.router,   dependencies=[_auth])
app.include_router(model.router,    dependencies=[_auth])


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/builds/{build_id}", response_class=HTMLResponse)
def build_detail(request: Request, build_id: int):
    return templates.TemplateResponse("build_detail.html", {"request": request, "build_id": build_id})


@app.get("/flaky", response_class=HTMLResponse)
def flaky_page(request: Request):
    return templates.TemplateResponse("flaky.html", {"request": request})
