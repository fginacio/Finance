/* Leitura de boleto/conta de consumo por arquivo: PDF vai direto pro servidor (extrai o texto); foto/imagem
   é decodificada aqui no navegador (ZXing lê código de barras linear, diferente do QR). Requer ZXing carregado antes. */
(function () {
    const arquivoInput = document.getElementById('boleto-arquivo'), status = document.getElementById('boleto-status');
    const btnFoto = document.getElementById('boleto-tirar-foto'), fotoInput = document.getElementById('boleto-foto');
    if (btnFoto) btnFoto.addEventListener('click', () => fotoInput.click());

    // O CSP do app não permite imagens blob:, então a foto vira data: URL (FileReader), como no leitor de QR.
    function abrirImagem(arquivo) {
        return new Promise((ok, erro) => {
            const leitor = new FileReader();
            leitor.onload = () => { const img = new Image(); img.onload = () => ok(img); img.onerror = erro; img.src = leitor.result; };
            leitor.onerror = erro;
            leitor.readAsDataURL(arquivo);
        });
    }

    // Reduz a foto (podem vir enormes da câmera) e devolve outra <img>, que é o que decodeFromImageElement aceita.
    function reduzir(img, largura) {
        const escala = Math.min(1, largura / Math.max(img.width, img.height));
        const c = document.createElement('canvas');
        c.width = Math.round(img.width * escala); c.height = Math.round(img.height * escala);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
        return new Promise((ok, erro) => {
            const img2 = new Image();
            img2.onload = () => ok(img2); img2.onerror = erro;
            img2.src = c.toDataURL('image/png');
        });
    }

    function decodificarBarras(img) {
        const leitor = new ZXing.BrowserMultiFormatReader();
        return reduzir(img, 1600).then(menor => leitor.decodeFromImageElement(menor));
    }

    function enviarLinha(linha) {
        const form = document.createElement('form');
        form.method = 'post'; form.action = '/lancamentos/boleto';
        const campo = document.createElement('input');
        campo.type = 'hidden'; campo.name = 'linha'; campo.value = linha;
        form.appendChild(campo); document.body.appendChild(form); form.submit();
    }

    function enviarPdf(arquivo) {
        const form = document.createElement('form');
        form.method = 'post'; form.action = '/lancamentos/boleto/arquivo'; form.enctype = 'multipart/form-data';
        const dt = new DataTransfer(); dt.items.add(arquivo);
        const campo = document.createElement('input');
        campo.type = 'file'; campo.name = 'arquivo'; campo.files = dt.files;
        form.appendChild(campo); document.body.appendChild(form); form.submit();
    }

    function processarArquivo(arquivo) {
        if (!arquivo) return;
        if (arquivo.type === 'application/pdf' || /\.pdf$/i.test(arquivo.name)) {
            status.textContent = 'Lendo o PDF...';
            enviarPdf(arquivo);
            return;
        }
        status.textContent = 'Lendo o código de barras...';
        abrirImagem(arquivo).then(img => decodificarBarras(img)).then(resultado => {
            status.textContent = 'Código lido. Consultando...';
            enviarLinha(resultado.getText());
        }).catch(() => {
            status.textContent = 'Não consegui ler o código de barras nessa foto. Aproxime, deixe reto, sem reflexo, '
                + 'ou cole a linha digitável manualmente ali embaixo.';
        });
    }

    if (fotoInput) fotoInput.addEventListener('change', () => processarArquivo(fotoInput.files[0]));
    if (arquivoInput) arquivoInput.addEventListener('change', () => processarArquivo(arquivoInput.files[0]));
})();
