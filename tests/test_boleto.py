"""Parser da linha digitável (boleto bancário e conta de consumo/convênio). Funções puras, sem banco."""
from app.boleto import parse_linha_digitavel


def test_convenio_conta_de_gas_real():
    # Linha digitável de uma conta de gás real (Consigaz), valor a pagar R$ 149,92.
    r = parse_linha_digitavel("83620000001 3 49920221202 7 61014000000 7 00008588439 3")
    assert r["tipo"] == "convenio"
    assert r["valor"] == 149.92
    assert r["vencimento"] is None
    assert r["avisos"] == []
    assert r["erro"] is None


def test_convenio_digito_verificador_errado():
    linha = "83620000001 9 49920221202 7 61014000000 7 00008588439 3"  # DV do 1º bloco trocado
    r = parse_linha_digitavel(linha)
    assert r["avisos"]  # avisa que não confere, mas ainda tenta extrair o valor


def test_boleto_bancario_47_digitos():
    linha = "00011234541234567890309876543217110050000015000"[:47]
    r = parse_linha_digitavel(linha)
    assert r["tipo"] == "boleto"
    assert r["valor"] == 150.0
    assert r["vencimento"] == "2025-02-27"
    assert r["avisos"] == []


def test_quantidade_invalida_de_digitos():
    r = parse_linha_digitavel("123 456")
    assert r["tipo"] is None
    assert r["erro"]


def test_ignora_pontuacao_na_colagem():
    r1 = parse_linha_digitavel("83620000001 3 49920221202 7 61014000000 7 00008588439 3")
    r2 = parse_linha_digitavel("83620000001-3.49920221202-7.61014000000-7.00008588439-3")
    assert r1["valor"] == r2["valor"]
