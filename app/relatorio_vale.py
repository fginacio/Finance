"""
Relatório do vale alimentação/refeição: saldo mês a mês por cartão, onde foi usado (categoria), evolução e a lista de usos.

Os números de cada mês vêm de `beneficios.resumo_do_mes`, o mesmo cálculo do card do Painel (saldo anterior + recargas
já caídas - usos). Nada daqui soma nos gastos.
"""
from app import beneficios
from app.relatorios import meses_anteriores

SEM_CATEGORIA = "Sem categoria"


def dados_vale(db, mes: str, n_meses: int = 6) -> dict:
    meses = meses_anteriores(mes, n_meses)

    # ---- saldo mês a mês, por cartão
    cartoes: dict[int, dict] = {}
    totais = []
    for m in meses:
        r = beneficios.resumo_do_mes(db, m)
        for c in r["lista"]:
            linha = cartoes.setdefault(c["id"], {"nome": c["nome"], "titular": c["titular"], "meses": {}})
            linha["meses"][m] = c
        totais.append({"mes": m, "saldo_anterior": sum(c["saldo_anterior"] for c in r["lista"]),
                       "recarga": sum(c["recarga"] for c in r["lista"]), "disponivel": r["disponivel"],
                       "usado": r["usado"], "restante": r["restante"]})
    por_cartao = [{"nome": c["nome"], "titular": c["titular"],
                   "linhas": [c["meses"].get(m) | {"mes": m} if m in c["meses"] else None for m in meses],
                   "usado": sum(x["usado"] for x in c["meses"].values()),
                   "recarga": sum(x["recarga"] for x in c["meses"].values())}
                  for c in cartoes.values()]

    # ---- onde foi usado
    dados: dict[str, list[float]] = {}
    for r in db.execute(
        f"""SELECT COALESCE(c.nome, '{SEM_CATEGORIA}') AS k, substr(u.data, 1, 7) AS m, SUM(u.valor) AS t
            FROM beneficio_usos u LEFT JOIN categorias c ON c.id = u.categoria_id
            WHERE substr(u.data, 1, 7) BETWEEN ? AND ? GROUP BY k, m""",  # nosec B608 - SEM_CATEGORIA é constante
        (meses[0], meses[-1]),
    ):
        dados.setdefault(r["k"], [0.0] * len(meses))[meses.index(r["m"])] = r["t"]
    total_usado = sum(sum(v) for v in dados.values())
    por_categoria = sorted(({"nome": k, "valores": v, "total": sum(v),
                             "pct": (sum(v) / total_usado * 100) if total_usado else 0.0} for k, v in dados.items()),
                           key=lambda l: l["total"], reverse=True)

    usos = [dict(r) for r in db.execute(
        f"""SELECT u.id, u.data, u.valor, u.descricao, COALESCE(c.nome, '{SEM_CATEGORIA}') AS categoria,
                   b.nome AS cartao, t.nome AS dono
            FROM beneficio_usos u JOIN beneficios b ON b.id = u.beneficio_id JOIN titulares t ON t.id = b.titular_id
            LEFT JOIN categorias c ON c.id = u.categoria_id
            WHERE substr(u.data, 1, 7) BETWEEN ? AND ? ORDER BY u.data DESC, u.id DESC""",  # nosec B608 - constante
        (meses[0], meses[-1]))]

    meses_com_uso = [t["usado"] for t in totais if t["usado"] > 0]
    return {"meses": meses, "totais": totais, "por_cartao": por_cartao, "por_categoria": por_categoria,
            "usos": usos, "total_usado": total_usado,
            "total_recarga": sum(t["recarga"] for t in totais),
            "media_uso": (sum(meses_com_uso) / len(meses_com_uso)) if meses_com_uso else 0.0,
            "saldo_atual": totais[-1]["restante"] if totais else 0.0,
            "ticket_medio": (total_usado / len(usos)) if usos else 0.0}
