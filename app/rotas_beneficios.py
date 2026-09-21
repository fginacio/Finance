"""Cadastro dos cartões de benefício (vale alimentação/refeição) e exclusão dos seus usos."""
import sqlite3
import urllib.parse
from datetime import date

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db

router = APIRouter()


def _volta(erro: str | None = None) -> RedirectResponse:
    url = "/cadastros/beneficios" + ("?erro=" + urllib.parse.quote(erro) if erro else "")
    return RedirectResponse(url, status_code=303)


def _valor(texto: str) -> float:
    t = (texto or "0").strip().replace("R$", "").replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    return float(t)


@router.post("/cadastros/beneficios/salvar")
def salvar_beneficio(
    db=Depends(get_db), id: int | None = Form(None), titular_id: int = Form(...), nome: str = Form(...),
    valor_mensal: str = Form("0"), dia_recarga: int = Form(...), inicio: str = Form(...),
    saldo_inicial: str = Form("0"), ativo: str | None = Form(None),
):
    try:
        mensal, saldo = _valor(valor_mensal), _valor(saldo_inicial)
        date.fromisoformat(inicio)
    except ValueError:
        return _volta("Valor ou data inválidos.")
    if mensal < 0 or not 1 <= dia_recarga <= 31:
        return _volta("Informe um valor mensal maior ou igual a zero e um dia de recarga entre 1 e 31.")
    campos = (titular_id, nome.strip(), mensal, dia_recarga, inicio, saldo, 1 if ativo else 0)
    try:
        if id is None:
            db.execute("""INSERT INTO beneficios (titular_id, nome, valor_mensal, dia_recarga, inicio, saldo_inicial, ativo)
                          VALUES (?,?,?,?,?,?,?)""", campos)
        else:
            db.execute("""UPDATE beneficios SET titular_id=?, nome=?, valor_mensal=?, dia_recarga=?, inicio=?,
                          saldo_inicial=?, ativo=? WHERE id=?""", campos + (id,))
        db.commit()
    except sqlite3.IntegrityError:
        return _volta("Esse titular já tem um cartão com esse nome.")
    return _volta()


@router.delete("/beneficios/usos/{uid}")
def excluir_uso(uid: int, db=Depends(get_db)):
    db.execute("DELETE FROM beneficio_usos WHERE id = ?", (uid,))
    db.commit()
    return HTMLResponse("")  # HTMX remove a linha
