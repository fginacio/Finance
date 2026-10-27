"""
Filtros de gastos compartilhados pelo Painel e pelo relatório Personalizado.

O filtro guarda o que foi DESMARCADO em cada dimensão (titular, grupo, categoria, forma de pagamento, essencial), e não o
que está marcado: assim uma categoria ou titular cadastrado depois já aparece incluído, sem precisar mexer no filtro.
Além das caixas, há uma busca livre por texto na descrição (ex.: "uber", "farmácia").

Na URL / cookie: `sem_<dimensao>=valor` (repetido) e `busca=texto`. O SQL gerado só tem "?" (valores vão como parâmetros).
"""
import urllib.parse

from app.relatorios import FORMAS_PAGAMENTO, SEM_TITULAR

SEM_CATEGORIA = "Sem categoria"

# dimensão -> (rótulo na tela, expressão SQL sobre vw_lancamentos; "{p}" é o prefixo da tabela/alias)
DIMENSOES = {
    "titular": ("Titulares", "COALESCE({p}titular, '" + SEM_TITULAR + "')"),
    "grupo": ("Grupos", "{p}grupo"),
    "categoria": ("Categorias", "{p}categoria"),
    "forma": ("Formas de pagamento", "{p}forma_pagamento"),
    "essencial": ("Essencial x não essencial", "CASE WHEN {p}essencial = 1 THEN 'Essencial' ELSE 'Não essencial' END"),
}
COOKIE_PAINEL = "cg_filtro_painel"


class Filtro:
    def __init__(self, excluidos: dict[str, set[str]] | None = None, busca: str = ""):
        self.excluidos = {d: set((excluidos or {}).get(d, ())) for d in DIMENSOES}
        self.busca = (busca or "").strip()[:100]

    # ------------------------------------------------------------ entrada / saída
    @classmethod
    def da_query(cls, pares) -> "Filtro":
        """`pares`: lista (chave, valor) da querystring ou do cookie (multi_items() / parse_qsl)."""
        excluidos: dict[str, set[str]] = {}
        busca = ""
        for k, v in pares:
            if k.startswith("sem_") and k[4:] in DIMENSOES:
                excluidos.setdefault(k[4:], set()).add(v)
            elif k == "busca":
                busca = v
        return cls(excluidos, busca)

    @classmethod
    def do_formulario(cls, pares, opcoes: dict[str, list[str]]) -> "Filtro":
        """Formulário de caixas: vem o que está MARCADO (`com_<dimensao>`); o resto das opções vira excluído."""
        marcados: dict[str, set[str]] = {d: set() for d in DIMENSOES}
        busca = ""
        for k, v in pares:
            if k.startswith("com_") and k[4:] in DIMENSOES:
                marcados[k[4:]].add(v)
            elif k == "busca":
                busca = v
        return cls({d: set(opcoes.get(d, [])) - marcados[d] for d in DIMENSOES}, busca)

    def para_query(self) -> str:
        pares = [(f"sem_{d}", v) for d in DIMENSOES for v in sorted(self.excluidos[d])]
        if self.busca:
            pares.append(("busca", self.busca))
        return urllib.parse.urlencode(pares)

    # ------------------------------------------------------------ uso
    @property
    def ativo(self) -> bool:
        return bool(self.busca) or any(self.excluidos.values())

    def inclui(self, dimensao: str, valor: str) -> bool:
        return valor not in self.excluidos[dimensao]

    def sql(self, prefixo: str = "") -> tuple[str, tuple]:
        """Trecho " AND ..." para o WHERE (ou o ON de um LEFT JOIN) e os parâmetros."""
        partes, params = [], []
        for d, (_, expr) in DIMENSOES.items():
            fora = sorted(self.excluidos[d])
            if fora:
                partes.append(f"{expr.format(p=prefixo)} NOT IN ({','.join('?' * len(fora))})")
                params += fora
        if self.busca:
            partes.append(f"LOWER(COALESCE({prefixo}descricao, '')) LIKE ?")
            params.append(f"%{self.busca.lower()}%")
        return "".join(" AND " + p for p in partes), tuple(params)

    def resumo(self) -> list[str]:
        """Texto curto do que está fora, para o aviso "filtro ativo"."""
        linhas = [f"{DIMENSOES[d][0]}: sem {', '.join(sorted(v))}" for d, v in self.excluidos.items() if v]
        if self.busca:
            linhas.append(f'Descrição contém "{self.busca}"')
        return linhas


def opcoes(db) -> dict[str, list[str]]:
    """Tudo o que pode ser marcado/desmarcado. Categorias inativas só entram se ainda tiverem lançamento."""
    titulares = [r["nome"] for r in db.execute("SELECT nome FROM titulares ORDER BY id")]
    if db.execute("SELECT 1 FROM lancamentos WHERE titular_id IS NULL LIMIT 1").fetchone():
        titulares.append(SEM_TITULAR)
    categorias = db.execute(
        """SELECT nome, grupo FROM categorias c WHERE contabiliza = 1
           AND (ativa = 1 OR EXISTS (SELECT 1 FROM lancamentos l WHERE l.categoria_id = c.id)) ORDER BY grupo, nome""").fetchall()
    grupos = list(dict.fromkeys(c["grupo"] for c in categorias))
    return {
        "titular": titulares,
        "grupo": grupos,
        "categoria": [c["nome"] for c in categorias],
        "forma": list(FORMAS_PAGAMENTO),
        "essencial": ["Essencial", "Não essencial"],
        # para a tela mostrar as categorias dentro do seu grupo
        "categorias_por_grupo": {g: [c["nome"] for c in categorias if c["grupo"] == g] for g in grupos},
    }
