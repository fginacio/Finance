"""
Controle de Gastos - Web
Ponto de entrada da aplicação FastAPI.
"""
import calendar
import sqlite3
import urllib.parse
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.database import get_db, init_db
from app import autenticacao, beneficios, nota_fiscal, rotas_auth, rotas_beneficios, rotas_boleto, rotas_duplicidades, rotas_importacao, rotas_nota, rotas_sobre
from app.listas import BANCOS_EMISSORES, GRUPOS_CATEGORIA, opcoes
from app.templating import templates
from app.relatorios import FORMAS_PAGAMENTO, dados_relatorios, meses_anteriores

BASE_DIR = Path(__file__).resolve().parent

# Todas as rotas exigem login (exceto /login e /static): a dependência é global.
# docs/openapi desligados: sairiam da proteção global e listariam todas as rotas.
app = FastAPI(title="Controle de Gastos", dependencies=[Depends(autenticacao.exigir_login)],
              docs_url=None, redoc_url=None, openapi_url=None)
app.add_exception_handler(autenticacao.NaoAutenticado, autenticacao.resposta_nao_autenticado)
app.middleware("http")(autenticacao.protecao_basica)
app.include_router(rotas_auth.router)
app.include_router(rotas_importacao.router)
app.include_router(rotas_beneficios.router)
app.include_router(rotas_duplicidades.router)
app.include_router(rotas_nota.router)
app.include_router(rotas_boleto.router)
app.include_router(rotas_sobre.router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/")
def dashboard(request: Request, mes: str | None = None, db=Depends(get_db)):
    mes = _mes_valido(mes)
    mes_ant = meses_anteriores(mes, 2)[0]

    def soma(where: str = "", params: tuple = (), m: str = mes) -> float:
        return db.execute(
            f"SELECT COALESCE(SUM(valor), 0) FROM vw_lancamentos WHERE conta = 1 AND substr(data, 1, 7) = ? {where}",  # nosec B608 - `where` é sempre constante do código; os valores vão como parâmetros
            (m,) + params,
        ).fetchone()[0]

    total = soma()
    total_ant = soma(m=mes_ant)
    meta = {r["chave"]: float(r["valor"]) for r in db.execute("SELECT chave, valor FROM parametros")}.get("meta_economia_mensal", 0.0)
    essenciais = soma("AND essencial = 1")

    indicadores = {
        "total": total,
        "total_ant": total_ant,
        "variacao": (total / total_ant - 1) if total_ant else None,
        "essenciais": essenciais,
        "pct_essenciais": (essenciais / total) if total else 0,
        "pendentes": soma("AND status = 'Pendente'"),
        "viagem": soma("AND categoria = 'Investimento viagem'"),
        "meta": meta,
        # saída de dinheiro da conta para aplicações: não é gasto (fora dos totais), mas aparece à parte
        "aplicado": db.execute("""SELECT COALESCE(SUM(l.valor), 0) FROM lancamentos l JOIN categorias c ON c.id = l.categoria_id
                                  WHERE c.contabiliza = 0 AND substr(l.data, 1, 7) = ?""", (mes,)).fetchone()[0],
        "fixo": db.execute("SELECT COALESCE(SUM(valor_estimado), 0) FROM recorrentes WHERE ativo = 1").fetchone()[0],
    }

    cartao_where = "AND forma_pagamento = 'Cartão de crédito'"
    por_cartao = [
        {"cartao": c["identificador"], "total": soma(cartao_where + " AND cartao = ?", (c["identificador"],))}
        for c in db.execute("SELECT identificador FROM cartoes WHERE ativo = 1 ORDER BY identificador")
    ]
    cartoes = {
        "total": soma(cartao_where),
        "lista": por_cartao,
        "sem_cartao": soma(cartao_where + " AND cartao IS NULL"),
    }

    por_titular = [dict(r) for r in db.execute(
        """SELECT t.nome AS titular, t.orcamento_mensal AS orcado, COALESCE(SUM(v.valor), 0) AS total
           FROM titulares t
           LEFT JOIN vw_lancamentos v ON v.titular = t.nome AND v.conta = 1 AND substr(v.data, 1, 7) = ?
           GROUP BY t.id ORDER BY t.id""", (mes,))]
    sem_titular = soma("AND titular IS NULL")
    if sem_titular:
        por_titular.append({"titular": "Sem titular informado", "orcado": 0.0, "total": sem_titular})
    for t in por_titular:
        t["saldo"] = t["orcado"] - t["total"]
        t["pct"] = (t["total"] / t["orcado"] * 100) if t["orcado"] else None

    orcamento_categorias = [dict(r) for r in db.execute(
        """SELECT c.nome AS categoria, c.orcamento_mensal AS orcado, COALESCE(SUM(l.valor), 0) AS realizado
           FROM categorias c
           LEFT JOIN lancamentos l ON l.categoria_id = c.id AND substr(l.data, 1, 7) = ?
                AND NOT (l.forma_pagamento = 'Cartão de crédito' AND COALESCE(l.origem, '') != 'fatura' AND c.nome != 'Cartões de crédito')
           WHERE c.contabiliza = 1
           GROUP BY c.id
           HAVING realizado > 0 OR (c.ativa = 1 AND c.orcamento_mensal > 0)
           ORDER BY realizado DESC, c.nome""", (mes,))]

    meses = meses_anteriores(mes, 12)
    totais = {r["mes"]: r["total"] for r in db.execute(
        """SELECT substr(data, 1, 7) AS mes, SUM(valor) AS total FROM vw_lancamentos
           WHERE conta = 1 AND substr(data, 1, 7) BETWEEN ? AND ? GROUP BY 1""", (meses[0], meses[-1]))}
    serie = [{"mes": m, "total": totais.get(m, 0.0)} for m in meses]
    com_gasto = [x["total"] for x in serie if x["total"] > 0]
    periodo = {
        "serie": serie,
        "total": sum(x["total"] for x in serie),
        "media": (sum(com_gasto) / len(com_gasto)) if com_gasto else 0,
        "maior": max(com_gasto, default=0),
        "menor": min(com_gasto, default=0),
        "max_barra": max(com_gasto, default=0),
    }

    return templates.TemplateResponse(
        request, "dashboard.html",
        {"mes": mes, "mes_ant": mes_ant, "ind": indicadores, "cartoes": cartoes,
         "por_titular": por_titular, "orcamento_categorias": orcamento_categorias,
         "periodo": periodo, "vale": beneficios.resumo_do_mes(db, mes)},
    )


# ---------------------------------------------------------------------------
# Relatórios
# ---------------------------------------------------------------------------
@app.get("/relatorios")
def relatorios(request: Request, aba: str = "resumo", mes: str | None = None, meses: int = 1,
               titular: list[str] = Query(default=[]), db=Depends(get_db)):
    mes = _mes_valido(mes)
    aba = aba if aba in ("resumo", "analise") else "resumo"
    meses = meses if meses in (1, 3, 6, 12) else 1
    r = dados_relatorios(db, mes, titular, meses)
    filtro_url = "".join("&titular=" + urllib.parse.quote(t) for t in r["sel"]) if r["filtrado"] else ""
    return templates.TemplateResponse(
        request, "relatorios.html", {"aba": aba, "mes": mes, "meses": meses, "r": r, "filtro_url": filtro_url}
    )


# ---------------------------------------------------------------------------
# Lançamentos (CRUD)
# ---------------------------------------------------------------------------
TIPOS = ["Variável", "Recorrente", "Extra / Eventual"]
STATUS = ["Pago", "Pendente", "Agendado"]


def _opcoes(db):
    return {
        "categorias": db.execute("SELECT id, nome, grupo FROM categorias WHERE ativa = 1 ORDER BY grupo, nome").fetchall(),
        "titulares": db.execute("SELECT id, nome FROM titulares ORDER BY nome").fetchall(),
        "cartoes": db.execute("SELECT id, identificador FROM cartoes WHERE ativo = 1 ORDER BY identificador").fetchall(),
        "formas": FORMAS_PAGAMENTO, "vale_forma": beneficios.FORMA_PAGAMENTO,
        "vales": db.execute("""SELECT b.id, b.nome, t.nome AS titular FROM beneficios b JOIN titulares t ON t.id = b.titular_id
                               WHERE b.ativo = 1 ORDER BY t.nome, b.nome""").fetchall(),
        "familia_id": (db.execute("SELECT id FROM titulares WHERE nome = ?", (beneficios.TITULAR_FAMILIA,)).fetchone() or [None])[0],
        "tipos": TIPOS, "status_lista": STATUS,
    }


def _parse_valor(texto: str) -> float:
    """Aceita '1.234,56', '1234,56' ou '1234.56'."""
    t = texto.strip().replace("R$", "").replace(" ", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    return float(t)


def _mes_valido(mes: str | None) -> str:
    try:
        ano, m = (mes or "").split("-")
        return f"{int(ano):04d}-{int(m):02d}"
    except ValueError:
        return date.today().strftime("%Y-%m")


@app.get("/lancamentos")
def listar_lancamentos(request: Request, mes: str | None = None, db=Depends(get_db)):
    mes = _mes_valido(mes)
    lancamentos = db.execute(
        "SELECT * FROM vw_lancamentos WHERE substr(data, 1, 7) = ? ORDER BY data DESC, id DESC",
        (mes,),
    ).fetchall()
    total = sum(l["valor"] for l in lancamentos if l["conta"])
    return templates.TemplateResponse(
        request, "lancamentos.html", {"lancamentos": lancamentos, "mes": mes, "total": total}
    )


@app.get("/lancamentos/novo")
def form_novo(request: Request, db=Depends(get_db)):
    return templates.TemplateResponse(
        request, "lancamento_form.html",
        {"l": None, "hoje": date.today().isoformat(), "erro": None, **_opcoes(db)},
    )


@app.get("/lancamentos/{lid}/editar")
def form_editar(lid: int, request: Request, db=Depends(get_db)):
    l = db.execute("SELECT * FROM lancamentos WHERE id = ?", (lid,)).fetchone()
    if l is None:
        return RedirectResponse("/lancamentos", status_code=303)
    return templates.TemplateResponse(
        request, "lancamento_form.html", {"l": l, "erro": None, **_opcoes(db)}
    )


def _salvar(db, lid, data, categoria_id, descricao, titular_id, forma_pagamento,
            cartao_id, valor, tipo, status, parcela, observacoes):
    v = _parse_valor(valor)
    if v < 0:
        raise ValueError("Valor não pode ser negativo.")
    date.fromisoformat(data)
    campos = (data, categoria_id, descricao.strip() or None, titular_id or None,
              forma_pagamento, cartao_id or None, v, tipo, status,
              parcela.strip() or None, observacoes.strip() or None)
    if lid is None:
        db.execute(
            """INSERT INTO lancamentos (data, categoria_id, descricao, titular_id, forma_pagamento,
               cartao_id, valor, tipo, status, parcela, observacoes) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            campos,
        )
    else:
        db.execute(
            """UPDATE lancamentos SET data=?, categoria_id=?, descricao=?, titular_id=?, forma_pagamento=?,
               cartao_id=?, valor=?, tipo=?, status=?, parcela=?, observacoes=? WHERE id=?""",
            campos + (lid,),
        )
    db.commit()


@app.post("/lancamentos/salvar")
def salvar_lancamento(
    request: Request, db=Depends(get_db),
    id: int | None = Form(None), data: str = Form(...), categoria_id: int = Form(...),
    descricao: str = Form(""), titular_id: int | None = Form(None),
    forma_pagamento: str = Form(...), cartao_id: int | None = Form(None),
    valor: str = Form(...), tipo: str = Form(...), status: str = Form(...),
    parcela: str = Form(""), observacoes: str = Form(""), beneficio_id: int | None = Form(None),
):
    if forma_pagamento == beneficios.FORMA_PAGAMENTO and id is None:
        try:
            v = _parse_valor(valor)
            date.fromisoformat(data)
            if v <= 0 or not beneficio_id:
                raise ValueError("informe um valor maior que zero e o cartão vale alimentação/refeição.")
            familia = db.execute("SELECT id FROM titulares WHERE nome = ?", (beneficios.TITULAR_FAMILIA,)).fetchone()
            db.execute("""INSERT INTO beneficio_usos (beneficio_id, data, valor, descricao, categoria_id, titular_id)
                          VALUES (?,?,?,?,?,?)""",
                       (beneficio_id, data, v, descricao.strip() or None, categoria_id, familia[0] if familia else None))
            db.commit()
        except (ValueError, sqlite3.IntegrityError) as e:
            l = {"id": id, "data": data, "categoria_id": categoria_id, "descricao": descricao, "titular_id": titular_id,
                 "forma_pagamento": forma_pagamento, "cartao_id": cartao_id, "valor": valor, "tipo": tipo, "status": status,
                 "parcela": parcela, "observacoes": observacoes, "beneficio_id": beneficio_id}
            return templates.TemplateResponse(request, "lancamento_form.html",
                                              {"l": l, "erro": f"Dados inválidos: {e}", **_opcoes(db)}, status_code=422)
        return RedirectResponse(f"/cadastros/beneficios?ok={urllib.parse.quote('Uso registrado no cartão.')}", status_code=303)
    try:
        _salvar(db, id, data, categoria_id, descricao, titular_id, forma_pagamento,
                cartao_id, valor, tipo, status, parcela, observacoes)
    except (ValueError, sqlite3.IntegrityError) as e:
        l = {"id": id, "data": data, "categoria_id": categoria_id, "descricao": descricao,
             "titular_id": titular_id, "forma_pagamento": forma_pagamento, "cartao_id": cartao_id,
             "valor": valor, "tipo": tipo, "status": status, "parcela": parcela,
             "observacoes": observacoes}
        return templates.TemplateResponse(
            request, "lancamento_form.html",
            {"l": l, "erro": f"Dados inválidos: {e}", **_opcoes(db)}, status_code=422,
        )
    nota_fiscal.aprender_local(db, observacoes, categoria_id, descricao)  # lançamento vindo de QR de nota: lembra a categoria do local
    return RedirectResponse(f"/lancamentos?mes={data[:7]}", status_code=303)


@app.delete("/lancamentos/{lid}")
def excluir_lancamento(lid: int, db=Depends(get_db)):
    db.execute("DELETE FROM lancamentos WHERE id = ?", (lid,))
    db.commit()
    return HTMLResponse("")  # HTMX remove a linha (hx-swap="outerHTML")


@app.post("/lancamentos/{lid}/duplicar")
def duplicar_lancamento(lid: int, db=Depends(get_db)):
    cur = db.execute(
        """INSERT INTO lancamentos (data, categoria_id, descricao, titular_id, forma_pagamento,
           cartao_id, valor, tipo, status, parcela, observacoes)
           SELECT data, categoria_id, descricao, titular_id, forma_pagamento,
           cartao_id, valor, tipo, status, parcela, observacoes FROM lancamentos WHERE id = ?""",
        (lid,),
    )
    db.commit()
    if cur.rowcount == 0:
        return RedirectResponse("/lancamentos", status_code=303)
    return RedirectResponse(f"/lancamentos/{cur.lastrowid}/editar", status_code=303)


# ---------------------------------------------------------------------------
# Recorrentes (modelo mensal) e geração de lançamentos do mês
# ---------------------------------------------------------------------------
def _dia_no_mes(mes: str, dia: int | None) -> str:
    """Data ISO para o dia de vencimento, limitado ao último dia do mês (ex.: 31 em fevereiro)."""
    ano, m = int(mes[:4]), int(mes[5:7])
    ultimo = calendar.monthrange(ano, m)[1]
    return date(ano, m, min(dia or 1, ultimo)).isoformat()


@app.get("/recorrentes")
def listar_recorrentes(request: Request, mes: str | None = None, db=Depends(get_db),
                       gerados: int | None = None, ignorados: int | None = None):
    mes = _mes_valido(mes)
    recorrentes = db.execute(
        """SELECT r.id, c.nome AS categoria, r.descricao, r.dia_vencimento, r.valor_estimado,
                  r.forma_pagamento, t.nome AS titular, ca.identificador AS cartao, r.ativo, r.palavra_chave
           FROM recorrentes r
           JOIN categorias c ON c.id = r.categoria_id
           LEFT JOIN titulares t ON t.id = r.titular_id
           LEFT JOIN cartoes ca ON ca.id = r.cartao_id
           ORDER BY r.ativo DESC, r.dia_vencimento, c.nome"""
    ).fetchall()
    total_fixo = sum(r["valor_estimado"] for r in recorrentes if r["ativo"])
    return templates.TemplateResponse(
        request, "recorrentes.html",
        {"recorrentes": recorrentes, "total_fixo": total_fixo, "mes": mes,
         "gerados": gerados, "ignorados": ignorados},
    )


@app.post("/recorrentes/gerar")
def gerar_recorrentes(db=Depends(get_db), mes: str = Form(...)):
    mes = _mes_valido(mes)
    gerados = ignorados = 0
    for r in db.execute("SELECT * FROM recorrentes WHERE ativo = 1").fetchall():
        ja_existe = db.execute(
            """SELECT 1 FROM lancamentos
               WHERE substr(data, 1, 7) = ?
                 AND (recorrente_id = ?
                      OR (recorrente_id IS NULL AND tipo = 'Recorrente' AND categoria_id = ? AND descricao IS ?))""",
            (mes, r["id"], r["categoria_id"], r["descricao"]),
        ).fetchone()
        if ja_existe:
            ignorados += 1
            continue
        db.execute(
            """INSERT INTO lancamentos (data, categoria_id, descricao, titular_id, forma_pagamento,
               cartao_id, valor, tipo, status, recorrente_id) VALUES (?,?,?,?,?,?,?,'Recorrente','Pendente',?)""",
            (_dia_no_mes(mes, r["dia_vencimento"]), r["categoria_id"], r["descricao"],
             r["titular_id"], r["forma_pagamento"], r["cartao_id"], r["valor_estimado"], r["id"]),
        )
        gerados += 1
    db.commit()
    return RedirectResponse(f"/recorrentes?mes={mes}&gerados={gerados}&ignorados={ignorados}", status_code=303)


@app.get("/recorrentes/novo")
def form_novo_recorrente(request: Request, db=Depends(get_db)):
    return templates.TemplateResponse(request, "recorrente_form.html", {"r": None, "erro": None, **_opcoes(db)})


@app.get("/recorrentes/{rid}/editar")
def form_editar_recorrente(rid: int, request: Request, db=Depends(get_db)):
    r = db.execute("SELECT * FROM recorrentes WHERE id = ?", (rid,)).fetchone()
    if r is None:
        return RedirectResponse("/recorrentes", status_code=303)
    return templates.TemplateResponse(request, "recorrente_form.html", {"r": r, "erro": None, **_opcoes(db)})


@app.post("/recorrentes/salvar")
def salvar_recorrente(
    request: Request, db=Depends(get_db),
    id: int | None = Form(None), categoria_id: int = Form(...), descricao: str = Form(...),
    dia_vencimento: int = Form(...), valor_estimado: str = Form(...),
    forma_pagamento: str = Form(...), titular_id: int | None = Form(None),
    cartao_id: int | None = Form(None), ativo: str | None = Form(None),
    palavra_chave: str = Form(""),
):
    try:
        valor = _parse_valor(valor_estimado)
        if valor < 0:
            raise ValueError("Valor não pode ser negativo.")
        campos = (categoria_id, descricao.strip(), dia_vencimento, valor, forma_pagamento,
                  titular_id or None, cartao_id or None, 1 if ativo else 0, palavra_chave.strip() or None)
        if id is None:
            db.execute(
                """INSERT INTO recorrentes (categoria_id, descricao, dia_vencimento, valor_estimado,
                   forma_pagamento, titular_id, cartao_id, ativo, palavra_chave) VALUES (?,?,?,?,?,?,?,?,?)""", campos)
        else:
            db.execute(
                """UPDATE recorrentes SET categoria_id=?, descricao=?, dia_vencimento=?, valor_estimado=?,
                   forma_pagamento=?, titular_id=?, cartao_id=?, ativo=?, palavra_chave=? WHERE id=?""", campos + (id,))
        db.commit()
    except (ValueError, sqlite3.IntegrityError) as e:
        r = {"id": id, "categoria_id": categoria_id, "descricao": descricao,
             "dia_vencimento": dia_vencimento, "valor_estimado": valor_estimado,
             "forma_pagamento": forma_pagamento, "titular_id": titular_id,
             "cartao_id": cartao_id, "ativo": 1 if ativo else 0, "palavra_chave": palavra_chave}
        return templates.TemplateResponse(
            request, "recorrente_form.html",
            {"r": r, "erro": f"Dados inválidos: {e}", **_opcoes(db)}, status_code=422)
    return RedirectResponse("/recorrentes", status_code=303)


@app.post("/recorrentes/{rid}/alternar")
def alternar_recorrente(rid: int, db=Depends(get_db)):
    db.execute("UPDATE recorrentes SET ativo = 1 - ativo WHERE id = ?", (rid,))
    db.commit()
    return RedirectResponse("/recorrentes", status_code=303)


@app.delete("/recorrentes/{rid}")
def excluir_recorrente(rid: int, db=Depends(get_db)):
    db.execute("DELETE FROM recorrentes WHERE id = ?", (rid,))
    db.commit()
    return HTMLResponse("")


# ---------------------------------------------------------------------------
# Cadastros: categorias, cartões, titulares e parâmetros
# ---------------------------------------------------------------------------
ABAS_CADASTRO = {
    "categorias": "Categorias",
    "cartoes": "Cartões",
    "titulares": "Titulares",
    "beneficios": "Vale alimentação/refeição",
    "parametros": "Parâmetros",
    "usuarios": "Usuários",
}


def _volta(aba: str, erro: str | None = None) -> RedirectResponse:
    url = f"/cadastros/{aba}"
    if erro:
        url += "?erro=" + urllib.parse.quote(erro)
    return RedirectResponse(url, status_code=303)


def _executar(db, aba: str, sql: str, params: tuple) -> RedirectResponse:
    try:
        db.execute(sql, params)
        db.commit()
    except sqlite3.IntegrityError:
        return _volta(aba, "Não foi possível salvar: já existe um registro com esse nome/identificador.")
    return _volta(aba)


@app.get("/cadastros")
def cadastros_inicio():
    return RedirectResponse("/cadastros/categorias", status_code=303)


@app.get("/cadastros/{aba}")
def cadastros(aba: str, request: Request, erro: str | None = None, ok: str | None = None, db=Depends(get_db)):
    if aba not in ABAS_CADASTRO:
        raise HTTPException(status_code=404)
    ctx = {"aba": aba, "abas": ABAS_CADASTRO, "erro": erro, "ok": ok}
    if aba == "categorias":
        ctx["itens"] = db.execute("SELECT * FROM categorias ORDER BY ativa DESC, grupo, nome").fetchall()
        ctx["grupos"] = GRUPOS_CATEGORIA
        ctx["opcoes"] = opcoes
    elif aba == "cartoes":
        ctx["itens"] = db.execute("SELECT * FROM cartoes ORDER BY ativo DESC, identificador").fetchall()
        ctx["titulares"] = db.execute("SELECT id, nome FROM titulares ORDER BY nome").fetchall()
        ctx["bancos"] = BANCOS_EMISSORES
        ctx["opcoes"] = opcoes
    elif aba == "titulares":
        ctx["itens"] = db.execute("SELECT * FROM titulares ORDER BY nome").fetchall()
    elif aba == "beneficios":
        hoje = date.today()
        ctx["itens"] = db.execute("SELECT * FROM beneficios ORDER BY ativo DESC, nome").fetchall()
        ctx["titulares"] = db.execute("SELECT id, nome FROM titulares ORDER BY nome").fetchall()
        ctx["hoje"] = hoje.isoformat()
        ctx["saldos"] = {b["id"]: beneficios.saldo_em(db, b, hoje) for b in ctx["itens"]}
        ctx["usos"] = db.execute("""SELECT u.id, u.data, u.valor, u.descricao, b.nome AS cartao, t.nome AS dono,
                                           COALESCE(f.nome, 'Família (compartilhado)') AS titular
                                    FROM beneficio_usos u JOIN beneficios b ON b.id = u.beneficio_id
                                    JOIN titulares t ON t.id = b.titular_id
                                    LEFT JOIN titulares f ON f.id = u.titular_id ORDER BY u.data DESC, u.id DESC LIMIT 30""").fetchall()
    elif aba == "usuarios":
        ctx["itens"] = db.execute("SELECT id, usuario, nome, ativo, ultimo_login FROM usuarios ORDER BY nome").fetchall()
        ctx["eu"] = request.state.usuario["id"]
    else:
        p = {r["chave"]: float(r["valor"]) for r in db.execute("SELECT chave, valor FROM parametros")}
        ctx["meta"], ctx["teto"] = p.get("meta_economia_mensal", 0.0), p.get("teto_mensal", 0.0)
    return templates.TemplateResponse(request, "cadastros.html", ctx)


def _valor_da_lista(db, tabela: str, coluna: str, id: int | None, valor: str, lista: list[str]) -> bool:
    """O valor tem de estar na lista fixa, ou ser o que este mesmo registro já tem gravado (edição sem trocar)."""
    if valor in lista:
        return True
    if id is None:
        return False
    atual = db.execute(f"SELECT {coluna} FROM {tabela} WHERE id = ?", (id,)).fetchone()  # nosec B608 - tabela/coluna são constantes do código
    return atual is not None and atual[0] == valor


@app.post("/cadastros/categorias/salvar")
def salvar_categoria(
    db=Depends(get_db), id: int | None = Form(None), nome: str = Form(...), grupo: str = Form(...),
    orcamento_mensal: str = Form("0"), essencial: str | None = Form(None),
    ativa: str | None = Form(None), observacao: str = Form(""), contabiliza: str | None = Form(None),
):
    try:
        orc = _parse_valor(orcamento_mensal or "0")
    except ValueError:
        return _volta("categorias", "Orçamento mensal inválido.")
    grupo = grupo.strip()
    if not _valor_da_lista(db, "categorias", "grupo", id, grupo, GRUPOS_CATEGORIA):
        return _volta("categorias", "Escolha um grupo da lista. Para incluir um grupo novo, peça o cadastro.")
    campos = (nome.strip(), grupo, 1 if essencial else 0, orc, 1 if ativa else 0, observacao.strip() or None,
              1 if contabiliza else 0)
    if id is None:
        return _executar(db, "categorias", """INSERT INTO categorias
            (nome, grupo, essencial, orcamento_mensal, ativa, observacao, contabiliza) VALUES (?,?,?,?,?,?,?)""", campos)
    return _executar(db, "categorias", """UPDATE categorias SET nome=?, grupo=?, essencial=?,
        orcamento_mensal=?, ativa=?, observacao=?, contabiliza=? WHERE id=?""", campos + (id,))


@app.post("/cadastros/cartoes/salvar")
def salvar_cartao(
    db=Depends(get_db), id: int | None = Form(None), identificador: str = Form(...),
    titular_id: int = Form(...), banco: str = Form(...), ativo: str | None = Form(None),
    observacao: str = Form(""), palavra_chave: str = Form(""),
):
    banco = banco.strip()
    if not _valor_da_lista(db, "cartoes", "banco", id, banco, BANCOS_EMISSORES):
        return _volta("cartoes", "Escolha um banco/emissor da lista. Para incluir um novo, peça o cadastro.")
    campos = (identificador.strip(), titular_id, banco, 1 if ativo else 0, observacao.strip() or None,
              palavra_chave.strip() or None)
    if id is None:
        return _executar(db, "cartoes", """INSERT INTO cartoes
            (identificador, titular_id, banco, ativo, observacao, palavra_chave) VALUES (?,?,?,?,?,?)""", campos)
    return _executar(db, "cartoes", """UPDATE cartoes SET identificador=?, titular_id=?, banco=?,
        ativo=?, observacao=?, palavra_chave=? WHERE id=?""", campos + (id,))


@app.post("/cadastros/titulares/salvar")
def salvar_titular(db=Depends(get_db), id: int | None = Form(None), nome: str = Form(...), orcamento_mensal: str = Form("0")):
    try:
        orc = _parse_valor(orcamento_mensal or "0")
    except ValueError:
        return _volta("titulares", "Orçamento mensal inválido.")
    if orc < 0:
        return _volta("titulares", "O orçamento não pode ser negativo.")
    if id is None:
        return _executar(db, "titulares", "INSERT INTO titulares (nome, orcamento_mensal) VALUES (?, ?)", (nome.strip(), orc))
    return _executar(db, "titulares", "UPDATE titulares SET nome=?, orcamento_mensal=? WHERE id=?", (nome.strip(), orc, id))


@app.post("/cadastros/parametros/salvar")
def salvar_parametros(db=Depends(get_db), meta_economia_mensal: str = Form("0"), teto_mensal: str = Form("0")):
    try:
        valores = {"meta_economia_mensal": _parse_valor(meta_economia_mensal or "0"),
                   "teto_mensal": _parse_valor(teto_mensal or "0")}
    except ValueError:
        return _volta("parametros", "Valor inválido.")
    if any(v < 0 for v in valores.values()):
        return _volta("parametros", "Os valores não podem ser negativos.")
    for chave, v in valores.items():
        db.execute("INSERT INTO parametros (chave, valor) VALUES (?, ?) "
                   "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor", (chave, str(v)))
    db.commit()
    return _volta("parametros")
