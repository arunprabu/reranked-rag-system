import os
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import StreamingResponse
from src.api.v1.services.query_service import query_documents, query_documents_stream
from src.api.v1.schema.query_schema import QueryRequest,QueryResponse

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

    docs = query_documents(request.query) 

    return docs

@router.post("/query/stream")
async def stream_query_endpoint(request: QueryRequest):
    """
    Endpoint that returns an SSE stream of the agent's response.
    """
    generator = await query_documents_stream(request.query)
    
    return StreamingResponse(
        generator, 
        media_type="text/event-stream"
    )