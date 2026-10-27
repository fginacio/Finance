"""
Versão do aplicativo e notas de versão (aparecem em Menu > Sobre).

Numeração (MAIOR.MENOR.CORREÇÃO): MENOR sobe quando entra uma função nova; CORREÇÃO, para ajustes e correções;
MAIOR, para mudanças grandes. Ao publicar uma versão nova: acrescente um item NO INÍCIO de NOTAS e o VERSAO acompanha
o primeiro item.
"""

NOTAS = [
    {
        "versao": "1.3.0", "data": "2026-10-27", "titulo": "Painel com filtros e gráficos, relatório do vale e relatório personalizado",
        "itens": [
            "Painel: botão \"Filtros\" para desmarcar pessoas, grupos, categorias, formas de pagamento, essencial/não "
            "essencial e buscar por texto na descrição. O filtro fica lembrado neste navegador até clicar em \"Mostrar tudo\".",
            "Painel: gráfico de gastos por grupo no mês e gráfico dos últimos 12 meses com a linha da média (clique numa "
            "barra para abrir aquele mês). O card do vale alimentação/refeição ficou alinhado e não mostra mais \"-0,00\".",
            "Relatórios > Vale alimentação/refeição: saldo mês a mês por cartão, gráfico de recarga x uso, onde o vale foi "
            "usado (por categoria) e a lista de usos do período.",
            "Relatórios > Personalizado: escolha agrupar por (categoria, grupo, pessoa, cartão, descrição...), período "
            "livre ou \"últimos N meses\", filtros, tipo de gráfico e quantas linhas mostrar; salve com um nome para "
            "reabrir depois.",
            "Lançamentos e Relatórios mostram os usos do vale alimentação/refeição (etiqueta \"não soma · vale "
            "alimentação\" em Lançamentos; total do período como nota em Relatórios).",
            "Novo aviso no Telegram quando um lançamento novo fica idêntico (mesmo valor, data, categoria e descrição) a "
            "outro já existente.",
            "\"Lançar mês seguinte\" se desabilita assim que clicado (evita cópias por clique duplo); campos de valor "
            "aceitam só dígitos, com os dois últimos como centavos.",
        ],
    },
    {
        "versao": "1.2.0", "data": "2026-10-01", "titulo": "Duplicidades agrupadas e \"Lançar mês seguinte\"",
        "itens": [
            "Verificar duplicidades: lançamentos idênticos (mesmo valor, data, categoria e descrição) agora aparecem "
            "agrupados num único card, com um clique para manter um e remover todas as cópias — antes, cada cópia a "
            "mais virava vários pares combinatórios na lista, dando a impressão de que as duplicidades cresciam sozinhas.",
            "Em Lançamentos, o botão \"Duplicar\" virou \"Lançar mês seguinte\": a cópia já nasce com a data em +1 mês "
            "(em vez da mesma data do original) e status \"Pendente\", evitando criar duas entradas idênticas sem querer.",
        ],
    },
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
