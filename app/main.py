"""Idea Developer Council — FastAPI server."""
from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import council, llm, memory  # noqa: E402
from app.roles import all_agents, council_order  # noqa: E402

INDEX_HTML = Path(__file__).resolve().parent / 'static' / 'index.html'

app = FastAPI(
    title='Idea Developer Council',
    version='1.0.0',
    description='Roadmap och råd för utvecklare: stack, arkitektur, server, juridik, etapper.',
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


class Restrictions(BaseModel):
    platform: str = Field(..., description='t.ex. webb, android-spel, android-app')
    users_target: str = Field(..., description='målgrupp i en mening')
    team_size: str = Field(..., description='t.ex. "1 utvecklare"')
    deadline: str | None = None
    budget: str | None = None


class RoadmapRequest(BaseModel):
    brief: str = Field(..., min_length=10, description='Vad vill du bygga?')
    restrictions: Restrictions
    project_id: str | None = None
    store: bool = True


@app.get('/', include_in_schema=False)
def home() -> FileResponse:
    """Webb-UI: formulär, roadmap-rendering och rådets bidrag."""
    return FileResponse(INDEX_HTML)


@app.get('/health')
def health():
    return {'status': 'ok', 'llm_mode': 'online' if llm.online() else 'offline'}


@app.get('/agents')
def agents():
    return {
        'order': council_order(),
        'agents': {name: {'primary_lens': a['primary_lens']}
                   for name, a in all_agents().items()},
    }


@app.post('/roadmap')
def roadmap(req: RoadmapRequest):
    try:
        return council.run_council(
            brief=req.brief,
            restrictions=req.restrictions.model_dump(),
            project_id=req.project_id,
            store=req.store,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get('/memory/validate')
def memory_validate():
    return memory.validate()


@app.get('/memory/projects')
def memory_projects():
    return memory.projects()


@app.get('/memory/context/{project_id}/{member}')
def memory_context(project_id: str, member: str, task_class: str = 'generic'):
    try:
        return memory.context(project_id, member, task_class)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
