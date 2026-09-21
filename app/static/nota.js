/* Leitura do QR da nota fiscal (usada em Novo lançamento e no resultado da leitura). Requer jsQR carregado antes. */
(function () {
    const foto = document.getElementById('foto'), status = document.getElementById('qr-status');
    document.getElementById('tirar-foto').addEventListener('click', () => foto.click());

    // Copia para a área de transferência. Em HTTP a API moderna não existe, então há o método antigo (textarea + execCommand).
    function copiar(texto) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(texto).then(() => true, () => copiarAntigo(texto));
        }
        return Promise.resolve(copiarAntigo(texto));
    }
    function copiarAntigo(texto) {
        const t = document.createElement('textarea');
        t.value = texto; t.setAttribute('readonly', ''); t.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
        document.body.appendChild(t); t.select(); t.setSelectionRange(0, texto.length);
        let ok = false;
        try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
        document.body.removeChild(t);
        return ok;
    }
    const chaveTexto = document.getElementById('chave-texto');
    if (chaveTexto) {
        const chave = chaveTexto.textContent.trim(), st = document.getElementById('chave-status');
        let jaCopiada = false;
        try { jaCopiada = sessionStorage.getItem('chaveCopiada') === chave; } catch (e) {}
        st.textContent = jaCopiada ? 'Chave copiada. É só colar no Méliuz.' : 'Toque em "Copiar chave" e cole no Méliuz.';
        st.className = 'small ' + (jaCopiada ? 'text-success' : 'text-muted');
        document.getElementById('copiar-chave').addEventListener('click', () => {
            Promise.resolve(copiar(chave)).then(ok => {
                st.textContent = ok ? 'Chave copiada. É só colar no Méliuz.' : 'Não deu para copiar sozinho: segure o número acima e escolha Copiar.';
                st.className = 'small ' + (ok ? 'text-success' : 'text-danger');
            });
        });
    }

    function tentar(img, largura) {
        const escala = Math.min(1, largura / Math.max(img.width, img.height));
        const c = document.createElement('canvas');
        c.width = Math.round(img.width * escala); c.height = Math.round(img.height * escala);
        const ctx = c.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(img, 0, 0, c.width, c.height);
        const dados = ctx.getImageData(0, 0, c.width, c.height);
        return jsQR(dados.data, c.width, c.height, { inversionAttempts: 'attemptBoth' });
    }

    // O CSP do app não permite imagens blob:, então a foto vira bitmap direto (ou data: URL como alternativa).
    function abrirImagem(arquivo) {
        if (window.createImageBitmap) return createImageBitmap(arquivo);
        return new Promise((ok, erro) => {
            const leitor = new FileReader();
            leitor.onload = () => { const img = new Image(); img.onload = () => ok(img); img.onerror = erro; img.src = leitor.result; };
            leitor.onerror = erro;
            leitor.readAsDataURL(arquivo);
        });
    }

    foto.addEventListener('change', () => {
        const arquivo = foto.files[0];
        if (!arquivo) return;
        status.textContent = 'Lendo o QR...';
        abrirImagem(arquivo).then(img => {
            let achou = null;
            for (const l of [1600, 1000, 700, 2400, 500]) { achou = tentar(img, l); if (achou) break; }
            if (!achou) { status.textContent = 'Não consegui ler o QR. Aproxime, deixe o QR reto, sem reflexo, e tente de novo.'; return; }
            status.textContent = 'QR lido. Consultando a Sefaz...';
            document.getElementById('conteudo').value = achou.data;
            const m = achou.data.match(/(?<!\d)\d{44}(?!\d)/);
            const enviar = () => document.getElementById('form-qr').submit();
            if (!m) { enviar(); return; }
            // Já copia a chave aqui (é o momento em que o navegador ainda aceita); a página seguinte mostra o resultado.
            Promise.resolve(copiar(m[0])).then(ok => {
                try { if (ok) sessionStorage.setItem('chaveCopiada', m[0]); } catch (e) {}
                enviar();
            });
        }).catch(() => { status.textContent = 'Não consegui abrir a imagem.'; });
    });
})();
