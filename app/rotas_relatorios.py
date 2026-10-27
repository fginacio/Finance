"""Relatórios personalizados salvos: salvar (ou substituir, se o nome já existe) e excluir."""
from datetime import date

from fastapi import APIRouter, Depends, Form
from fastapi.responses import RedirectResponse
from starlette.datastructures import QueryParams

from app import filtros
from app.database import get_db
from app.relatorio_personalizado import Montagem

router = APIRouter()


def _url(params: str) -> str:
    return "/relatorios?aba=personalizado&" + params


@router.post("/relatorios/salvos")
def salvar_relatorio(db=Depends(get_db), nome: str = Form(...), params: str = Form(...)):
    # remonta a querystring: só fica o que a Montagem entende (nada vindo do formulário vai cru para a URL)
    mt = Montagem.da_query(QueryParams(params), filtros.opcoes(db), date.today().strftime("%Y-%m"))
    nome = nome.strip()[:60]
    if not nome:
        return RedirectResponse(_url(mt.para_query()), status_code=303)
    db.execute("""INSERT INTO relatorios_salvos (nome, params) VALUES (?, ?)
                  ON CONFLICT(nome) DO UPDATE SET params = excluded.params""", (nome, mt.para_query()))
    db.commit()
    return RedirectResponse(_url(mt.para_query()), status_code=303)


@router.post("/relatorios/salvos/{rid}/excluir")
def excluir_relatorio(rid: int, db=Depends(get_db)):
    db.execute("DELETE FROM relatorios_salvos WHERE id = ?", (rid,))
    db.commit()
    return RedirectResponse("/relatorios?aba=personalizado", status_code=303)
