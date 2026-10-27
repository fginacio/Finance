"""
Relatório Personalizado: o usuário monta (agrupar por, período livre, filtros, gráfico) e pode salvar com um nome.

Um relatório salvo é só a querystring canônica da montagem (`Montagem.para_query`); abrir = redirecionar para ela.
"""
import urllib.parse

from app.filtros import Filtro
from app.relatorios import SEM_TITULAR, meses_anteriores

# agrupar por -> (rótulo, expressão SQL sobre vw_lancamentos)
AGRUPAMENTOS = {
    "categoria": ("Categoria", "categoria"),
    "grupo": ("Grupo", "grupo"),
    "titular": ("Titular", f"COALESCE(titular, '{SEM_TITULAR}')"),
    "forma": ("Forma de pagamento", "forma_pagamento"),
    "cartao": ("Cartão de crédito", "COALESCE(cartao, 'Sem cartão')"),
    "banco": ("Banco / emissor", "COALESCE(banco, 'Sem cartão')"),
    "essencial": ("Essencial x não essencial", "CASE WHEN essencial = 1 THEN 'Essencial' ELSE 'Não essencial' END"),
    "tipo": ("Tipo (variável, recorrente...)", "tipo"),
    "status": ("Status (pago, pendente...)", "status"),
    "descricao": ("Descrição (estabelecimento)", "COALESCE(NULLIF(TRIM(descricao), ''), '(sem descrição)')"),
}
GRAFICOS = {"barras": "Barras", "linhas": "Linhas", "pizza": "Pizza / rosca", "nenhum": "Sem gráfico"}
LIMITES = (0, 5, 10, 20)
ULTIMOS = (3, 6, 12, 24)  # período relativo: acompanha o mês atual (bom para relatório salvo)
MAX_MESES = 36


def _mes_ok(m: str | None) -> bool:
    return bool(m) and len(m) == 7 and m[4] == "-" and m[:4].isdigit() and m[5:].isdigit() and 1 <= int(m[5:]) <= 12


class Montagem:
    def __init__(self, agrupar="categoria", de=None, ate=None, por_mes=True, grafico="barras", limite=10,
                 filtro: Filtro | None = None, mes_padrao="2026-01", ultimos=0):
        self.ultimos = ultimos if ultimos in ULTIMOS else 0
        if self.ultimos:
            ate, de = mes_padrao, meses_anteriores(mes_padrao, self.ultimos)[0]
        self.agrupar = agrupar if agrupar in AGRUPAMENTOS else "categoria"
        self.ate = ate if _mes_ok(ate) else mes_padrao
        self.de = de if _mes_ok(de) and de <= self.ate else meses_anteriores(self.ate, 6)[0]
        self.meses = self._meses()
        self.de = self.meses[0]
        self.por_mes = bool(por_mes)
        self.grafico = grafico if grafico in GRAFICOS else "barras"
        self.limite = limite if limite in LIMITES else 10
        self.filtro = filtro or Filtro()

    def _meses(self) -> list[str]:
        meses = []
        a, m = int(self.ate[:4]), int(self.ate[5:])
        while len(meses) < MAX_MESES:
            atual = f"{a:04d}-{m:02d}"
            if atual < self.de:
                break
            meses.insert(0, atual)
            a, m = (a - 1, 12) if m == 1 else (a, m - 1)
        return meses

    @classmethod
    def da_query(cls, q, opcoes: dict, mes_padrao: str) -> "Montagem":
        """`q`: query_params do Starlette. Com `filtrar=1`, as caixas vêm do formulário (com_*); senão, da URL (sem_*)."""
        pares = q.multi_items()
        filtro = Filtro.do_formulario(pares, opcoes) if "filtrar" in q else Filtro.da_query(pares)
        def inteiro(chave, padrao):
            try:
                return int(q.get(chave, padrao))
            except ValueError:
                return padrao
        return cls(q.get("agrupar"), q.get("de"), q.get("ate"), q.get("colunas", "mes") == "mes",
                   q.get("grafico"), inteiro("limite", 10), filtro, mes_padrao, inteiro("ultimos", 0))

    def para_query(self) -> str:
        periodo = {"ultimos": self.ultimos} if self.ultimos else {"de": self.de, "ate": self.ate}
        base = urllib.parse.urlencode({"agrupar": self.agrupar, **periodo,
                                       "colunas": "mes" if self.por_mes else "total",
                                       "grafico": self.grafico, "limite": self.limite})
        f = self.filtro.para_query()
        return base + ("&" + f if f else "")


def dados_personalizado(db, mt: Montagem) -> dict:
    meses = mt.meses
    f_sql, f_params = mt.filtro.sql()
    expr = AGRUPAMENTOS[mt.agrupar][1]
    dados: dict[str, list[float]] = {}
    qtd: dict[str, int] = {}
    for r in db.execute(
        f"""SELECT {expr} AS k, substr(data, 1, 7) AS m, SUM(valor) AS t, COUNT(*) AS n FROM vw_lancamentos
            WHERE conta = 1 AND substr(data, 1, 7) BETWEEN ? AND ? {f_sql} GROUP BY k, m""",  # nosec B608 - expr vem de AGRUPAMENTOS; filtro só tem "?"
        (meses[0], meses[-1]) + f_params,
    ):
        dados.setdefault(r["k"], [0.0] * len(meses))[meses.index(r["m"])] = r["t"]
        qtd[r["k"]] = qtd.get(r["k"], 0) + r["n"]

    linhas = sorted(({"nome": k, "valores": v, "total": sum(v), "qtd": qtd[k]} for k, v in dados.items()),
                    key=lambda l: l["total"], reverse=True)
    if mt.limite and len(linhas) > mt.limite:  # o resto vira uma linha "Outros"
        resto = linhas[mt.limite:]
        linhas = linhas[:mt.limite] + [{"nome": f"Outros ({len(resto)})", "outros": True,
                                         "valores": [sum(l["valores"][i] for l in resto) for i in range(len(meses))],
                                         "total": sum(l["total"] for l in resto), "qtd": sum(l["qtd"] for l in resto)}]
    total = sum(l["total"] for l in linhas)
    for l in linhas:
        l["pct"] = (l["total"] / total * 100) if total else 0.0
        l["media"] = l["total"] / len(meses)
    total_geral = {"valores": [sum(l["valores"][i] for l in linhas) for i in range(len(meses))], "total": total,
                   "qtd": sum(l["qtd"] for l in linhas)}
    return {"meses": meses, "linhas": linhas, "total_geral": total_geral, "rotulo": AGRUPAMENTOS[mt.agrupar][0]}


# ---------------------------------------------------------------- relatórios salvos
def criar_estrutura(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS relatorios_salvos (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        nome        TEXT NOT NULL UNIQUE,
        params      TEXT NOT NULL,                     -- querystring canônica (Montagem.para_query)
        criado_em   TEXT NOT NULL DEFAULT (datetime('now'))
    )""")


def salvos(db) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT id, nome, params FROM relatorios_salvos ORDER BY nome COLLATE NOCASE")]
