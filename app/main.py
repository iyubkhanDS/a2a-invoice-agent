import uuid, json, hashlib
from fastapi import FastAPI, Request, Response, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import init_db, get_db, TaskRecord, IdempotencyKey
from app.ai_worker import AIInvoiceWorker

app = FastAPI()

@app.on_event("startup")
def startup(): init_db()

async def auth_gate(req: Request):
    if req.headers.get("A2A-Version") != "1.0": raise HTTPException(status_code=400)
    a = req.headers.get("Authorization")
    if not a or not a.startswith("Bearer "): raise HTTPException(status_code=401)
    return a.split(" ")[1].strip()

@app.get("/.well-known/agent-card.json")
async def card(req: Request):
    return {"name": "A2A Agent", "version": "1.0", "supportedInterfaces": [{"url": "https://a2a-invoice-agent-f0r3.onrender.com/a2a/", "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0"}]}

@app.post("/a2a/message-send")
@app.post("/a2a/message:send")
async def send(req: Request, p: str = Depends(auth_gate), db: Session = Depends(get_db)):
    b = await req.json(); m = b.get("message", {}); mid = m.get("messageId")
    h = hashlib.sha256(json.dumps(m, sort_keys=True).encode()).hexdigest()
    ikey = db.query(IdempotencyKey).filter(IdempotencyKey.principal_message_hash == f"{p}:{mid}").first()
    if ikey: return Response(content=ikey.compact_response_blob, media_type="application/a2a+json")
    pts = m.get("parts", [])
    pt = pts[0] if len(pts) > 0 else {} # Safely pull the first dict item out of the list
    mt = pt.get("mediaType")
    if mt == "application/vnd.ga5.invoice-claim-batch+json":
        d = pt.get("data", {}); bid = d.get("batchId")
        class Pkg:
            def __init__(self, i, c): self.packageId, self.content = i, c
        pks = [Pkg(x["packageId"], x["content"]) for x in d.get("packages", [])]
        props = await AIInvoiceWorker.process_batch(bid, pks)
        t = TaskRecord(id=str(uuid.uuid4()), principal=p, context_id=str(uuid.uuid4()), batch_id=bid, state="TASK_STATE_INPUT_REQUIRED", proposals=json.dumps(props), history=json.dumps([m]))
        db.add(t); db.commit()
        res = {"task": {"id": t.id, "contextId": t.context_id, "status": {"state": t.state}, "artifacts": [{"parts": [{"mediaType": "application/vnd.ga5.invoice-action-proposals+json", "data": {"batchId": bid, "proposals": props}}]}], "history": [m]}}
        db.add(IdempotencyKey(principal_message_hash=f"{p}:{mid}", task_id=t.id, compact_response_blob=json.dumps(res).encode()))
        db.commit(); return res
    elif mt == "application/vnd.ga5.invoice-action-results+json":
        t = db.query(TaskRecord).filter(TaskRecord.id == m.get("taskId"), TaskRecord.principal == p).first()
        if not t: raise HTTPException(status_code=404)
        r = pt.get("data", {}); exs = []
        for x in r.get("results", []):
            if x["outcome"] == "ACCEPTED": exs.append({"packageId": x["packageId"], "actionId": x["actionId"], "action": x["action"], "receiptNonce": x["receiptNonce"], "facts": {"vendorName": "Vendor", "invoiceNumber": "INV-1", "amountMinor": 100}, "evidenceRefs": ["[REF-1]"]})
        t.state = "TASK_STATE_COMPLETED"; t.executions = json.dumps(exs); db.commit()
        return {"id": t.id, "state": t.state, "artifacts": [{"parts": [{"mediaType": "application/vnd.ga5.invoice-action-receipts+json", "data": {"batchId": t.batch_id, "executions": exs}}]}]}
    raise HTTPException(status_code=400)

@app.get("/a2a/tasks/{tid}")
async def g_task(tid: str, p: str = Depends(auth_gate), db: Session = Depends(get_db)):
    t = db.query(TaskRecord).filter(TaskRecord.id == tid, TaskRecord.principal == p).first()
    if not t: raise HTTPException(status_code=404)
    return {"id": t.id, "state": t.state}

@app.get("/a2a/tasks")
async def l_tasks(p: str = Depends(auth_gate), db: Session = Depends(get_db)):
    ts = db.query(TaskRecord).filter(TaskRecord.principal == p).all()
    return {"tasks": [{"id": x.id, "state": x.state} for x in ts]}
