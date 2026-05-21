"""
API FastAPI — Neogrid EDI Logístico
Ativa o RPA via HTTP. Hospedada no Easypanel.
"""

import asyncio
import logging
import os
from fastapi import FastAPI, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse

from rpa import run_rpa

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

app = FastAPI(
    title="Neogrid EDI RPA",
    description="Verifica e baixa documentos não lidos na Caixa de Entrada do EDI Logístico.",
    version="2.0.0",
)

security = HTTPBearer(auto_error=False)

NEOGRID_EMAIL = os.environ["NEOGRID_EMAIL"]
NEOGRID_PASSWORD = os.environ["NEOGRID_PASSWORD"]
API_TOKEN = os.environ.get("API_TOKEN", "")


def _check_token(credentials: HTTPAuthorizationCredentials | None):
    if not API_TOKEN:
        return
    if credentials is None or credentials.credentials != API_TOKEN:
        raise HTTPException(status_code=401, detail="Token inválido ou ausente.")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/run")
async def run(credentials: HTTPAuthorizationCredentials | None = Security(security)):
    """
    Executa o RPA e retorna os documentos não lidos do dia.

    Cada arquivo retornado em `files` contém:
    - filename: nome do arquivo
    - content_base64: conteúdo em base64
    - size_bytes: tamanho em bytes
    - downloaded_at: timestamp ISO do download
    """
    _check_token(credentials)

    try:
        result = await run_rpa(NEOGRID_EMAIL, NEOGRID_PASSWORD)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Erro desconhecido no RPA."))

    return JSONResponse(content=result)
