"""
Versão do aplicativo e notas de versão (aparecem em Menu > Sobre).

Numeração (MAIOR.MENOR.CORREÇÃO): MENOR sobe quando entra uma função nova; CORREÇÃO, para ajustes e correções;
MAIOR, para mudanças grandes. Ao publicar uma versão nova: acrescente um item NO INÍCIO de NOTAS e o VERSAO acompanha
o primeiro item.
"""

NOTAS = [
    {
        "versao": "1.1.0", "data": "2026-09-25", "titulo": "Leitura de boleto/conta de consumo e débito automático nas faturas",
        "itens": [
            "Em Novo lançamento: além do QR da nota, agora dá para ler boleto ou conta de consumo (água, luz, gás, "
            "telefone) pela linha digitável — colando os números, subindo o PDF (extrai o texto) ou fotografando o "
            "código de barras (decodificado no navegador). Reconhece boleto bancário (47 dígitos, com vencimento) e "
            "conta de consumo/convênio (48 dígitos).",
            "Revisar faturas: o app percebe quando o texto do PDF já indica \"débito automático\" e mostra uma caixa "
            "pré-marcada; deixando marcada, o lançamento sai com essa forma de pagamento em vez de \"Boleto\".",
        ],
    },
    {
        "versao": "1.0.0", "data": "2026-09-21", "titulo": "Lançamento inicial",
        "itens": [
            "Lançamentos, recorrentes, cadastros (categorias, cartões, titulares, parâmetros) e painel do mês.",
            "Relatórios com período configurável, gráficos, orçamento por categoria e por titular.",
            "Importação de extrato bancário (OFX, CSV, XLSX, PDF) e de faturas em PDF, com detecção de duplicidades.",
            "Leitura do QR da nota fiscal para preencher um lançamento automaticamente.",
            "Login por usuário e senha, com sessões, bloqueio por tentativas e troca de senha.",
            "Avisos no Telegram: atividade em tempo real, orçamento estourado, gasto alto, contas pendentes perto do "
            "vencimento e resumo do fechamento do mês.",
            "Roda em Docker (frontend, backend e camada de dados) com backup diário e verificação de integridade.",
        ],
    },
]

VERSAO = NOTAS[0]["versao"]
DATA_VERSAO = NOTAS[0]["data"]
