"""
Consultas dos relatórios (Resumo Mensal e Análise) - SQL direto sobre vw_lancamentos.

O período (3, 6 ou 12 meses, escolhido na tela) sempre termina no mês selecionado.
Cartão e banco só somam lançamentos pagos com "Cartão de crédito" e cartão informado,
como na planilha.
"""
FORMAS_PAGAMENTO = ["Dinheiro", "PIX", "Débito", "Cartão de crédito", "Boleto",
                    "Débito automático", "Transferência / TED"]
SEM_TITULAR = "Sem titular informado"
NAO_CATEGORIA_CARTAO = "forma_pagamento = 'Cartão de crédito' AND cartao IS NOT NULL"


def meses_anteriores(mes: str, n: int) -> list[str]:
    """Os n meses que terminam em `mes` (inclusive), em ordem cronológica."""
    ano, m = int(mes[:4]), int(mes[5:7])
    meses = []
    for i in range(n - 1, -1, -1):
        total = ano * 12 + (m - 1) - i
        meses.append(f"{total // 12:04d}-{total % 12 + 1:02d}")
    return meses


def _matriz_base(db, meses, expr, chaves, where="1=1", filtro=("", ())):
    """Linhas {nome, valores[12], total} agrupadas por `expr`.

    `chaves` são as linhas que sempre aparecem; chaves não previstas com gasto entram ao final.
    """
    dados: dict[str, list[float]] = {}
    for r in db.execute(
        f"""SELECT {expr} AS k, substr(data, 1, 7) AS m, SUM(valor) AS t FROM vw_lancamentos
            WHERE conta = 1 AND substr(data, 1, 7) BETWEEN ? AND ? AND {where} {filtro[0]} GROUP BY k, m""",  # nosec B608 - expr/where/filtro são constantes do código (filtro só tem "?")
        (meses[0], meses[-1]) + tuple(filtro[1]),
    ):
        dados.setdefault(r["k"], [0.0] * len(meses))[meses.index(r["m"])] = r["t"]
    nomes = list(chaves) + [k for k in dados if k not in chaves]
    return [{"nome": k, "valores": dados.get(k, [0.0] * len(meses)),
             "total": sum(dados.get(k, [0.0]))} for k in nomes]


def _com_total_geral(linhas, n):
    return {"valores": [sum(l["valores"][i] for l in linhas) for i in range(n)],
            "total": sum(l["total"] for l in linhas)}


def dados_relatorios(db, mes: str, titulares_sel: list[str] | None = None, n_meses: int = 1) -> dict:
    """`titulares_sel`: só lançamentos desses titulares (vazio = todos, inclusive sem titular).

    `n_meses`: tamanho do período mostrado nas tabelas e no gráfico, terminando em `mes` (inclusive).
    """
    meses = meses_anteriores(mes, n_meses)
    n = len(meses)
    todos = [r["nome"] for r in db.execute("SELECT nome FROM titulares ORDER BY id")]
    sel = [t for t in (titulares_sel or []) if t in todos]
    filtrado = bool(sel) and len(sel) < len(todos)
    filtro = (f"AND titular IN ({','.join('?' * len(sel))})", tuple(sel)) if filtrado else ("", ())

    def _matriz(*a, **k):  # a mesma função de módulo, já com o filtro de titular aplicado
        return _matriz_base(*a, filtro=filtro, **k)

    # ---- por categoria (com orçado do período)
    cats = db.execute("SELECT nome, grupo, essencial, orcamento_mensal, ativa FROM categorias ORDER BY id").fetchall()
    info = {c["nome"]: c for c in cats}
    por_categoria = _matriz(db, meses, "categoria", [c["nome"] for c in cats if c["ativa"]])
    for l in por_categoria:
        c = info[l["nome"]]
        l["grupo"], l["essencial"] = c["grupo"], bool(c["essencial"])
        l["orcado"] = 0 if filtrado else c["orcamento_mensal"] * n  # o orçamento por categoria é da família toda
        l["orcado_mensal"] = 0 if filtrado else c["orcamento_mensal"]
    total_geral = _com_total_geral(por_categoria, n)

    grupos = [r["grupo"] for r in db.execute("SELECT grupo FROM categorias GROUP BY grupo ORDER BY MIN(id)")]
    titulares = [r["nome"] for r in db.execute("SELECT nome FROM titulares ORDER BY id")]
    cartoes = [r["identificador"] for r in db.execute("SELECT identificador FROM cartoes ORDER BY id")]
    bancos = [r["banco"] for r in db.execute("SELECT banco FROM cartoes GROUP BY banco ORDER BY MIN(id)")]

    por_titular = _matriz(db, meses, f"COALESCE(titular, '{SEM_TITULAR}')", titulares)
    por_titular = [l for l in por_titular if l["nome"] != SEM_TITULAR or l["total"] > 0]
    if filtrado:
        por_titular = [l for l in por_titular if l["nome"] in sel]
    por_cartao = _matriz(db, meses, "cartao", cartoes, NAO_CATEGORIA_CARTAO)
    por_banco = _matriz(db, meses, "banco", bancos, NAO_CATEGORIA_CARTAO)

    blocos = [
        ("Por grupo", _matriz(db, meses, "grupo", grupos)),
        ("Por titular", por_titular),
        ("Por cartão de crédito", por_cartao),
        ("Por banco / emissor (cartão de crédito)", por_banco),
        ("Por forma de pagamento", _matriz(db, meses, "forma_pagamento", FORMAS_PAGAMENTO)),
        ("Essencial x não essencial",
         _matriz(db, meses, "CASE WHEN essencial = 1 THEN 'Essencial' ELSE 'Não essencial' END",
                 ["Essencial", "Não essencial"])),
    ]

    # ---- análise
    total = total_geral["total"]

    def pct(v, base):
        return (v / base * 100) if base else 0.0

    top = sorted((l for l in por_categoria if l["total"] > 0), key=lambda l: l["total"], reverse=True)[:8]
    top = [{"nome": l["nome"], "grupo": l["grupo"], "total": l["total"], "pct": pct(l["total"], total)} for l in top]

    total_cartao = sum(l["total"] for l in por_cartao)
    titular_do_cartao = {r["identificador"]: r["titular"] for r in db.execute(
        "SELECT c.identificador, t.nome AS titular FROM cartoes c JOIN titulares t ON t.id = c.titular_id")}
    concentracao = [{"cartao": l["nome"], "titular": titular_do_cartao.get(l["nome"], "-"), "total": l["total"],
                     "pct": pct(l["total"], total_cartao)} for l in por_cartao]

    estouros = []
    for l in por_categoria:
        if l["orcado"] > 0 and l["total"] > l["orcado"]:
            estouros.append({"nome": l["nome"], "orcado": l["orcado"], "total": l["total"],
                             "excesso": l["total"] - l["orcado"], "pct": pct(l["total"], l["orcado"])})
    estouros.sort(key=lambda e: e["excesso"], reverse=True)

    cards = _cards(db, mes, filtro, por_categoria, filtrado)

    por_categoria = [l for l in por_categoria if l["total"] > 0]  # sem linhas zeradas no período: menos poluição visual
    blocos = [(titulo, [l for l in linhas if l["total"] > 0]) for titulo, linhas in blocos]
    if filtrado:  # sem cartões de outras pessoas
        concentracao = [c for c in concentracao if c["titular"] in sel]

    return {"meses": meses, "por_categoria": por_categoria, "total_geral": total_geral, "blocos": blocos,
            "top": top, "concentracao": concentracao, "total_cartao": total_cartao,
            "estouros": estouros, "total_periodo": total,
            "todos": todos, "sel": sel if filtrado else list(todos), "filtrado": filtrado,
            "grafico": _grafico(meses, por_titular),
            "cards": cards}


def _cards(db, mes, filtro, por_categoria, filtrado):
    """Resumo rápido do mês selecionado: total, variação vs mês anterior, orçamento, maior categoria.

    Sempre compara com um único mês anterior, independente do período (`n_meses`) mostrado nas tabelas.
    """
    mes_anterior = meses_anteriores(mes, 2)[0]
    total_mes = sum(l["valores"][-1] for l in por_categoria)
    total_anterior = db.execute(
        f"""SELECT COALESCE(SUM(valor), 0) AS t FROM vw_lancamentos
            WHERE conta = 1 AND substr(data, 1, 7) = ? {filtro[0]}""",  # nosec B608 - filtro só tem "?"
        (mes_anterior,) + tuple(filtro[1]),
    ).fetchone()["t"]
    variacao = total_mes - total_anterior
    variacao_pct = (variacao / total_anterior * 100) if total_anterior else None

    orcamento_mes = 0.0 if filtrado else sum(l["orcado_mensal"] for l in por_categoria)
    orcamento_pct = (total_mes / orcamento_mes * 100) if orcamento_mes else None

    com_gasto = [l for l in por_categoria if l["valores"][-1] > 0]
    maior = max(com_gasto, key=lambda l: l["valores"][-1]) if com_gasto else None
    maior_categoria = {"nome": maior["nome"], "valor": maior["valores"][-1],
                       "pct": (maior["valores"][-1] / total_mes * 100) if total_mes else 0.0} if maior else None

    return {"total_mes": total_mes, "variacao": variacao, "variacao_pct": variacao_pct,
            "orcamento_mes": orcamento_mes, "orcamento_pct": orcamento_pct,
            "maior_categoria": maior_categoria}


def _grafico(meses, por_titular):
    """Barras empilhadas por mês, uma cor por titular; o template desenha."""
    cores = ["#0d6efd", "#198754", "#fd7e14", "#6f42c1", "#6c757d"]
    series = [{"nome": l["nome"], "cor": cores[i % len(cores)], "valores": l["valores"]}
              for i, l in enumerate(por_titular) if l["total"] > 0]
    totais = [sum(s["valores"][i] for s in series) for i in range(len(meses))]
    return {"meses": meses, "series": series, "totais": totais, "maximo": max(totais, default=0)}
