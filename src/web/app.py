"""FastAPI front end: upload → propose → revise → download. In-memory sessions."""
from __future__ import annotations

import base64
import io
import os
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from src.agent.adapter import to_config
from src.agent.pipeline import run_pipeline
from src.agent.proposer import DEFAULT_LOG, propose
from src.agent.render import render_png
from src.agent.schema import GeometrySummary, SetupProposal
from src.agent.summary import build_summary
from src.generator.journal import JournalGenerator
from src.generator.summary import SummaryGenerator
from src.geometry.analyzer import GeometryAnalyzer
from src.materials.database import MaterialDatabase

CALLS_PER_SESSION = int(os.environ.get("CALLS_PER_SESSION", "10"))
SESSION_CAP_PER_HOUR = int(os.environ.get("SESSION_CAP_PER_HOUR", "50"))
SESSION_TTL_S = 3600
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024  # stream the upload in 1 MiB chunks so a large body never sits fully in memory
LOG_PATH = DEFAULT_LOG
STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class Session:
    id: str
    created: float
    last_used: float
    geometry_path: str
    features: object
    solids: list
    summary: GeometrySummary
    filename: str = "part.step"
    proposal: Optional[SetupProposal] = None
    messages: list[str] = field(default_factory=list)
    valid: bool = False
    calls: int = 0
    history: list[dict] = field(default_factory=list)
    brief: str = ""


def _safe_upload_filename(raw: Optional[str]) -> str:
    """Bare basename of the uploaded file, safe to use inside the download zip.

    Strips any directory components the client may have sent (path or
    filename could carry `/`, `\\`, or `..`) so it is never used to escape
    the zip's own directory; falls back to a generic name when empty.
    """
    name = Path((raw or "").strip()).name
    return name or "part.step"


SESSIONS: dict[str, Session] = {}
SESSION_STARTS: list[float] = []
DB = MaterialDatabase()

app = FastAPI(title="FEA Setup Agent")
app.state.propose_fn = propose


class BriefIn(BaseModel):
    brief: str


class InstructionIn(BaseModel):
    instruction: str


def _sweep() -> None:
    now = time.time()
    for sid in [s for s, sess in SESSIONS.items() if now - sess.last_used > SESSION_TTL_S]:
        _drop(sid)
    SESSION_STARTS[:] = [t for t in SESSION_STARTS if now - t < 3600]


def _drop(sid: str) -> None:
    sess = SESSIONS.pop(sid, None)
    if sess:
        try:
            os.remove(sess.geometry_path)
        except OSError:
            pass


def _get(sid: str) -> Session:
    _sweep()
    sess = SESSIONS.get(sid)
    if sess is None:
        raise HTTPException(404, "Session not found or expired. Upload the part again.")
    sess.last_used = time.time()
    return sess


def _b64_render(sess: Session) -> str:
    supports = [s.target for s in sess.proposal.supports] if sess.proposal else []
    loads = [l.target for l in sess.proposal.loads] if sess.proposal else []
    return base64.b64encode(render_png(sess.solids, sess.summary, supports, loads)).decode("ascii")


def _proposal_payload(sess: Session, attempts: int, tokens: dict) -> dict:
    return {
        "proposal": sess.proposal.model_dump(),
        "messages": sess.messages,
        "valid": sess.valid,
        "attempts": attempts,
        "tokens": tokens,
        "render_png_base64": _b64_render(sess),
    }


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/session")
async def create_session(file: UploadFile = File(...)):
    _sweep()
    if len(SESSION_STARTS) >= SESSION_CAP_PER_HOUR:
        raise HTTPException(429, f"Session cap of {SESSION_CAP_PER_HOUR} per hour reached. Try again later.")
    name = (file.filename or "").lower()
    if not name.endswith((".step", ".stp")):
        raise HTTPException(400, "Only STEP files (.step, .stp) are accepted on this path.")
    fd, path = tempfile.mkstemp(suffix=".step")
    total = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"File is {total / 1e6:.1f} MB; the limit is 20 MB.")
                fh.write(chunk)
    except HTTPException:
        os.remove(path)
        raise
    try:
        features, solids, summary = await run_in_threadpool(_analyze_and_summarize, path)
    except ValueError as e:
        os.remove(path)
        raise HTTPException(400, str(e))
    except Exception as e:
        os.remove(path)
        raise HTTPException(400, f"Could not read this STEP file: {e}")
    sid = uuid.uuid4().hex[:12]
    now = time.time()
    SESSIONS[sid] = Session(id=sid, created=now, last_used=now, geometry_path=path,
                            features=features, solids=solids, summary=summary,
                            filename=_safe_upload_filename(file.filename))
    SESSION_STARTS.append(now)
    render_b64 = await run_in_threadpool(_b64_render, SESSIONS[sid])
    return {"session_id": sid, "summary": summary.model_dump(), "render_png_base64": render_b64}


def _analyze_and_summarize(path: str):
    """CPU-bound geometry analysis and summary build; run off the event loop."""
    features, solids = GeometryAnalyzer.analyze_with_solids(path)
    summary = build_summary(features, [ns.body for ns in solids])
    return features, solids, summary


def _run(sess: Session, brief: str, instruction: Optional[str]) -> dict:
    if sess.calls >= CALLS_PER_SESSION:
        raise HTTPException(429, f"This session used its {CALLS_PER_SESSION} model calls. Upload again to start over.")
    sess.calls += 1
    try:
        result = run_pipeline(sess.summary, brief, DB, prior=sess.proposal if instruction else None,
                              instruction=instruction, session_id=sess.id,
                              propose_fn=app.state.propose_fn, log_path=LOG_PATH)
    except Exception as e:  # API errors surface as a plain message; the UI shows a retry button
        raise HTTPException(502, f"Model call failed: {e}")
    sess.proposal, sess.messages, sess.valid = result.proposal, result.messages, result.valid
    sess.history.append({"text": instruction or brief, "valid": result.valid, "messages": result.messages})
    sess.brief = brief
    return _proposal_payload(sess, result.attempts, result.tokens)


@app.post("/session/{sid}/propose")
def propose_endpoint(sid: str, body: BriefIn):
    sess = _get(sid)
    # Don't clear sess.proposal/valid here: if _run fails (cap hit, model error)
    # the session must keep whatever valid proposal it already had. A fresh
    # propose still ignores any prior proposal because _run only threads
    # `prior` through when an instruction is given (see _run below).
    return _run(sess, body.brief, None)


@app.post("/session/{sid}/revise")
def revise_endpoint(sid: str, body: InstructionIn):
    sess = _get(sid)
    if sess.proposal is None:
        raise HTTPException(409, "Nothing to revise yet. Submit a brief first.")
    return _run(sess, sess.brief, body.instruction)


_README_TEXT = (
    "This FEA setup was generated by the ANSYS Workflow Tool.\n\n"
    "Keep these three files together in one folder:\n"
    "  - {step_name}      (the part geometry)\n"
    "  - simulation_setup.wbjn (the Workbench journal)\n"
    "  - settings_summary.html (a human-readable summary of the setup)\n\n"
    "To use: open ANSYS Workbench, then File -> Scripting -> Run Script File "
    "and select simulation_setup.wbjn from this folder. The journal references "
    "the geometry file by its name in this folder, so it must stay alongside it.\n"
)


@app.get("/session/{sid}/download")
def download(sid: str):
    sess = _get(sid)
    if sess.proposal is None or not sess.valid:
        raise HTTPException(409, "Download needs a valid proposal. Fix the validator messages first.")
    # Use the original filename (a bare basename) as the journal's geometry
    # path so SetFile refers to a file the user actually has once they unzip
    # this download, instead of this server's temp path.
    config = to_config(sess.proposal, sess.summary, sess.features, sess.filename, DB)
    with tempfile.TemporaryDirectory() as out:
        wbjn, _ = JournalGenerator.write(config, out, DB)
        html = SummaryGenerator.write(config, out)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(wbjn, "simulation_setup.wbjn")
            z.write(html, "settings_summary.html")
            z.write(sess.geometry_path, sess.filename)
            z.writestr("README.txt", _README_TEXT.format(step_name=sess.filename))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="fea_setup_{sid}.zip"'})
