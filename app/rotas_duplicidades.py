"""Tela "Verificar duplicidades": lista os pares suspeitos e deixa manter um e remover o outro."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.database import CATEGORIA_PENDENTE, get_db
from app.duplicidades import pares_suspeitos
from app.templating import templates

router = APIRouter()


def _remover_duplicata(db, manter_id: int, remover_id: int) -> bool:
    """Remove `remover_id` mantendo `manter_id`, sem perder o que a linha removida sabe.

    - O extrato é a realidade bancária: se a linha removida veio do extrato e a mantida é uma fatura ou um
      pendente, a mantida passa a valer com a data e a forma de pagamento do banco (e fica Pago).
    - Se a mantida está "A classificar", herda a categoria da removida; recorrente e titular só se estiverem vazios.
    - O que veio de arquivo (extrato/fatura) fica registrado como "já tratado" para não voltar em nova importação.
    """
    k = db.execute("SELECT l.*, c.nome AS cat FROM lancamentos l JOIN categorias c ON c.id = l.categoria_id WHERE l.id = ?",
                   (manter_id,)).fetchone()
    r = db.execute("SELECT l.*, c.nome AS cat FROM lancamentos l JOIN categorias c ON c.id = l.categoria_id WHERE l.id = ?",
                   (remover_id,)).fetchone()
    if k is None or r is None or manter_id == remover_id:
        return False
    sets, params = [], []
    if r["origem"] == "extrato" and (k["origem"] == "fatura" or k["status"] in ("Pendente", "Agendado")):
        sets += ["data = ?", "status = 'Pago'"]
        params += [r["data"]]
        if k["cartao_id"] is None:  # lançamentos de cartão mantêm 'Cartão de crédito'
            sets.append("forma_pagamento = ?")
            params.append(r["forma_pagamento"])
    if k["cat"] == CATEGORIA_PENDENTE and r["cat"] != CATEGORIA_PENDENTE:
        sets.append("categoria_id = ?")
        params.append(r["categoria_id"])
    sets += ["recorrente_id = COALESCE(recorrente_id, ?)", "titular_id = COALESCE(titular_id, ?)"]
    params += [r["recorrente_id"], r["titular_id"]]
    try:
        db.execute("BEGIN")
        if r["id_externo"]:
            db.execute("INSERT OR IGNORE INTO ignorados_importacao (id_externo) VALUES (?)", (r["id_externo"],))
        db.execute(f"UPDATE lancamentos SET {', '.join(sets)} WHERE id = ?", (*params, manter_id))  # nosec B608 - `sets` são trechos fixos; os valores vão em `params`
        db.execute("UPDATE lancamentos SET sugestao_id = NULL WHERE sugestao_id = ?", (remover_id,))
        db.execute("DELETE FROM duplicidades_ignoradas WHERE a = ? OR b = ?", (remover_id, remover_id))
        db.execute("DELETE FROM lancamentos WHERE id = ?", (remover_id,))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return True


@router.get("/duplicidades")
def duplicidades(request: Request, db=Depends(get_db)):
    return templates.TemplateResponse(request, "duplicidades.html", {"pares": pares_suspeitos(db)})


@router.post("/duplicidades/resolver")
def resolver(db=Depends(get_db), a: int = Form(...), b: int = Form(...), acao: str = Form(...)):
    a, b = min(a, b), max(a, b)
    if acao == "manter_a":
        _remover_duplicata(db, a, b)
    elif acao == "manter_b":
        _remover_duplicata(db, b, a)
    elif acao == "diferentes":
        db.execute("INSERT OR IGNORE INTO duplicidades_ignoradas (a, b) VALUES (?, ?)", (a, b))
        db.commit()
    return RedirectResponse("/duplicidades", status_code=303)
