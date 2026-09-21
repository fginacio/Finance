"""
Listas fixas do Cadastros (drop-down). Para incluir um item novo, acrescente aqui (ou peça).

Um valor que já estiver gravado num registro e não constar da lista continua aparecendo (e valendo) nesse registro,
mas não pode ser escolhido em outros.
"""

GRUPOS_CATEGORIA = [
    "Alimentação", "Comunicação", "Desenvolvimento", "Financeiro", "Lazer", "Metas", "Moradia",
    "Outros", "Pessoal", "Saúde e bem-estar", "Serviços", "Transporte",
]

BANCOS_EMISSORES = ["Banco do Brasil", "Bradesco", "Itaú Personalité", "Itaú Simples", "Nubank", "XP"]


def opcoes(lista: list[str], atual: str | None) -> list[str]:
    """A lista, mais o valor atual do registro caso ele não esteja nela (para não perdê-lo ao editar)."""
    return lista + [atual] if atual and atual not in lista else list(lista)
