import uuid, json, hashlib
from datetime import datetime
from fastapi import FastAPI, Request, Response, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import init_db, get_db, TaskRecord, IdempotencyKey
from app.ai_worker import AIInvoiceWorker

app = FastAPI()

@app.on_event("startup")
def startup():
    init_db()

async def auth_gate(req: Request):
    if req.headers.get("A2A-Version") != "1.0":
        raise HTTPException(status_code=400, detail="Invalid A2A-Version")
    if req.method == "POST" and "application/a2a+json" not in req.headers.get("Content-Type", ""):
        raise HTTPException(status_code=400, detail="Invalid Content-Type")
    a = req.headers.get("Authorization")
    if not a or not a.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return a.split(" ")[1].strip()

@app.get("/.well-known/agent-card.json")
async def card(req: Request):
    res = {
        "name": "A2A Invoice Agent",
        "description": "Processes financial claims batches natively.",
        "version": "1.0",
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
        "supportedInterfaces": [{"url": "https://onrender.com", "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0"}],
        "defaultInputModes": ["application/vnd.ga5.invoice-claim-batch+json"],
        "defaultOutputModes": ["application/vnd.ga5.invoice-action-proposals+json", "application/vnd.ga5.invoice-action-receipts+json"],
        "skills": [{"id": "invoice_action_agent", "name": "Invoice Batch Action Parser", "description": "Analyzes invoice claims.", "tags": ["finance", "invoices", "reconciliation"]}]
    }
    return Response(content=json.dumps(res), media_type="application/a2a+json")

@app.post("/a2a/message:send")
async def send(req: Request, p: str = Depends(auth_gate), db: Session = Depends(get_db)):
    b = await req.json()
    m = b.get("message", {})
    mid = m.get("messageId")
    if not mid:
        raise HTTPException(status_code=400, detail="Missing messageId")
        
    h = hashlib.sha256(json.dumps(m, sort_keys=True).encode()).hexdigest()
    ikey = db.query(IdempotencyKey).filter(IdempotencyKey.task_id == mid).first()
    if ikey:
        if ikey.principal_message_hash != f"{p}:{h}":
            raise HTTPException(status_code=409, detail="Idempotency Conflict: Payload variation detected")
        return Response(content=ikey.compact_response_blob, media_type="application/a2a+json")
        
    pts = m.get("parts", [])
    pt = pts[0] if len(pts) > 0 else {}
    mt = pt.get("mediaType")
    
    if mt == "application/vnd.ga5.invoice-claim-batch+json":
        d = pt.get("data", {})
        bid = d.get("batchId")
        class Pkg:
            def __init__(self, i, c): self.packageId, self.content = i, c
        pks = [Pkg(x.get("packageId", ""), x.get("content", "")) for x in d.get("packages", [])]
        props = await AIInvoiceWorker.process_batch(bid, pks)
        
        t = TaskRecord(id=str(uuid.uuid4()), principal=p, context_id=m.get("contextId", str(uuid.uuid4())), batch_id=bid, state="TASK_STATE_INPUT_REQUIRED", proposals=json.dumps(props), history=json.dumps([m]))
        db.add(t); db.commit()
        
        res = {"task": {"id": t.id, "contextId": t.context_id, "status": {"state": t.state}, "artifacts": [{"parts": [{"mediaType": "application/vnd.ga5.invoice-action-proposals+json", "data": {"batchId": bid, "proposals": props}}]}], "history": [m]}}
        rblob = json.dumps(res)
        db.add(IdempotencyKey(principal_message_hash=f"{p}:{h}", task_id=mid, compact_response_blob=rblob.encode()))
        db.commit()
        return Response(content=rblob, media_type="application/a2a+json")
        
    elif mt == "application/vnd.ga5.invoice-action-results+json":
        t = db.query(TaskRecord).filter(TaskRecord.id == m.get("taskId"), TaskRecord.principal == p).first()
        if not t:
            raise HTTPException(status_code=404, detail="Task not found")
        if t.state != "TASK_STATE_INPUT_REQUIRED":
            raise HTTPException(status_code=400, detail="Invalid lifecycle jump")
        r = pt.get("data", {})
        stored = json.loads(t.proposals or "[]")
        exs = []
        for x in r.get("results", []):
            match = next((p for p in stored if p["packageId"] == x["packageId"]), None)
            if not match or match["actionId"] != x["actionId"] or match["action"] != x["action"]:
                raise HTTPException(status_code=400, detail="Invalid continuation verification signature")
            if x["outcome"] == "ACCEPTED":
                exs.append({"packageId": x["packageId"], "actionId": x["actionId"], "action": x["action"], "receiptNonce": x["receiptNonce"], "facts": match["facts"], "evidenceRefs": match["evidenceRefs"]})
        t.state = "TASK_STATE_COMPLETED"
        t.executions = json.dumps(exs)
        db.commit()
        res = {"id": t.id, "state": t.state, "artifacts": [{"parts": [{"mediaType": "application/vnd.ga5.invoice-action-receipts+json", "data": {"batchId": t.batch_id, "executions": exs}}]}]}
        return Response(content=json.dumps(res), media_type="application/a2a+json")
        
    raise HTTPException(status_code=400, detail="Unsupported Media Type Structure")

@app.post("/a2a/tasks/{tid}:cancel")
async def cancel_task(tid: str, p: str = Depends(auth_gate), db: Session = Depends(get_db)):
    t = db.query(TaskRecord).filter(TaskRecord.id == tid, TaskRecord.principal == p).first()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    if t.state in ["TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED"]:
        raise HTTPException(status_code=400, detail="Task is already terminal")
    t.state = "TASK_STATE_CANCELED"
    db.commit()
    res = {"id": t.id, "state": t.state}
    return Response(content=json.dumps(res), media_type="application/a2a+json")

@app.get("/a2a/tasks/{tid}")
async def g_task(tid: str, p: str = Depends(auth_gate), db: Session = Depends(get_db)):
    t = db.query(TaskRecord).filter(TaskRecord.id == tid, TaskRecord.principal == p).first()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    res = {"id": t.id, "state": t.state}
    return Response(content=json.dumps(res), media_type="application/a2a+json")

@app.get("/a2a/tasks")
async def l_tasks(p: str = Depends(auth_gate), db: Session = Depends(get_db)):
    ts = db.query(TaskRecord).filter(TaskRecord.principal == p).all()
    res = {"tasks": [{"id": x.id, "state": x.state} for x in ts]}
    return Response(content=json.dumps(res), media_type="application/a2a+json")
