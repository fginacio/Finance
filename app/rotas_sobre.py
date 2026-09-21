"""Tela "Sobre": versão do aplicativo e notas de versão."""
from fastapi import APIRouter, Request

from app.templating import templates
from app.versao import DATA_VERSAO, NOTAS, VERSAO

router = APIRouter()


@router.get("/sobre")
def sobre(request: Request):
    return templates.TemplateResponse(request, "sobre.html", {"notas": NOTAS, "versao": VERSAO, "data_versao": DATA_VERSAO})
