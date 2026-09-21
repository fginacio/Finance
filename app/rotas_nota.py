"""Leitura de QR de nota fiscal (NFC-e) a partir de "Novo lançamento". Para todos os usuários."""
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from app.database import get_db
from app.nota_fiscal import (baixar_pagina, categoria_do_local, decodificar_chave, extrair_chave, extrair_dados,
                             ja_cadastrada, parecidos, registrar_leitura, url_permitida)
from app.templating import templates

router = APIRouter(prefix="/lancamentos/nota")


@router.get("")
def tela():
    return RedirectResponse("/lancamentos/novo", status_code=303)


@router.post("")
def ler_nota(request: Request, db=Depends(get_db), conteudo: str = Form("")):
    """Recebe o texto do QR (link da Sefaz) ou a chave de acesso e mostra o que foi possível descobrir."""
    conteudo = conteudo.strip()[:2000]
    r = {"conteudo": conteudo, "chave": extrair_chave(conteudo), "dados": None, "info": None, "erro": None, "chave_info": None,
         "lida_antes": None, "cadastrada": None, "parecidos": [], "categoria": None}
    if r["chave"]:
        r["chave_info"] = decodificar_chave(r["chave"])
    if conteudo.lower().startswith("http"):
        if not url_permitida(conteudo):
            r["erro"] = "O QR não aponta para um site da Sefaz (https em .gov.br); por segurança não foi consultado."
        else:
            html, r["info"] = baixar_pagina(conteudo)
            r["erro"] = r["info"]["erro"]
            if html:
                r["dados"] = extrair_dados(html)
    elif not r["chave"]:
        r["erro"] = "Não reconheci um link da Sefaz nem uma chave de acesso de 44 dígitos."
    if r["chave"]:
        r["lida_antes"] = registrar_leitura(db, r["chave"], r["dados"])
        r["cadastrada"] = ja_cadastrada(db, r["chave"])
        if r["dados"] and r["dados"].get("valor") and r["dados"].get("data"):
            r["parecidos"] = parecidos(db, r["chave"], float(r["dados"]["valor"]), r["dados"]["data"])
        local = categoria_do_local(db, r["chave"])
        if local:
            r["categoria"] = db.execute("SELECT grupo || ' › ' || nome FROM categorias WHERE id = ?", (local["categoria_id"],)).fetchone()[0]
    return templates.TemplateResponse(request, "nota.html", {"resultado": r})


@router.post("/lancar")
def lancar(request: Request, db=Depends(get_db), data: str = Form(""), valor: str = Form(""),
           descricao: str = Form(""), chave: str = Form("")):
    """Abre o formulário normal de lançamento já preenchido; nada é gravado até você confirmar lá."""
    from app.main import _opcoes  # import tardio: main importa este módulo
    try:
        date.fromisoformat(data)
    except ValueError:
        data = date.today().isoformat()
    l = {"id": None, "data": data, "valor": valor, "descricao": descricao[:80],
         "observacoes": f"NFC-e chave {chave}" if chave else ""}
    local = categoria_do_local(db, chave) if len(chave) == 44 else None
    if local:  # só a categoria é sugerida; titular e forma de pagamento ficam por sua conta
        l["categoria_id"] = local["categoria_id"]
    return templates.TemplateResponse(request, "lancamento_form.html",
                                      {"l": l, "hoje": date.today().isoformat(), "erro": None, **_opcoes(db)})
