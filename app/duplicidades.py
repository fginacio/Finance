"""
Varredura de possíveis lançamentos duplicados, incluindo os já validados.

Motivo de existir: a checagem feita na importação só olha linhas "a validar". Um gasto que entra por duas
vias (fatura em PDF e pagamento no extrato) e é validado antes de o outro chegar passaria despercebido.
"""
from datetime import date

from app.importacao import padrao

JANELA_DIAS = 3      # datas até N dias de distância entram na comparação
PONTOS_MINIMOS = 3   # abaixo disso o par não é mostrado


def _origem(l) -> str:
    return l["origem"] or "digitado"


def pontuar(a, b) -> tuple[int, list[str]]:
    """Pontua o quanto dois lançamentos de MESMO VALOR parecem ser o mesmo gasto."""
    pontos, motivos = 0, []
    if a["data"] == b["data"]:
        pontos += 3
        motivos.append("mesma data")
    else:
        dias = abs((date.fromisoformat(a["data"]) - date.fromisoformat(b["data"])).days)
        motivos.append(f"{dias} dia(s) de diferença")
    if _origem(a) != _origem(b):
        pontos += 2
        motivos.append(f"origens diferentes ({_origem(a)} e {_origem(b)})")
    if a["categoria"] == b["categoria"]:
        pontos += 1
        motivos.append("mesma categoria")
    if set(padrao(a["descricao"] or "").split()) & set(padrao(b["descricao"] or "").split()):
        pontos += 1
        motivos.append("descrições parecidas")
    return pontos, [m for m in motivos if m]


CABECALHO = ("v.id, v.data, v.valor, v.descricao, v.categoria, v.titular, v.forma_pagamento, v.cartao, v.origem, "
             "v.status, v.validado")


def _por_id(db, ids) -> dict:
    marcas = ",".join("?" * len(ids))
    return {r["id"]: r for r in db.execute(f"SELECT {CABECALHO} FROM vw_lancamentos v WHERE v.id IN ({marcas})", tuple(ids))}  # nosec B608 - `marcas` são só "?" e `CABECALHO` é constante


def grupos_identicos(db) -> list[dict]:
    """Lançamentos com valor, data, categoria e descrição idênticos (cópias exatas, ex.: do botão "Duplicar"
    sem ter mudado nada). Mostrados como um grupo único em vez de C(n, 2) pares."""
    linhas = db.execute(
        """SELECT GROUP_CONCAT(id) AS ids FROM lancamentos
           WHERE valor > 0
           GROUP BY valor, data, categoria_id, descricao
           HAVING COUNT(*) > 1""").fetchall()
    if not linhas:
        return []
    grupos_ids = [[int(i) for i in r["ids"].split(",")] for r in linhas]
    todos_ids = {i for ids in grupos_ids for i in ids}
    por_id = _por_id(db, todos_ids)
    grupos = []
    for ids in grupos_ids:
        itens = sorted((por_id[i] for i in ids if i in por_id), key=lambda l: l["id"])
        if len(itens) > 1:
            grupos.append({"itens": itens})
    grupos.sort(key=lambda g: (g["itens"][0]["data"], g["itens"][0]["id"]))
    return grupos


def pares_suspeitos(db) -> list[dict]:
    """Pares (a, b) de lançamentos com o mesmo valor em datas próximas, do mais ao menos provável.

    Exclui pares já cobertos por `grupos_identicos` (cópias exatas), que são mostrados agrupados.
    """
    cobertos = [{l["id"] for l in g["itens"]} for g in grupos_identicos(db)]
    linhas = db.execute(f"""
        SELECT a.id AS ida, b.id AS idb FROM lancamentos a JOIN lancamentos b
          ON a.id < b.id AND abs(a.valor - b.valor) < 0.005 AND abs(julianday(a.data) - julianday(b.data)) <= {JANELA_DIAS}
        WHERE a.valor > 0
          AND NOT EXISTS (SELECT 1 FROM duplicidades_ignoradas d WHERE d.a = a.id AND d.b = b.id)""").fetchall()  # nosec B608 - só a constante inteira JANELA_DIAS é interpolada
    if not linhas:
        return []
    ids = {r["ida"] for r in linhas} | {r["idb"] for r in linhas}
    por_id = _por_id(db, ids)
    pares = []
    for r in linhas:
        if any(r["ida"] in c and r["idb"] in c for c in cobertos):
            continue
        a, b = por_id[r["ida"]], por_id[r["idb"]]
        pontos, motivos = pontuar(a, b)
        if pontos >= PONTOS_MINIMOS:
            pares.append({"a": a, "b": b, "pontos": pontos, "motivos": motivos})
    pares.sort(key=lambda p: (-p["pontos"], p["a"]["data"], p["a"]["id"]))
    return pares
