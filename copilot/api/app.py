"""HTTP API with live progress (Server-Sent Events).

  POST /investigations                 start one (simulate a fault, or point at an existing database)
  GET  /investigations/{id}            status, pending approval question, final report
  GET  /investigations/{id}/events     live stream: one event per finished step (SSE)
  POST /investigations/{id}/approval   answer the approval question: {"approved": true, "by": "ritu"}
  POST /investigations/{id}/label      teach the KB the real cause of a finished investigation
  GET  /  (demo page)   GET /health   GET /faults

Each investigation runs in its own thread. When the graph reaches the approval gate the thread waits
for the approval request, and a missing answer counts as "no", so nothing is ever applied by default."""
import json
import threading
import traceback
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from ..agent.learn import learn_from_resolution
from ..agent.run import investigate
from ..config import ROOT, SERVICES
from ..kb import KBUnavailable, KnowledgeBase
from ..sim.faults import FAULTS
from ..sim.generator import generate

DATA_DIR = ROOT / "data"
APPROVAL_TIMEOUT = 600  # seconds to wait for a human before answering "no"


class StartRequest(BaseModel):
    fault: Optional[str] = None       # simulate this fault ...
    root: Optional[str] = None
    seed: int = 0
    db_path: Optional[str] = None     # ... or investigate an existing database under data/
    auto_approve: bool = False        # demo/test convenience; default is to wait for a human


class ApprovalRequest(BaseModel):
    approved: bool
    by: str = "api-user"


class LabelRequest(BaseModel):
    fault: str
    root_service: str
    resolution: str
    steps: Optional[List[str]] = None
    log_keywords: List[str] = []


class Job:
    def __init__(self, job_id, db):
        self.id, self.db = job_id, db
        self.events, self.cond = [], threading.Condition()
        self.status, self.pending, self.decision = "running", None, None
        self.decided = threading.Event()
        self.final, self.error = None, None

    def emit(self, event):
        with self.cond:
            event = dict(event, seq=len(self.events) + 1)
            if event["type"] == "approval_required":
                self.status, self.pending = "awaiting_approval", event["payload"]
            elif event["type"] == "decision":
                self.status, self.pending = "running", None
            elif event["type"] == "done":
                self.status = "done"
            elif event["type"] == "error":
                self.status = "error"
            self.events.append(event)
            self.cond.notify_all()

    @property
    def finished(self):
        return self.status in ("done", "error")


def create_app(kb=None, data_dir=None):
    app = FastAPI(title="Incident Copilot")
    jobs = {}
    state = {"kb": kb}
    data_dir = Path(data_dir or DATA_DIR)

    def get_kb():
        if state["kb"] is None:
            state["kb"] = KnowledgeBase()
        return state["kb"]

    def get_job(job_id):
        if job_id not in jobs:
            raise HTTPException(404, "no such investigation")
        return jobs[job_id]

    def work(job, auto_approve):
        def approver(payload):
            if auto_approve:
                return {"approved": True, "by": "auto-approve"}
            if not job.decided.wait(APPROVAL_TIMEOUT):
                return {"approved": False, "by": "timeout"}
            return job.decision
        try:
            job.final = investigate(job.db, kb=get_kb(), approver=approver, emit=job.emit, thread_id=job.id)
        except Exception:
            job.error = traceback.format_exc()
            job.emit({"type": "error", "message": job.error.splitlines()[-1]})

    @app.get("/health")
    def health():
        try:
            get_kb()
            return {"ok": True, "knowledge_base": "ready"}
        except KBUnavailable as exc:
            return {"ok": False, "knowledge_base": str(exc)}

    @app.get("/faults")
    def faults():
        return {"faults": sorted(FAULTS), "services": SERVICES}

    @app.post("/investigations", status_code=201)
    def start(req: StartRequest):
        job_id = uuid.uuid4().hex[:10]
        if req.db_path:
            path = Path(req.db_path).resolve()
            if data_dir.resolve() not in path.parents or not path.exists():
                raise HTTPException(400, "db_path must be an existing file under the data directory")
            db = str(path)
        elif req.fault:
            if req.fault not in FAULTS or (req.root and req.root not in SERVICES):
                raise HTTPException(400, "unknown fault or service")
            (data_dir / "api").mkdir(parents=True, exist_ok=True)
            db = str(data_dir / "api" / f"{job_id}.db")
            generate(req.fault, req.root, req.seed, db_path=db)
        else:
            raise HTTPException(400, "give either fault or db_path")
        job = jobs[job_id] = Job(job_id, db)
        threading.Thread(target=work, args=(job, req.auto_approve), daemon=True).start()
        return {"id": job_id, "status": job.status}

    @app.get("/investigations/{job_id}")
    def show(job_id: str):
        job = get_job(job_id)
        report = job.final.get("report") if job.final else None
        return {"id": job.id, "status": job.status, "pending_approval": job.pending,
                "events": len(job.events), "report": report, "error": job.error}

    @app.get("/investigations/{job_id}/events")
    def events(job_id: str, after: int = 0):
        job = get_job(job_id)

        def stream():
            i = after
            while True:
                with job.cond:
                    job.cond.wait_for(lambda: i < len(job.events) or job.finished, timeout=15)
                    fresh, done = job.events[i:], job.finished
                for ev in fresh:
                    i = ev["seq"]
                    yield f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"
                if not fresh:
                    if done:
                        return
                    yield ": keep-alive\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/investigations/{job_id}/approval")
    def approve(job_id: str, req: ApprovalRequest):
        job = get_job(job_id)
        if job.status != "awaiting_approval":
            raise HTTPException(409, f"not waiting for approval (status: {job.status})")
        job.decision = {"approved": req.approved, "by": req.by}
        job.decided.set()
        return {"ok": True}

    @app.post("/investigations/{job_id}/label")
    def label(job_id: str, req: LabelRequest):
        job = get_job(job_id)
        if job.status != "done" or not job.final or "signature" not in job.final:
            raise HTTPException(409, "investigation has not finished with a signature to learn from")
        kb_id = learn_from_resolution(get_kb(), job.final, req.fault, req.root_service, req.resolution,
                                      steps=req.steps, log_keywords=req.log_keywords)
        return {"learned": kb_id}

    @app.get("/", response_class=HTMLResponse)
    def home():
        return DEMO_PAGE

    return app


DEMO_PAGE = """<!doctype html><meta charset=utf-8><title>Incident Copilot</title>
<style>body{font:15px system-ui;max-width:860px;margin:2rem auto;padding:0 1rem}pre{background:#f3f4f6;padding:1rem;overflow:auto}
button,select{font:inherit;padding:.4rem .8rem}#ask{display:none;border:2px solid #b45309;padding:1rem;margin:1rem 0}</style>
<h1>Incident Copilot</h1>
<p>Pick a fault to simulate, watch the investigation stream in, and approve or reject the fix.</p>
<select id=fault></select> <button id=go>Investigate</button>
<div id=ask><b>Approval needed</b><pre id=q></pre><button id=yes>Approve</button> <button id=no>Reject</button></div>
<h3>Live steps</h3><pre id=log></pre><h3>Report</h3><pre id=rep></pre>
<script>
const $=id=>document.getElementById(id);let job;
fetch('/faults').then(r=>r.json()).then(d=>d.faults.forEach(f=>$('fault').add(new Option(f,f))));
$('go').onclick=async()=>{$('log').textContent='';$('rep').textContent='';
 const r=await fetch('/investigations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fault:$('fault').value})});
 job=(await r.json()).id;const es=new EventSource(`/investigations/${job}/events`);
 for(const t of ['start','step','approval_required','decision','done','error'])es.addEventListener(t,e=>{const d=JSON.parse(e.data);
  if(t==='step')$('log').textContent+=d.trace.join('\\n')+'\\n';
  if(t==='approval_required'){$('q').textContent=JSON.stringify(d.payload,null,2);$('ask').style.display='block'}
  if(t==='decision')$('ask').style.display='none';
  if(t==='done'){$('rep').textContent=JSON.stringify(d.report,null,2);es.close()}
  if(t==='error'){$('rep').textContent=d.message;es.close()}})};
const answer=ok=>fetch(`/investigations/${job}/approval`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved:ok,by:'web-user'})});
$('yes').onclick=()=>answer(true);$('no').onclick=()=>answer(false);
</script>"""

app = create_app()
