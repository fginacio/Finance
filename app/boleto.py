"""
Leitura da linha digitável de boletos e contas de consumo (água, luz, gás, telefone...) a partir de
"Novo lançamento". Três jeitos de chegar aqui com o mesmo resultado:
- Colar a linha digitável direto (100% confiável).
- Subir o PDF do boleto: o código de barras linear (Interleaved 2 of 5) não dá pra ler direto do PDF,
  mas a maioria dos PDFs de boleto traz a linha digitável como texto selecionável — extrai_linha_de_texto
  procura esse texto (pypdf faz a extração, em app/rotas_boleto.py).
- Foto do código de barras: decodificada no navegador (ZXing), como o QR da nota.

Dois formatos, reconhecidos pela quantidade de dígitos:
- 47 dígitos: boleto bancário (título de cobrança). Traz valor e data de vencimento.
- 48 dígitos: conta de consumo / convênio (concessionárias, tributos, carnês). Só o valor costuma
  vir codificado; vencimento não faz parte do código de barras desse formato.

Referência: padrão FEBRABAN de código de barras e linha digitável.
"""
import re
from datetime import date, timedelta

# Base do "fator de vencimento" do boleto bancário. Zerou em 2025 (o campo de 4 dígitos estourou em
# 21/02/2025) e a FEBRABAN definiu uma nova contagem a partir dessa data, recomeçando do fator 1000.
_BASE_ANTIGA = date(1997, 10, 7)
_BASE_NOVA = date(2025, 2, 22)
_TROCA_FATOR = 1000


def _mod10(campo: str) -> int:
    soma, peso = 0, 2
    for d in reversed(campo):
        p = int(d) * peso
        soma += p // 10 + p % 10
        peso = 1 if peso == 2 else 2
    resto = soma % 10
    return 0 if resto == 0 else 10 - resto


def _mod11_boleto(campo: str) -> int:
    """DV geral do código de barras do boleto bancário (módulo 11, pesos 2..9)."""
    soma, peso = 0, 2
    for d in reversed(campo):
        soma += int(d) * peso
        peso = peso + 1 if peso < 9 else 2
    resto = soma % 11
    dv = 11 - resto
    return 1 if dv in (0, 10, 11) else dv


def _fator_para_data(fator: int) -> str | None:
    if fator <= 0:
        return None
    if fator >= _TROCA_FATOR:
        return (_BASE_NOVA + timedelta(days=fator - _TROCA_FATOR)).isoformat()
    return (_BASE_ANTIGA + timedelta(days=fator)).isoformat()


def _parse_boleto_bancario(d: str) -> dict:
    """Linha digitável de 47 dígitos (boleto de cobrança bancária)."""
    campo1, dv1 = d[0:9], d[9]
    campo2, dv2 = d[10:20], d[20]
    campo3, dv3 = d[21:31], d[31]
    dv_geral = d[32]
    fator, valor = d[33:37], d[37:47]
    r = {"tipo": "boleto", "linha": d, "valor": None, "vencimento": None, "erro": None, "avisos": []}
    if _mod10(campo1) != int(dv1) or _mod10(campo2) != int(dv2) or _mod10(campo3) != int(dv3):
        r["avisos"].append("Um dos dígitos verificadores dos campos não confere; confira os números digitados.")
    barra = campo1[:4] + dv_geral + fator + valor + campo1[4:] + campo2 + campo3
    if _mod11_boleto(barra[:4] + barra[5:]) != int(dv_geral):
        r["avisos"].append("O dígito verificador geral não confere; confira os números digitados.")
    try:
        r["valor"] = int(valor) / 100
    except ValueError:
        r["erro"] = "Não consegui ler o valor nessa linha digitável."
        return r
    r["vencimento"] = _fator_para_data(int(fator))
    return r


def _parse_convenio(d: str) -> dict:
    """Linha digitável de 48 dígitos (conta de consumo / concessionária / tributo)."""
    r = {"tipo": "convenio", "linha": d, "valor": None, "vencimento": None, "erro": None, "avisos": []}
    blocos = [d[0:11], d[12:23], d[24:35], d[36:47]]
    dvs = [d[11], d[23], d[35], d[47]]
    if any(_mod10(b) != int(dv) for b, dv in zip(blocos, dvs)):
        r["avisos"].append("Um dos dígitos verificadores dos blocos não confere; confira os números digitados.")
    barra = "".join(blocos)  # 44 dígitos: produto(1) + segmento(1) + dv geral(1) + indicador(1) + valor(11) + resto
    try:
        valor = int(barra[4:15])
    except ValueError:
        r["erro"] = "Não consegui ler o valor nessa linha digitável."
        return r
    if valor:
        r["valor"] = valor / 100
    else:
        r["avisos"].append("Essa conta não traz o valor no código de barras (é só uma referência); preencha o valor manualmente.")
    return r


def parse_linha_digitavel(texto: str) -> dict:
    """Recebe o texto colado (com ou sem espaços/pontos) e devolve tipo, valor e (se houver) vencimento."""
    d = re.sub(r"\D", "", texto or "")
    if len(d) == 47:
        return _parse_boleto_bancario(d)
    if len(d) == 48:
        return _parse_convenio(d)
    return {"tipo": None, "linha": d, "valor": None, "vencimento": None, "avisos": [],
            "erro": f"Encontrei {len(d)} dígitos; a linha digitável tem 47 (boleto) ou 48 (conta de consumo)."}


# Um dígito, opcionalmente seguido de espaço/ponto/hífen (como a linha vem impressa, em blocos).
_RE_48 = re.compile(r"(?<!\d)(?:\d[ .\-]?){47}\d(?!\d)")
_RE_47 = re.compile(r"(?<!\d)(?:\d[ .\-]?){46}\d(?!\d)")


def extrair_linha_de_texto(texto: str) -> str | None:
    """Procura uma linha digitável (47 ou 48 dígitos) dentro de um texto maior, como o extraído de um PDF.
    Tenta 48 dígitos primeiro (senão uma conta de consumo seria lida como boleto, já que todo 48 contém
    sequências de 47). Prefere um trecho cujos dígitos verificadores batam."""
    texto = texto or ""
    for regex in (_RE_48, _RE_47):
        candidatos = [re.sub(r"\D", "", m.group(0)) for m in regex.finditer(texto)]
        if not candidatos:
            continue
        for c in candidatos:
            if not parse_linha_digitavel(c)["avisos"]:
                return c
        return candidatos[0]  # nenhum bateu o DV, mas devolve o primeiro achado (melhor esforço)
    return None
