"""
API FastAPI — Neogrid EDI Logístico
Hospedada no EasyPanel, ativada a cada 5min pelo scheduler externo.
"""

import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from rpa import executar_rpa

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("rpa_neogrid.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

app = FastAPI(
    title="Neogrid EDI RPA",
    description="Verifica documentos não lidos na Caixa de Entrada do EDI Logístico.",
    version="1.0.0"
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/verificar")
def verificar():
    """
    Executa o RPA e retorna os documentos não lidos do dia.

    Cada documento retornado inclui:
    - numero: identificador do documento
    - remetente: empresa que enviou
    - data_criacao: data/hora de criação
    - status: status de leitura
    - pdf_base64: conteúdo do PDF em base64 (decodifique para salvar o arquivo)
    - pdf_nome: nome sugerido para o arquivo PDF

    Exemplo para salvar o PDF em Python:
        import base64
        with open(doc["pdf_nome"], "wb") as f:
            f.write(base64.b64decode(doc["pdf_base64"]))
    """
    resultado = executar_rpa(headless=True)

    if not resultado["sucesso"]:
        raise HTTPException(
            status_code=500,
            detail=f"Falha na execução do RPA: {resultado['erro']}"
        )

    return JSONResponse(content=resultado)
