from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])

# In-memory store for pending destructive tool calls awaiting confirmation
# Structure: { "task_id": {"name": str, "args": dict, "status": "pending" | "approved" | "denied"} }
pending_tools: Dict[str, Dict[str, Any]] = {}

class ConfirmToolRequest(BaseModel):
    task_id: str
    action: str  # "approve" or "deny"

@router.post("/confirm")
def confirm_tool(req: ConfirmToolRequest):
    """
    Endpoint for the UI to confirm or deny a pending destructive tool call.
    """
    if req.task_id not in pending_tools:
        raise HTTPException(status_code=404, detail="Pending tool call not found or expired.")
    
    if req.action not in ["approve", "deny"]:
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'deny'.")
        
    pending_tools[req.task_id]["status"] = req.action
    
    return {"status": "ok", "task_id": req.task_id, "action": req.action}

@router.get("/pending")
def list_pending():
    """Returns all pending tool calls."""
    return [{"task_id": k, **v} for k, v in pending_tools.items()]
