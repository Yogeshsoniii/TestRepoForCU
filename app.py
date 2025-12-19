from fastapi import FastAPI, UploadFile, File, HTTPException, Form
import requests
import base64
import os
from azure.identity import get_bearer_token_provider
from azure.identity import ManagedIdentityCredential
from typing import Optional

app = FastAPI(title="Content Understanding API")

# Constants
AZURE_ENDPOINT = "https://cosmicaifoundryuat.cognitiveservices.azure.com"
API_VERSION = "2025-11-01"
DEFAULT_LOCAL_FILE = "Yogesh soni_Resume_AIML-1.pdf"
uami_client_id = os.getenv("UAMI_CLIENT_ID")
credential = ManagedIdentityCredential(client_id=uami_client_id)
token_provider = get_bearer_token_provider(
    credential,
    "https://cognitiveservices.azure.com/.default"
)

MODEL_DEPLOYMENTS = {
    "gpt-4.1": "gpt-4.1",
    "text-embedding-3-large": "text-embedding-3-large",
}

def get_aad_headers():
    return {
        "Authorization": f"Bearer {token_provider()}",
        "x-ms-useragent": "cu-python-sdk/1.0.0",
        "Content-Type": "application/json",
    }

def poll_analyzer_result_by_id(
    result_id: str,
    timeout: int = 120,
    interval: int = 2,
):
    """
    Polls analyzerResults endpoint until analysis completes.
    """
    result_url = (
        f"{AZURE_ENDPOINT}/contentunderstanding/analyzerResults/"
        f"{result_id}?api-version={API_VERSION}"
    )

    start_time = time.time()

    while True:
        if time.time() - start_time > timeout:
            raise HTTPException(
                status_code=408,
                detail="Analyzer result polling timed out"
            )

        response = requests.get(
            url=result_url,
            headers=get_aad_headers(),
            timeout=30
        )

        if not response.ok:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.text
            )

        result_json = response.json()
        status = result_json.get("status", "").lower()

        if status == "succeeded":
            return result_json

        if status in ("failed", "canceled"):
            raise HTTPException(
                status_code=500,
                detail=result_json
            )

        time.sleep(interval)

def get_file_bytes(file: UploadFile | None) -> bytes:
    """C
    Use uploaded file if present, otherwise fallback to local root file.
    """
    if file:
        return file.file.read()

    if not os.path.exists(DEFAULT_LOCAL_FILE):
        raise HTTPException(
            status_code=500,
            detail=f"Default local file not found: {DEFAULT_LOCAL_FILE}"
        )

    with open(DEFAULT_LOCAL_FILE, "rb") as f:
        return f.read()

def load_file_bytes(
    uploaded_file: Optional[UploadFile],
    local_file_path: Optional[str],
) -> bytes:
    """
    Load file bytes from either uploaded file or local file path.
    Priority: uploaded file > local file path
    """
    if uploaded_file:
        return uploaded_file.file.read()

    if local_file_path:
        if not os.path.exists(local_file_path):
            raise HTTPException(
                status_code=400,
                detail=f"Local file not found: {local_file_path}"
            )

        with open(local_file_path, "rb") as f:
            return f.read()

    raise HTTPException(
        status_code=400,
        detail="Either upload a file or provide local_file_path"
    )


def call_analyzer(analyzer_name: str, file_bytes: bytes, timeout: int = 120):
    analyze_url = (
        f"{AZURE_ENDPOINT}/contentunderstanding/analyzers/"
        f"{analyzer_name}:analyze?api-version={API_VERSION}"
    )

    payload = {
        "inputs": [
            {
                "data": base64.b64encode(file_bytes).decode("utf-8")
            }
        ]
    }

    response = requests.post(
        url=analyze_url,
        headers=get_aad_headers(),
        json=payload,
        timeout=30
    )

    if response.status_code not in (200, 202):
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text
        )

    body = response.json()
    result_id = body.get("id")

    if not result_id:
        # Rare synchronous completion
        return body

    return poll_analyzer_result_by_id(
        result_id=result_id,
        timeout=timeout
    )



@app.post("/analyze/layout")
async def analyze_layout(file: UploadFile = File(None)):
    file_bytes = get_file_bytes(file)

    return call_analyzer(
        analyzer_name="prebuilt-layout",
        file_bytes=file_bytes,
        timeout=60
    )



@app.post("/analyze/document")
async def analyze_document(file: UploadFile = File(None)):
    file_bytes = get_file_bytes(file)

    return call_analyzer(
        analyzer_name="prebuilt-document",
        file_bytes=file_bytes,
        timeout=120
    )




