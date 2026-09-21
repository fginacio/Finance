"""
Importação de extratos e faturas + tela de validação.

Fluxo do extrato: arquivo -> lançamentos com validado=0 (destacados) -> /validar (categorizar,
confirmar, conciliar com um pendente ou excluir).
Fluxo da fatura: PDF -> tela de revisão -> lançamento (ou conclusão do pendente do recorrente).
"""
import hashlib
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from app.database import CATEGORIA_PENDENTE, get_db
from app.importacao import (PdfSenhaErro, analisar_fatura, detectar_alerta, detectar_forma,
                            eh_pagamento_fatura_cartao, ler_extrato, ler_pdf_texto, padrao, parece_fatura_cartao,
                            parse_valor_br, reconhecer_cartao, reconhecer_recorrente)
from app.relatorios import FORMAS_PAGAMENTO
from app.templating import templates

router = APIRouter()

FILTROS = {
    "todos": ("", "Todos"),
    "pix": ("AND l.forma_pagamento = 'PIX'", "PIX"),
    "sem-categoria": (f"AND c.nome = '{CATEGORIA_PENDENTE}'", "Sem categoria"),
    "alerta": ("AND l.alerta IS NOT NULL", "Com alerta"),
    "sugestao": ("AND (l.sugestao_id IS NOT NULL OR l.alerta LIKE '%duplicidade%')", "Possíveis duplicadas"),
}


# ------------------------------------------------------------------ apoio
def _senhas(texto: str) -> list[str]:
    return [s.strip() for s in (texto or "").split(",") if s.strip()]


def _mes_referencia(mes: str | None) -> str:
    """Mês do extrato ('YYYY-MM'); sem informar (ou inválido), o mês atual."""
    try:
        ano, m = (mes or "").split("-")
        return f"{int(ano):04d}-{int(m):02d}" if 1 <= int(m) <= 12 else date.today().strftime("%Y-%m")
    except ValueError:
        return date.today().strftime("%Y-%m")


def _opcoes(db) -> dict:
    return {
        "categorias": db.execute("SELECT id, nome, grupo FROM categorias WHERE ativa = 1 ORDER BY grupo, nome").fetchall(),
        "titulares": db.execute("SELECT id, nome FROM titulares ORDER BY nome").fetchall(),
        "formas": FORMAS_PAGAMENTO,
    }


def _ja_importada(db, chave: str) -> bool:
    """A chave já virou lançamento ou foi removida na validação/duplicidades (não deve voltar)."""
    return bool(db.execute("SELECT 1 FROM lancamentos WHERE id_externo = ? UNION SELECT 1 FROM ignorados_importacao WHERE id_externo = ?",
                           (chave, chave)).fetchone())


def _id_pendente(db) -> int:
    return db.execute("SELECT id FROM categorias WHERE nome = ?", (CATEGORIA_PENDENTE,)).fetchone()["id"]


def _cartoes(db):
    return db.execute("""SELECT c.id, c.identificador, c.banco, c.palavra_chave, c.titular_id, t.nome AS titular_nome
                         FROM cartoes c JOIN titulares t ON t.id = c.titular_id WHERE c.ativo = 1 ORDER BY c.identificador""").fetchall()


def _id_cat_cartoes(db) -> int | None:
    r = db.execute("SELECT id FROM categorias WHERE nome = 'Cartões de crédito'").fetchone()
    return r["id"] if r else None


def _contexto(db) -> dict:
    return {
        "pendente": _id_pendente(db),
        "cartoes": _cartoes(db),
        "cat_cartoes": _id_cat_cartoes(db),
        "recorrentes": db.execute("SELECT * FROM recorrentes WHERE ativo = 1").fetchall(),
        "regras": db.execute("SELECT * FROM regras").fetchall(),
        "ocupados": {r[0] for r in db.execute(
            "SELECT sugestao_id FROM lancamentos WHERE validado = 0 AND sugestao_id IS NOT NULL")},
        "ignorados": {r[0] for r in db.execute("SELECT id_externo FROM ignorados_importacao")},
    }


def _regra_para(descricao: str, regras):
    p = padrao(descricao)
    exata = [r for r in regras if r["padrao"] == p]
    if exata:
        return exata[0]
    contidas = [r for r in regras if len(r["padrao"]) >= 5 and r["padrao"] in p]
    return max(contidas, key=lambda r: len(r["padrao"])) if contidas else None


def _classificar(descricao: str, ctx: dict) -> dict:
    """Sugestão para uma saída: recorrente por palavra-chave > regra aprendida > 'A classificar'."""
    forma = detectar_forma(descricao)
    sug = {"categoria_id": ctx["pendente"], "titular_id": None, "forma": forma or "Débito",
           "tipo": "Variável", "recorrente_id": None, "cartao_id": None}
    if eh_pagamento_fatura_cartao(descricao) and ctx["cat_cartoes"]:
        # Método A (fatura fechada): o pagamento da fatura é o gasto do cartão.
        sug["categoria_id"] = ctx["cat_cartoes"]
        cartao = reconhecer_cartao(descricao, ctx["cartoes"])
        if cartao:
            sug.update(cartao_id=cartao["id"], titular_id=cartao["titular_id"], forma="Cartão de crédito")
        return sug
    rec = reconhecer_recorrente(descricao, ctx["recorrentes"])
    if rec:
        sug.update(categoria_id=rec["categoria_id"], titular_id=rec["titular_id"], tipo="Recorrente",
                   recorrente_id=rec["id"])
        if not forma:
            sug["forma"] = rec["forma_pagamento"]
        return sug
    regra = _regra_para(descricao, ctx["regras"])
    if regra:
        sug.update(categoria_id=regra["categoria_id"], titular_id=regra["titular_id"])
        if regra["forma_pagamento"] and not forma:
            sug["forma"] = regra["forma_pagamento"]
    return sug


def _candidato_pendente(db, data: str, valor: float, recorrente_id: int | None, ocupados: set) -> int | None:
    """Lançamento que esta saída provavelmente conclui: um pendente ou um já criado a partir da fatura
    do mesmo gasto (para não contar duas vezes a conta que veio na fatura e no extrato)."""
    if recorrente_id:
        linhas = db.execute(
            """SELECT id, abs(julianday(data) - julianday(?)) AS dist FROM lancamentos
               WHERE recorrente_id = ? AND validado = 1
                 AND (status IN ('Pendente', 'Agendado') OR (origem = 'fatura' AND abs(valor - ?) < 0.01))
                 AND abs(julianday(data) - julianday(?)) <= 20 ORDER BY dist""", (data, recorrente_id, valor, data))
    else:
        linhas = db.execute(
            """SELECT id, abs(julianday(data) - julianday(?)) AS dist FROM lancamentos
               WHERE validado = 1 AND abs(valor - ?) < 0.005
                 AND (status IN ('Pendente', 'Agendado') OR origem = 'fatura')
                 AND abs(julianday(data) - julianday(?)) <= 7 ORDER BY dist""", (data, valor, data))
    for r in linhas:
        if r["id"] not in ocupados:
            return r["id"]
    return None


AVISO_DUP = "Possível duplicidade"


def _brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _achar_duplicidade(db, lid: int | None, data: str, valor: float, recorrente_id: int | None, ocupados: set,
                       cartao_id: int | None = None):
    """Procura o lançamento que esta saída provavelmente repete ou conclui.

    Devolve (sugestao_id, aviso). Sugestão: um pendente/fatura (janela de dias) ou qualquer lançamento com o
    mesmo valor na mesma data. Aviso de duplicidade: mesmo valor de um lançamento já existente, ou de outra
    linha importada na mesma data.
    """
    cand = _candidato_pendente(db, data, valor, recorrente_id, ocupados)
    if not cand:
        for r in db.execute("SELECT id FROM lancamentos WHERE validado = 1 AND abs(valor - ?) < 0.005 AND data = ? ORDER BY id",
                            (valor, data)):
            if r["id"] not in ocupados:
                cand = r["id"]
                break
    if not cand:
        # Gasto vindo de QR de nota: o banco costuma lançar 1-3 dias depois da data da nota, então a janela é maior.
        for r in db.execute(
                """SELECT id FROM lancamentos WHERE validado = 1 AND abs(valor - ?) < 0.005
                   AND observacoes LIKE 'NFC-e chave%' AND abs(julianday(data) - julianday(?)) <= 3
                   ORDER BY abs(julianday(data) - julianday(?)), id""", (valor, data, data)):
            if r["id"] not in ocupados:
                cand = r["id"]
                break
    if not cand and cartao_id:
        # Pagamento de fatura com valor diferente da fatura (parcial, juros): ainda é a fatura deste cartão.
        for r in db.execute(
                """SELECT id FROM lancamentos WHERE validado = 1 AND origem = 'fatura' AND cartao_id = ?
                   AND abs(julianday(data) - julianday(?)) <= 20 ORDER BY abs(julianday(data) - julianday(?))""",
                (cartao_id, data, data)):
            if r["id"] not in ocupados:
                cand = r["id"]
                break
    if cand:
        c = db.execute("SELECT data, descricao, valor FROM lancamentos WHERE id = ?", (cand,)).fetchone()
        if abs(c["valor"] - valor) < 0.005:
            return cand, (f"{AVISO_DUP}: já existe “{c['descricao'] or 'lançamento'}” de {_brl(valor)} "
                          f"em {c['data'][8:]}/{c['data'][5:7]}.")
        return cand, None
    outra = db.execute("SELECT id FROM lancamentos WHERE validado = 0 AND id != ? AND abs(valor - ?) < 0.005 AND data = ?",
                       (lid or -1, valor, data)).fetchone()
    if outra:
        return None, f"{AVISO_DUP}: outra linha importada com o mesmo valor e a mesma data (pode ser uma compra repetida)."
    return None, None


def _juntar_avisos(*avisos) -> str | None:
    return " ".join(a for a in avisos if a) or None


def _atualizar_duplicidades(db) -> None:
    """Reavalia as linhas a validar: lançamentos criados depois (fatura, recorrentes, manual) também contam."""
    db.execute("""UPDATE lancamentos SET sugestao_id = NULL WHERE validado = 0 AND sugestao_id IS NOT NULL
                  AND sugestao_id NOT IN (SELECT id FROM lancamentos WHERE validado = 1)""")
    ocupados = {r[0] for r in db.execute("SELECT sugestao_id FROM lancamentos WHERE validado = 0 AND sugestao_id IS NOT NULL")}
    for r in db.execute("SELECT id, data, valor, recorrente_id, sugestao_id, alerta, cartao_id FROM lancamentos WHERE validado = 0").fetchall():
        sug, aviso = r["sugestao_id"], None
        if sug:
            c = db.execute("SELECT data, descricao, valor FROM lancamentos WHERE id = ?", (sug,)).fetchone()
            if abs(c["valor"] - r["valor"]) < 0.005:
                aviso = (f"{AVISO_DUP}: já existe “{c['descricao'] or 'lançamento'}” de {_brl(r['valor'])} "
                         f"em {c['data'][8:]}/{c['data'][5:7]}.")
        else:
            sug, aviso = _achar_duplicidade(db, r["id"], r["data"], r["valor"], r["recorrente_id"], ocupados, r["cartao_id"])
            if sug:
                ocupados.add(sug)
        atual = r["alerta"] or ""
        if aviso and AVISO_DUP not in atual:
            db.execute("UPDATE lancamentos SET alerta = ? WHERE id = ?", (_juntar_avisos(atual, aviso), r["id"]))
        if sug != r["sugestao_id"]:
            db.execute("UPDATE lancamentos SET sugestao_id = ? WHERE id = ?", (sug, r["id"]))
    db.commit()


def _aprender(db, descricao: str, categoria_id: int, titular_id: int | None, forma: str) -> int:
    """Guarda a regra descrição->categoria e aplica às linhas semelhantes ainda sem categoria."""
    pend = _id_pendente(db)
    p = padrao(descricao)
    if categoria_id == pend or not p:
        return 0
    db.execute(
        """INSERT INTO regras (padrao, categoria_id, titular_id, forma_pagamento) VALUES (?,?,?,?)
           ON CONFLICT(padrao) DO UPDATE SET categoria_id = excluded.categoria_id,
             titular_id = excluded.titular_id, forma_pagamento = excluded.forma_pagamento,
             atualizado_em = datetime('now')""", (p, categoria_id, titular_id, forma))
    aplicadas = 0
    for r in db.execute("SELECT id, descricao FROM lancamentos WHERE validado = 0 AND categoria_id = ?", (pend,)).fetchall():
        if padrao(r["descricao"] or "") == p:
            db.execute("UPDATE lancamentos SET categoria_id = ?, titular_id = COALESCE(titular_id, ?) WHERE id = ?",
                       (categoria_id, titular_id, r["id"]))
            aplicadas += 1
    return aplicadas


# ------------------------------------------------------------------ hub e extrato
@router.get("/importar")
def importar_inicio(request: Request):
    return templates.TemplateResponse(request, "importar.html", {"resultado": None, "mes": _mes_referencia(None)})


@router.post("/importar/extrato")
def importar_extrato(request: Request, db=Depends(get_db), arquivos: list[UploadFile] = File(default=[]),
                     senha: str = Form(""), mes: str | None = Form(None)):
    mes = _mes_referencia(mes)
    ctx = _contexto(db)
    por_arquivo = []
    for arq in arquivos:
        if not arq.filename:
            continue
        item = {"nome": arq.filename, "novas": 0, "repetidas": 0, "fora": 0, "pix": 0, "sugestoes": 0, "alertas": 0, "duplicadas": 0, "erro": None}
        try:
            saidas = ler_extrato(arq.filename, arq.file.read(), _senhas(senha), int(mes[:4]))
        except PdfSenhaErro as e:
            item["erro"] = str(e)
        except Exception as e:  # arquivo ilegível/formato inesperado: segue com os demais
            item["erro"] = f"Não consegui ler este arquivo ({type(e).__name__}: {e})."
        else:
            do_mes = [s for s in saidas if s["data"][:7] == mes]
            item["fora"] = len(saidas) - len(do_mes)
            saidas = do_mes
            if not saidas and item["fora"]:
                item["erro"] = (f"Nenhuma saída de {mes[5:]}/{mes[:4]} neste arquivo ({item['fora']} de outros meses foram "
                                "ignoradas). Para importar outro mês, informe o mês de referência.")
            elif not saidas:
                item["erro"] = "Nenhuma saída encontrada. Se o arquivo é de outro formato, me envie um exemplo para ajustar."
            for s in saidas:
                if s["chave"] in ctx["ignorados"] or db.execute(
                        "SELECT 1 FROM lancamentos WHERE id_externo = ?", (s["chave"],)).fetchone():
                    item["repetidas"] += 1
                    continue
                sug = _classificar(s["descricao"], ctx)
                cand, aviso_dup = _achar_duplicidade(db, None, s["data"], s["valor"], sug["recorrente_id"], ctx["ocupados"],
                                                     sug["cartao_id"])
                if cand:
                    ctx["ocupados"].add(cand)
                alerta = _juntar_avisos(detectar_alerta(s["descricao"]), aviso_dup)
                db.execute(
                    """INSERT INTO lancamentos (data, categoria_id, descricao, titular_id, forma_pagamento, cartao_id, valor,
                       tipo, status, validado, origem, id_externo, alerta, sugestao_id, recorrente_id)
                       VALUES (?,?,?,?,?,?,?,?,'Pago',0,'extrato',?,?,?,?)""",
                    (s["data"], sug["categoria_id"], s["descricao"], sug["titular_id"], sug["forma"], sug["cartao_id"],
                     s["valor"], sug["tipo"], s["chave"], alerta, cand, sug["recorrente_id"]))
                novo_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                item["novas"] += 1
                item["pix"] += sug["forma"] == "PIX"
                item["sugestoes"] += bool(cand)
                item["alertas"] += bool(alerta)
                item["duplicadas"] += bool(aviso_dup)
                if aviso_dup and not cand:  # a outra linha importada também precisa do aviso
                    db.execute("""UPDATE lancamentos SET alerta = COALESCE(alerta || ' ', '') || ?
                                  WHERE validado = 0 AND id != ? AND abs(valor - ?) < 0.005
                                    AND data = ? AND COALESCE(alerta, '') NOT LIKE ?""",
                               (aviso_dup, novo_id, s["valor"], s["data"], f"%{AVISO_DUP}%"))
        por_arquivo.append(item)
    db.commit()
    return templates.TemplateResponse(request, "importar.html", {"resultado": por_arquivo, "mes": mes})


# ------------------------------------------------------------------ faturas
@router.post("/importar/faturas")
def importar_faturas(request: Request, db=Depends(get_db), arquivos: list[UploadFile] = File(default=[]),
                           senha: str = Form("")):
    ctx = _contexto(db)
    hoje = date.today().isoformat()
    linhas = []
    for arq in arquivos:
        if not arq.filename:
            continue
        linha = {"arquivo": arq.filename, "erro": None, "texto": "", "valor": None, "vencimento": "", "referencia": "",
                 "recorrente_id": None, "status": "Pago", "alternativas": [], "avisos": [], "cartao_id": None,
                 "eh_cartao": False, "zerada": False}
        try:
            texto = ler_pdf_texto(arq.file.read(), _senhas(senha))
        except PdfSenhaErro as e:
            linha["erro"] = str(e)
        except Exception as e:
            linha["erro"] = f"Não consegui ler este PDF ({type(e).__name__}: {e})."
        else:
            dados = analisar_fatura(texto)
            linha["eh_cartao"] = parece_fatura_cartao(texto)
            cartao = reconhecer_cartao(texto, ctx["cartoes"]) if linha["eh_cartao"] else None
            rec = None if linha["eh_cartao"] else reconhecer_recorrente(texto, ctx["recorrentes"])
            linha["cartao_id"] = cartao["id"] if cartao else None
            linha.update(texto=texto[:2500], valor=dados["valor"], vencimento=dados["vencimento"] or "",
                         referencia=dados["referencia"] or "", recorrente_id=rec["id"] if rec else None,
                         alternativas=[v for v in dados["alternativas"] if v >= 1])
            linha["status"] = "Pago" if dados["vencimento"] and dados["vencimento"] <= hoje else "Pendente"
            linha["zerada"] = dados["valor"] == 0
            if dados["valor"] and dados["vencimento"]:
                for e in db.execute(
                        """SELECT data, descricao, valor, validado FROM lancamentos
                           WHERE abs(valor - ?) < 0.005 AND abs(julianday(data) - julianday(?)) <= 5
                             AND NOT (recorrente_id IS ? AND status IN ('Pendente', 'Agendado'))""",
                        (dados["valor"], dados["vencimento"], rec["id"] if rec else None)):
                    linha["avisos"].append(
                        f"Já existe “{e['descricao'] or 'lançamento'}” de {_brl(e['valor'])} em {e['data'][8:]}/{e['data'][5:7]}"
                        f"{' (a validar)' if not e['validado'] else ''}: possível duplicidade.")
            if not texto.strip():
                linha["erro"] = "O PDF não tem texto (parece escaneado). Este tipo ainda não é lido."
        linhas.append(linha)
    return templates.TemplateResponse(
        request, "fatura_revisao.html",
        {"linhas": linhas, "recorrentes": ctx["recorrentes"], "cartoes": ctx["cartoes"], "hoje": hoje,
         **_opcoes(db)})


@router.post("/importar/faturas/confirmar")
def confirmar_faturas(
    request: Request, db=Depends(get_db),
    arquivo: list[str] = Form(default=[]), acao: list[str] = Form(default=[]), valor: list[str] = Form(default=[]),
    data_pagamento: list[str] = Form(default=[]), vencimento: list[str] = Form(default=[]),
    referencia: list[str] = Form(default=[]), recorrente_id: list[str] = Form(default=[]),
    categoria_id: list[str] = Form(default=[]), status: list[str] = Form(default=[]),
    descricao: list[str] = Form(default=[]), cartao_id: list[str] = Form(default=[]),
):
    resultados = []
    cat_cartoes = _id_cat_cartoes(db)
    for i, nome in enumerate(arquivo):
        if acao[i] != "incluir":
            resultados.append({"arquivo": nome, "ok": None, "msg": "Ignorada."})
            continue
        v = parse_valor_br(valor[i])
        data = data_pagamento[i]
        if v == 0:
            resultados.append({"arquivo": nome, "ok": None, "msg": "Fatura zerada (R$ 0,00): nada a lançar."})
            continue
        if not v or v < 0 or not data:
            resultados.append({"arquivo": nome, "ok": False, "msg": "Informe um valor e uma data válidos."})
            continue
        cid = int(cartao_id[i]) if i < len(cartao_id) and cartao_id[i] else None
        if cid:
            resultados.append(_gravar_fatura_cartao(db, cid, cat_cartoes, nome, v, data, vencimento[i], referencia[i], status[i]))
            continue
        rid = int(recorrente_id[i]) if recorrente_id[i] else None
        chave = "fat:" + hashlib.sha1(f"{rid}|{referencia[i]}|{vencimento[i]}|{v:.2f}|{nome}".encode(), usedforsecurity=False).hexdigest()[:20]
        if _ja_importada(db, chave):
            resultados.append({"arquivo": nome, "ok": False, "msg": "Esta fatura já foi importada."})
            continue

        if rid:
            rec = db.execute("SELECT * FROM recorrentes WHERE id = ?", (rid,)).fetchone()
            mes = (vencimento[i] or data)[:7]
            pendente = db.execute(
                """SELECT id FROM lancamentos WHERE recorrente_id = ? AND status IN ('Pendente','Agendado')
                   AND substr(data, 1, 7) IN (?, ?) ORDER BY data LIMIT 1""", (rid, mes, data[:7])).fetchone()
            if pendente:
                db.execute("UPDATE lancamentos SET valor=?, data=?, status=?, validado=1, origem='fatura', id_externo=? WHERE id=?",
                           (v, data, status[i], chave, pendente["id"]))
                resultados.append({"arquivo": nome, "ok": True, "msg": f"Concluiu o lançamento pendente de “{rec['descricao']}”."})
                continue
            ja_no_mes = db.execute("SELECT 1 FROM lancamentos WHERE recorrente_id = ? AND substr(data, 1, 7) = ?", (rid, mes)).fetchone()
            if ja_no_mes:
                resultados.append({"arquivo": nome, "ok": False,
                                   "msg": f"“{rec['descricao']}” já tem lançamento em {mes[5:]}/{mes[:4]}. Edite-o em Lançamentos."})
                continue
            db.execute(
                """INSERT INTO lancamentos (data, categoria_id, descricao, titular_id, forma_pagamento, cartao_id, valor,
                   tipo, status, origem, id_externo, recorrente_id) VALUES (?,?,?,?,?,?,?,'Recorrente',?,'fatura',?,?)""",
                (data, rec["categoria_id"], descricao[i] or rec["descricao"], rec["titular_id"], rec["forma_pagamento"],
                 rec["cartao_id"], v, status[i], chave, rid))
            resultados.append({"arquivo": nome, "ok": True, "msg": f"Criou o lançamento de “{rec['descricao']}”."})
        else:
            if not categoria_id[i]:
                resultados.append({"arquivo": nome, "ok": False, "msg": "Escolha o recorrente ou uma categoria."})
                continue
            db.execute(
                """INSERT INTO lancamentos (data, categoria_id, descricao, forma_pagamento, valor, tipo, status, origem, id_externo)
                   VALUES (?,?,?,'Boleto',?,'Variável',?,'fatura',?)""",
                (data, int(categoria_id[i]), descricao[i] or nome, v, status[i], chave))
            resultados.append({"arquivo": nome, "ok": True, "msg": "Criou um lançamento avulso."})
    db.commit()
    _atualizar_duplicidades(db)
    return templates.TemplateResponse(request, "importar.html", {"resultado": None, "resultado_faturas": resultados,
                                                                 "mes": _mes_referencia(None)})


def _gravar_fatura_cartao(db, cartao_id: int, cat_cartoes: int | None, arquivo: str, valor: float, data: str,
                          vencimento: str, referencia: str, status: str) -> dict:
    """Fatura fechada (Método A): um lançamento por fatura, categoria 'Cartões de crédito', com o cartão."""
    cartao = db.execute("SELECT c.*, t.nome AS titular_nome FROM cartoes c JOIN titulares t ON t.id = c.titular_id WHERE c.id = ?",
                        (cartao_id,)).fetchone()
    if cartao is None or cat_cartoes is None:
        return {"arquivo": arquivo, "ok": False, "msg": "Cartão ou categoria 'Cartões de crédito' não encontrado."}
    chave = "fat:" + hashlib.sha1(f"cartao|{cartao_id}|{(vencimento or data)[:7]}|{valor:.2f}".encode(), usedforsecurity=False).hexdigest()[:20]
    if _ja_importada(db, chave):
        return {"arquivo": arquivo, "ok": False, "msg": f"Esta fatura de {cartao['identificador']} já foi importada."}
    mes = (vencimento or data)[:7]
    # Reaproveita o "Fatura do cartão" pendente gerado pelos recorrentes (do mesmo cartão, ou sem cartão definido).
    pendente = db.execute(
        """SELECT id FROM lancamentos WHERE categoria_id = ? AND status IN ('Pendente', 'Agendado') AND validado = 1
             AND substr(data, 1, 7) IN (?, ?) AND (cartao_id = ? OR cartao_id IS NULL)
           ORDER BY (cartao_id = ?) DESC, data LIMIT 1""", (cat_cartoes, mes, data[:7], cartao_id, cartao_id)).fetchone()
    if pendente:
        db.execute("""UPDATE lancamentos SET valor=?, data=?, status=?, cartao_id=?, titular_id=?, forma_pagamento='Cartão de crédito',
                      descricao=?, origem='fatura', id_externo=? WHERE id=?""",
                   (valor, data, status, cartao_id, cartao["titular_id"], f"Fatura {cartao['identificador']}", chave, pendente["id"]))
        return {"arquivo": arquivo, "ok": True, "msg": f"Fatura de {cartao['identificador']} concluiu o lançamento pendente de cartão."}
    db.execute(
        """INSERT INTO lancamentos (data, categoria_id, descricao, titular_id, forma_pagamento, cartao_id, valor, tipo, status,
           origem, id_externo) VALUES (?,?,?,?,'Cartão de crédito',?,?,'Variável',?,'fatura',?)""",
        (data, cat_cartoes, f"Fatura {cartao['identificador']}", cartao["titular_id"], cartao_id, valor, status, chave))
    return {"arquivo": arquivo, "ok": True, "msg": f"Criou o lançamento da fatura de {cartao['identificador']}."}


# ------------------------------------------------------------------ validação
@router.get("/validar")
def validar(request: Request, filtro: str = "todos", db=Depends(get_db)):
    filtro = filtro if filtro in FILTROS else "todos"
    _atualizar_duplicidades(db)
    base = """FROM lancamentos l JOIN categorias c ON c.id = l.categoria_id
              LEFT JOIN lancamentos s ON s.id = l.sugestao_id WHERE l.validado = 0 """
    itens = db.execute(
        f"""SELECT l.*, c.nome AS categoria_nome, s.data AS sug_data, s.descricao AS sug_descricao, s.valor AS sug_valor
            {base} {FILTROS[filtro][0]} ORDER BY l.data, l.id""").fetchall()
    contagens = {k: db.execute(f"SELECT COUNT(*) {base} {w}").fetchone()[0] for k, (w, _) in FILTROS.items()}
    return templates.TemplateResponse(
        request, "validar.html",
        {"itens": itens, "filtro": filtro, "filtros": FILTROS, "contagens": contagens,
         "pendente": CATEGORIA_PENDENTE, "pendente_id": _id_pendente(db), **_opcoes(db)})


def _volta(filtro: str) -> RedirectResponse:
    return RedirectResponse(f"/validar?filtro={filtro if filtro in FILTROS else 'todos'}", status_code=303)


@router.post("/validar/{lid}/confirmar")
def confirmar(lid: int, db=Depends(get_db), data: str = Form(...), descricao: str = Form(""),
              categoria_id: int = Form(...), titular_id: int | None = Form(None), forma_pagamento: str = Form(...),
              valor: str = Form(...), filtro: str = Form("todos")):
    v = parse_valor_br(valor)
    if v is None or v < 0:
        return _volta(filtro)
    db.execute(
        """UPDATE lancamentos SET data=?, descricao=?, categoria_id=?, titular_id=?, forma_pagamento=?, valor=?,
           validado=1, sugestao_id=NULL WHERE id=? AND validado=0""",
        (data, descricao.strip() or None, categoria_id, titular_id or None, forma_pagamento, abs(v), lid))
    _aprender(db, descricao, categoria_id, titular_id or None, forma_pagamento)
    db.commit()
    return _volta(filtro)


@router.post("/validar/{lid}/conciliar")
def conciliar(lid: int, db=Depends(get_db), data: str = Form(...), forma_pagamento: str = Form(...),
              valor: str = Form(...), filtro: str = Form("todos")):
    """Junta a saída importada ao lançamento pendente que ela conclui: o pendente vira Pago com data/valor reais."""
    x = db.execute("SELECT * FROM lancamentos WHERE id = ? AND validado = 0 AND sugestao_id IS NOT NULL", (lid,)).fetchone()
    v = parse_valor_br(valor)
    if x is None or v is None or v < 0:
        return _volta(filtro)
    db.execute("DELETE FROM lancamentos WHERE id = ?", (lid,))
    if x["id_externo"]:  # a linha do extrato já foi absorvida: não pode voltar num novo import
        db.execute("INSERT OR IGNORE INTO ignorados_importacao (id_externo) VALUES (?)", (x["id_externo"],))
    db.execute(
        """UPDATE lancamentos SET data=?, valor=?,
           forma_pagamento = CASE WHEN cartao_id IS NOT NULL THEN forma_pagamento ELSE ? END, status='Pago',
           id_externo=COALESCE(id_externo, ?), validado=1 WHERE id=?""",
        (data, abs(v), forma_pagamento, x["id_externo"], x["sugestao_id"]))
    db.commit()
    return _volta(filtro)


@router.post("/validar/{lid}/excluir")
def excluir(lid: int, db=Depends(get_db), filtro: str = Form("todos")):
    x = db.execute("SELECT id_externo FROM lancamentos WHERE id = ? AND validado = 0", (lid,)).fetchone()
    if x:
        if x["id_externo"]:
            db.execute("INSERT OR IGNORE INTO ignorados_importacao (id_externo) VALUES (?)", (x["id_externo"],))
        db.execute("DELETE FROM lancamentos WHERE id = ?", (lid,))
        db.commit()
    return _volta(filtro)


@router.post("/validar/confirmar-classificados")
def confirmar_classificados(db=Depends(get_db), filtro: str = Form("todos")):
    """Confirma de uma vez o que já tem categoria e não tem nenhum alerta (duplicidade, fatura de cartão...)."""
    pend = _id_pendente(db)
    db.execute("""UPDATE lancamentos SET validado = 1
                  WHERE validado = 0 AND categoria_id != ? AND sugestao_id IS NULL AND alerta IS NULL""", (pend,))
    db.commit()
    return _volta(filtro)
