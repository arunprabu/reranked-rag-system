import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from src.api.v1.services.query_service import query_documents, query_documents_stream
from src.api.v1.schema.query_schema import QueryRequest, QueryResponse
from src.core.guardrails import GuardrailViolation

# Import your ingestion and query utilities
from src.ingestion.ingestion import ingest_pdf
router = APIRouter()

UPLOAD_DIR = "uploaded_pdfs"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# --- Upload Endpoint ---
@router.post("/admin/upload")
async def upload_pdf(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # Call ingestion pipeline (chunking + embedding into PGVector)
    ingest_pdf(file_path)

    return {"file": file.filename, "message": "Upload and embedding successful"}


@router.post("/query")
def query_endpoint(request: QueryRequest):
    try:
        return query_documents(request.query)
    except GuardrailViolation as violation:
        # An input guardrail blocked the request — return a 400 with the reason.
        raise HTTPException(
            status_code=400,
            detail={"guardrail": violation.guard, "message": violation.message},
        )


@router.post("/query/stream")
async def stream_query_endpoint(request: QueryRequest):
    """Return an SSE stream of the agent's response (after input guardrails)."""
    try:
        generator = await query_documents_stream(request.query)
    except GuardrailViolation as violation:
        raise HTTPException(
            status_code=400,
            detail={"guardrail": violation.guard, "message": violation.message},
        )

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
    )
