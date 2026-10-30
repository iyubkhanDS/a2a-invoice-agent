from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal

# --- Incoming A2A Envelope Validations ---
class MessagePart(BaseModel):
    mediaType: str
    data: Optional[Dict[str, Any]] = None
    text: Optional[str] = None

class Message(BaseModel):
    messageId: str
    role: Literal["ROLE_USER", "ROLE_AGENT"]
    parts: List[MessagePart]
    contextId: Optional[str] = None
    taskId: Optional[str] = None

class SendMessageConfiguration(BaseModel):
    returnImmediately: Optional[bool] = False
    historyLength: Optional[int] = 20
    acceptedOutputModes: Optional[List[str]] = None

class SendMessageRequest(BaseModel):
    message: Message
    configuration: Optional[SendMessageConfiguration] = None

# --- Inbound Invoice Structure (Batch Elements) ---
class InvoicePackage(BaseModel):
    packageId: str
    content: str  # The synthetic raw ledger text processed by AI

class InvoiceClaimBatch(BaseModel):
    batchId: str
    policyRevision: str
    packages: List[InvoicePackage]

# --- Outbound A2A Proposal Structures (TASK_STATE_INPUT_REQUIRED) ---
class InvoiceFacts(BaseModel):
    vendorName: str
    invoiceNumber: str
    amountMinor: int
    currency: str = "INR"

class ActionProposal(BaseModel):
    packageId: str
    actionId: str  # Durable unique ID (at least 12 characters)
    action: Literal["settle_invoice", "request_approval", "hold_invoice", "reject_duplicate", "open_exception"]
    facts: InvoiceFacts
    evidenceRefs: List[str]  # Must be exactly the 3 decisive bracketed references
    rationale: str  # 60 to 1500 character evaluation reasoning

class InvoiceActionProposals(BaseModel):
    batchId: str
    proposals: List[ActionProposal]

# --- Continuation & Execution Validations (TASK_STATE_COMPLETED) ---
class GraderResultItem(BaseModel):
    packageId: str
    actionId: str
    action: str
    outcome: Literal["ACCEPTED", "REJECTED"]
    receiptNonce: str

class InvoiceActionResults(BaseModel):
    batchId: str
    results: List[GraderResultItem]

class ExecutionReceipt(BaseModel):
    packageId: str
    actionId: str
    action: str
    receiptNonce: str
    facts: InvoiceFacts
    evidenceRefs: List[str]

class InvoiceActionReceipts(BaseModel):
    batchId: str
    executions: List[ExecutionReceipt]
