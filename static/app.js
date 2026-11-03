// State Management
let state = {
    sessionId: null,
    currentStep: 1,
    activeProvider: "gemini",
    documents: [],
    entities: [],
    skipped: [],
    sessionName: "",
    lastResult: null,
    currentViewMode: "decrypted" // 'decrypted' or 'masked'
};

// DOM Elements
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const filesContainer = document.getElementById('filesContainer');
const docGrid = document.getElementById('docGrid');
const docCount = document.getElementById('docCount');
const entityCount = document.getElementById('entityCount');
const entityTableBody = document.getElementById('entityTableBody');
const entitySearch = document.getElementById('entitySearch');

const navSteps = document.querySelectorAll('.step-item');
const provPills = document.querySelectorAll('.prov-pill');
const activeProviderLabel = document.getElementById('activeProviderLabel');
const execProviderName = document.getElementById('execProviderName');
const authStatusText = document.getElementById('authStatusText');
const openLoginBtn = document.getElementById('openLoginBtn');

const userInstructionInput = document.getElementById('userInstructionInput');
const runAnalysisBtn = document.getElementById('runAnalysisBtn');
const previewPromptBtn = document.getElementById('previewPromptBtn');
const preflightBox = document.getElementById('preflightBox');

const resultOutput = document.getElementById('resultOutput');
const viewDecryptedBtn = document.getElementById('viewDecryptedBtn');
const viewMaskedBtn = document.getElementById('viewMaskedBtn');
const downloadWordBtn = document.getElementById('downloadWordBtn');
const copyResultBtn = document.getElementById('copyResultBtn');
const resetSessionBtn = document.getElementById('resetSessionBtn');

const promptModal = document.getElementById('promptModal');
const closeModalBtn = document.getElementById('closeModalBtn');
const maskedPromptPreview = document.getElementById('maskedPromptPreview');
const copyModalPromptBtn = document.getElementById('copyModalPromptBtn');
const copyMaskedPromptBtn = document.getElementById('copyMaskedPromptBtn');

const manualResponseInput = document.getElementById('manualResponseInput');
const manualDeanonymizeBtn = document.getElementById('manualDeanonymizeBtn');

const addEntityModal = document.getElementById('addEntityModal');
const addEntityBtn = document.getElementById('addEntityBtn');
const closeAddModalBtn = document.getElementById('closeAddModalBtn');
const saveCustomEntityBtn = document.getElementById('saveCustomEntityBtn');

const loadingOverlay = document.getElementById('loadingOverlay');
const loadingTitle = document.getElementById('loadingTitle');
const loadingMsg = document.getElementById('loadingMsg');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    updateProviderUI("gemini");
    initVault();
});

// Any call answered "423 locked" (e.g. archive locked meanwhile) brings the password prompt back
// Per-start token, embedded by the server in the page it serves: every API call carries it
const APP_TOKEN = (document.querySelector('meta[name="privatedoc-token"]') || {}).content || "";
const _rawFetch = window.fetch.bind(window);
const _nativeFetch = (url, options = {}) => _rawFetch(url, {
    ...options,
    headers: {...(options.headers || {}), 'X-PrivateDoc-Token': APP_TOKEN}
});
// Tell the server when this page opens and closes: if the last one closes while the program keeps
// running in the background, the server warns the user (see backend/page_watch.py).
const PAGE_ID = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now();
const _pageEvent = (what, extra = {}) => _nativeFetch('/api/page/' + what, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({page_id: PAGE_ID}), ...extra
}).catch(() => {});
_pageEvent('open');
window.addEventListener('pageshow', (e) => { if (e.persisted) _pageEvent('open'); });
window.addEventListener('pagehide', () => _pageEvent('close', {keepalive: true}));

window.fetch = async (url, options) => {
    const resp = await _nativeFetch(url, options);
    if (resp.status === 423) initVault();
    return resp;
};

// One decision for every way out of the app (send, copy, copy from the preview):
// recognised data still readable blocks it; unrecognised words ask for the user's confirmation.
function allowedToLeave(preflight) {
    if (!preflight) return false;
    if ((preflight.leaks || []).length > 0) {
        alert("Operazione bloccata: alcuni dati sensibili risultano ancora in chiaro. Controlla l'avviso nella pagina.");
        return false;
    }
    const suspects = preflight.suspects || [];
    if (suspects.length > 0) {
        return confirm(`Queste parole potrebbero essere nomi non protetti:\n\n${suspects.join(", ")}\n\nNon sono state mascherate. Vuoi procedere comunque?`);
    }
    return true;
}

function setupEventListeners() {
    // Navigation Steps
    navSteps.forEach(item => {
        item.addEventListener('click', () => {
            const step = parseInt(item.getAttribute('data-step'));
            goToStep(step);
        });
    });

    document.getElementById('proceedToMaskingBtn')?.addEventListener('click', () => goToStep(2));
    document.getElementById('goToAnalyzeBtn')?.addEventListener('click', () => goToStep(3));
    document.getElementById('newAnalysisBtn')?.addEventListener('click', () => goToStep(3));

    // Provider Selector
    provPills.forEach(pill => {
        pill.addEventListener('click', () => {
            provPills.forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            const prov = pill.getAttribute('data-provider');
            updateProviderUI(prov);
        });
    });

    // Dropzone Events
    dropzone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => handleFiles(e.target.files));

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));

    dropzone.addEventListener('drop', async (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        // dropped folders must be walked: dataTransfer.files only holds an empty entry for them
        const entries = [...(e.dataTransfer.items || [])]
            .map(i => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null))
            .filter(Boolean);
        if (entries.length > 0) {
            handleFiles(await collectDroppedFiles(entries));
        } else {
            handleFiles(e.dataTransfer.files);
        }
    });

    // "Scegli una cartella" link inside the dropzone
    const folderInput = document.getElementById('folderInput');
    document.getElementById('pickFolderBtn').addEventListener('click', (e) => {
        e.stopPropagation();
        folderInput.click();
    });
    folderInput.addEventListener('change', (e) => {
        handleFiles([...e.target.files].map(f => ({file: f, path: f.webkitRelativePath || f.name})));
        e.target.value = '';
    });

    // Open Login Window (Browser Bridge for username & password)
    authStatusText.style.cursor = 'pointer';
    authStatusText.title = 'Clicca per ricontrollare la connessione';
    authStatusText.addEventListener('click', checkAuth);

    openLoginBtn.addEventListener('click', async () => {
        showLoading("Apertura finestra di login...", `Accedi con la tua email e password al tuo account ${getProviderDisplayName(state.activeProvider)}.`);
        try {
            const resp = await fetch('/api/auth/open-login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ provider: state.activeProvider })
            });
            const data = await resp.json();
            hideLoading();
            alert(data.message);
            checkAuth();
        } catch (err) {
            hideLoading();
            alert("Errore nell'avvio del browser di login: " + err.message);
        }
    });

    // User instruction changes update preflight dynamically
    let preflightDebounce = null;
    userInstructionInput.addEventListener('input', () => {
        clearTimeout(preflightDebounce);
        preflightDebounce = setTimeout(() => {
            refreshPreflight();
        }, 500);
    });

    // Entity Search
    entitySearch.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        renderEntities(query);
    });

    // Preview Prompt
    previewPromptBtn.addEventListener('click', async () => {
        if (!state.sessionId) {
            alert("Carica prima almeno un file!");
            return;
        }
        showLoading("Generazione prompt anonimo...", "Compilazione dei testi protetti in corso");
        try {
            const resp = await fetch('/api/prompt/generate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    session_id: state.sessionId,
                    instruction: userInstructionInput.value || "Confronta i documenti"
                })
            });
            const data = await resp.json();
            hideLoading();
            if (!resp.ok) {
                alert(data.detail || "Impossibile generare il testo.");
                return;
            }
            renderPreflight(data.preflight);
            maskedPromptPreview.textContent = data.prompt;
            promptModal.style.display = 'flex';
        } catch (err) {
            hideLoading();
            alert("Errore: " + err.message);
        }
    });

    closeModalBtn.addEventListener('click', () => promptModal.style.display = 'none');
    setupMaskContextMenu();
    copyModalPromptBtn.addEventListener('click', async () => {
        // re-check right now: the text may have changed since the preview was opened
        const resp = await fetch('/api/prompt/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({session_id: state.sessionId, instruction: userInstructionInput.value || "Confronta i documenti"})
        });
        const data = await resp.json();
        if (!resp.ok) { alert(data.detail || "Impossibile generare il testo."); return; }
        renderPreflight(data.preflight);
        if (!allowedToLeave(data.preflight)) return;
        navigator.clipboard.writeText(data.prompt);
        alert("Prompt anonimizzato copiato negli appunti!");
    });

    // Copies the anonymised text (after the same pre-flight check as every other way out); true if copied
    async function copyMaskedPrompt() {
        if (!state.sessionId) {
            alert("Carica prima almeno un file!");
            return false;
        }
        const resp = await fetch('/api/prompt/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_id: state.sessionId,
                instruction: userInstructionInput.value || "Confronta i documenti"
            })
        });
        const data = await resp.json();
        if (!resp.ok) {
            alert(data.detail || "Impossibile generare il testo.");
            return false;
        }
        renderPreflight(data.preflight);
        if (!allowedToLeave(data.preflight)) return false;
        await navigator.clipboard.writeText(data.prompt);
        return true;
    }

    copyMaskedPromptBtn.addEventListener('click', async () => {
        if (await copyMaskedPrompt()) alert("Prompt anonimizzato copiato! Incollalo ora nella chat del provider.");
    });

    // One click: copy the anonymised text, open the provider in the user's normal browser, wait for the answer
    async function copyAndOpenProvider() {
        const provider = MANUAL_PROVIDERS.includes(state.activeProvider) ? state.activeProvider : 'gemini';
        if (!(await copyMaskedPrompt())) return;
        window.open(PROVIDER_URLS[provider], '_blank', 'noopener');
        const hint = document.getElementById('copyHint');
        hint.textContent = `✓ Testo copiato. Incollalo (Ctrl+V) nella chat di ${getProviderDisplayName(provider)}, poi copia la risposta e incollala qui sotto.`;
        hint.style.display = 'block';
        manualResponseInput.scrollIntoView({behavior: 'smooth', block: 'center'});
        manualResponseInput.focus();
    }
    document.getElementById('copyOpenBtn').addEventListener('click', copyAndOpenProvider);

    // Manual Deanonymize
    manualDeanonymizeBtn.addEventListener('click', async () => {
        const text = manualResponseInput.value.trim();
        if (!text) {
            alert("Incolla prima il testo della risposta ottenuto dall'LLM!");
            return;
        }
        showLoading("Decifratura in corso...", "Sostituzione istantanea dei token con i dati originali");
        try {
            const resp = await fetch('/api/deanonymize', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    session_id: state.sessionId,
                    raw_response: text
                })
            });
            const data = await resp.json();
            hideLoading();
            state.lastResult = data.result;
            showResults();
        } catch (err) {
            hideLoading();
            alert("Errore nella decifratura: " + err.message);
        }
    });

    // Automated Execute
    runAnalysisBtn.addEventListener('click', async () => {
        if (!state.sessionId || state.documents.length === 0) {
            alert("Carica prima almeno un file da confrontare!");
            return;
        }
        if (MANUAL_PROVIDERS.includes(state.activeProvider)) {   // no automatic browser for these: copy and open
            await copyAndOpenProvider();
            return;
        }
        showLoading(
            "Analisi Protetta in corso...",
            `I documenti anonimizzati sono stati inviati alla sessione di ${getProviderDisplayName(state.activeProvider)}. In attesa della risposta...`
        );
        try {
            const send = (confirmedSuspects) => fetch('/api/execute', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    session_id: state.sessionId,
                    provider: state.activeProvider,
                    instruction: userInstructionInput.value || "Confronta e analizza i documenti",
                    confirmed_suspects: confirmedSuspects
                })
            });
            let data = await (await send([])).json();
            if (data.status === 'needs_confirmation') {
                hideLoading();
                if (!confirm(`Queste parole potrebbero essere nomi non protetti:\n\n${data.suspects.join(", ")}\n\nNon sono state mascherate. Vuoi inviare comunque?`)) {
                    refreshPreflight();
                    return;
                }
                showLoading("Analisi Protetta in corso...", "Invio confermato. In attesa della risposta...");
                data = await (await send(data.suspects)).json();
            }
            hideLoading();
            if (data.status === 'success') {
                state.lastResult = data.result;
                showResults();
            } else {
                renderPreflight(data.preflight);
                // If browser session is not logged in or encountered an issue, suggest the 1-click fallback
                alert(`Nota dal servizio: ${data.message}\n\nPuoi usare il pulsante "Accedi all'Account" nella barra laterale, oppure utilizzare il comodo pannello "Copia & Decifra" a destra!`);
                if (data.masked_prompt) {
                    maskedPromptPreview.textContent = data.masked_prompt;
                    promptModal.style.display = 'flex';
                }
            }
        } catch (err) {
            hideLoading();
            alert("Errore nell'esecuzione: " + err.message);
        }
    });

    // Result View Toggle
    viewDecryptedBtn.addEventListener('click', () => {
        viewDecryptedBtn.classList.add('active');
        viewMaskedBtn.classList.remove('active');
        state.currentViewMode = "decrypted";
        renderResultContent();
    });

    viewMaskedBtn.addEventListener('click', () => {
        viewMaskedBtn.classList.add('active');
        viewDecryptedBtn.classList.remove('active');
        state.currentViewMode = "masked";
        renderResultContent();
    });

    // Export Word
    downloadWordBtn.addEventListener('click', async () => {
        if (!state.sessionId) return;
        // fetch with the token header + Blob: the token never appears in a URL, log or history
        const resp = await fetch(`/api/export/docx?session_id=${encodeURIComponent(state.sessionId)}`);
        if (!resp.ok) { alert("Impossibile generare il report."); return; }
        const url = URL.createObjectURL(await resp.blob());
        const link = document.createElement('a');
        link.href = url;
        link.download = 'Report_Confronto_Documentale.docx';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
    });

    // Copy Result
    copyResultBtn.addEventListener('click', () => {
        const text = resultOutput.textContent;
        navigator.clipboard.writeText(text);
        alert("Testo del report copiato negli appunti!");
    });

    // Reset Session
    resetSessionBtn.addEventListener('click', async () => {
        if (confirm("Vuoi chiudere questa pratica e iniziarne una nuova? La pratica attuale resta salvata nell'elenco.")) {
            if (state.sessionId) {
                await fetch('/api/session/reset', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ session_id: state.sessionId })
                });
            }
            state.sessionId = null;
            state.skipped = [];
            renderSkipped();
            try { localStorage.removeItem('privatedoc_session'); } catch { /* ignore */ }
            state.documents = [];
            state.entities = [];
            state.lastResult = null;
            docGrid.innerHTML = '';
            filesContainer.style.display = 'none';
            state.sessionName = "";
            document.getElementById('praticaBar').style.display = 'none';
            goToStep(1);
            loadCases();
        }
    });

    document.getElementById('quitBtn').addEventListener('click', async () => {
        if (!confirm("Chiudere il programma? Un caricamento in corso verrà interrotto; le pratiche già salvate restano al sicuro.")) return;
        try {
            await _nativeFetch('/api/shutdown', {method: 'POST'});
        } catch { /* the server may drop the connection while closing */ }
        document.body.innerHTML = '<div style="font-family:sans-serif; color:#f8fafc; background:#0a0d14; height:100vh; display:flex; align-items:center; justify-content:center; text-align:center;"><div><h2>Programma chiuso</h2><p>Puoi chiudere questa scheda del browser.</p><p style="opacity:.7;">Per riaprirlo, rilancia PrivateDoc AI dall’icona.</p></div></div>';
    });

    document.getElementById('lockVaultBtn').addEventListener('click', async () => {
        await _nativeFetch('/api/vault/lock', {method: 'POST'});
        state.sessionId = null;
        state.documents = [];
        state.entities = [];
        state.skipped = [];
        renderSkipped();
        docGrid.innerHTML = '';
        filesContainer.style.display = 'none';
        document.getElementById('praticaBar').style.display = 'none';
        document.getElementById('casesBox').style.display = 'none';
        goToStep(1);
        initVault();
    });

    document.getElementById('praticaName').addEventListener('change', async (e) => {
        if (!state.sessionId) return;
        const name = e.target.value.trim();
        if (!name) { e.target.value = state.sessionName; return; }
        await fetch('/api/pratiche/rename', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: state.sessionId, name: name})
        });
        state.sessionName = name;
        loadCases();
    });

    // Custom Entity Modal
    addEntityBtn.addEventListener('click', async () => {
        const lib = await loadCategories();
        const select = document.getElementById('customEntityCategory');
        select.textContent = '';
        for (const c of [...lib.presets, ...lib.custom]) {
            const option = document.createElement('option');
            option.value = c.id;
            option.textContent = (lib.custom.includes(c) ? '★ ' : '') + c.label;
            select.appendChild(option);
        }
        addEntityModal.style.display = 'flex';
    });
    closeAddModalBtn.addEventListener('click', () => addEntityModal.style.display = 'none');
    saveCustomEntityBtn.addEventListener('click', async () => {
        const text = document.getElementById('customEntityText').value.trim();
        const cat = document.getElementById('customEntityCategory').value;
        if (!text) {
            alert("Inserisci il testo da mascherare!");
            return;
        }
        const resp = await fetch('/api/entity/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_id: state.sessionId,
                text: text,
                category: cat
            })
        });
        const data = await resp.json();
        state.entities = data.entities;
        renderEntities();
        addEntityModal.style.display = 'none';
        document.getElementById('customEntityText').value = '';
    });
}

// Upload Handler
// Walks dropped files/folders recursively, keeping each file's path inside the folder
async function collectDroppedFiles(entries) {
    const found = [];
    const readAll = (reader) => new Promise((resolve, reject) => {
        const all = [];
        const next = () => reader.readEntries((batch) => {
            if (batch.length === 0) resolve(all);
            else { all.push(...batch); next(); }
        }, reject);
        next();
    });
    const walk = async (entry) => {
        if (entry.isFile) {
            const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
            found.push({file: file, path: entry.fullPath.replace(/^\//, '')});
        } else if (entry.isDirectory) {
            for (const child of await readAll(entry.createReader())) await walk(child);
        }
    };
    for (const entry of entries) await walk(entry);
    return found;
}

async function handleFiles(fileList) {
    if (!fileList || fileList.length === 0) return;

    // Same shape for single files and for folder entries: {file, path}
    const items = [...fileList].map(i => (i.file ? i : {file: i, path: i.name}));
    const batches = makeBatches(items);
    const total = items.length;
    let done = 0;
    let cancelled = false;
    const cancelBtn = document.getElementById('loadingCancelBtn');
    const discardBtn = document.getElementById('loadingDiscardBtn');
    let discard = false;
    const operationId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
    const wasNewCase = !state.sessionId;
    const stop = (andDiscard) => {
        cancelled = true;
        discard = andDiscard;
        cancelBtn.disabled = discardBtn.disabled = true;
        (andDiscard ? discardBtn : cancelBtn).textContent = "Interruzione in corso...";
        _nativeFetch('/api/upload/cancel', {method: 'POST'});
    };
    cancelBtn.onclick = () => stop(false);
    discardBtn.onclick = () => stop(true);
    cancelBtn.disabled = discardBtn.disabled = false;
    cancelBtn.textContent = "Interrompi e tieni quanto caricato";
    discardBtn.textContent = "Interrompi e scarta";

    showLoading("Caricamento ed estrazione...", "Estrazione testi, tabelle, email e archivi in corso");
    const started = Date.now();
    updateProgress(0, total, "");

    // while one file is being read (a long scanned PDF) show how far the OCR is
    let ocrNote = "";
    const poll = setInterval(async () => {
        try {
            const p = await (await _nativeFetch('/api/upload/progress')).json();
            ocrNote = p.pages_total > 0
                ? (p.phase === 'ner'
                    ? ` · riconoscimento con il modello: ${p.pages_done} di ${p.pages_total} blocchi`
                    : ` · lettura pagine (OCR): ${p.pages_done} di ${p.pages_total}`)
                : "";
            updateProgress(done, total, currentName, started, ocrNote);
        } catch { /* ignore */ }
    }, 1000);
    let currentName = "";

    try {
        for (const batch of batches) {
            if (cancelled) break;
            currentName = batch[0].path;
            ocrNote = "";
            updateProgress(done, total, currentName, started, ocrNote);
            const formData = new FormData();
            if (state.sessionId) formData.append('session_id', state.sessionId);
            formData.append('operation_id', operationId);
            batch.forEach(item => formData.append('files', item.file, item.path));

            const resp = await fetch('/api/upload', {method: 'POST', body: formData});
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `errore ${resp.status}`);
            }
            const data = await resp.json();
            state.sessionId = data.session_id;
            state.documents = data.documents;
            state.entities = data.entities;
            state.skipped = data.skipped || [];
            setSessionName(data.name);
            saveSessionLocally();
            done += batch.length;
        }
        clearInterval(poll);
        hideLoading();
        renderSkipped();
        loadCases();
        renderDocumentGrid();
        renderEntities();
        if (cancelled && discard) {
            await discardUpload(operationId, wasNewCase);
        } else if (cancelled) {
            alert(`Caricamento interrotto: elaborati ${done} file su ${total}. Quanto già letto resta salvato nella pratica.`);
        }
    } catch (err) {
        clearInterval(poll);
        hideLoading();
        if (state.sessionId) {
            renderSkipped();
            renderDocumentGrid();
            renderEntities();
            loadCases();
        }
        alert(`Errore nel caricamento dopo ${done} file su ${total}: ` + err.message);
    }
}

// Undo an interrupted upload: remove what it added, or the whole case if it was created by it
async function discardUpload(operationId, wasNewCase) {
    if (!state.sessionId) return;
    if (wasNewCase) {
        await fetch('/api/pratiche/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: state.sessionId})
        });
        state.sessionId = null;
        state.documents = [];
        state.entities = [];
        state.skipped = [];
        try { localStorage.removeItem('privatedoc_session'); } catch { /* ignore */ }
        document.getElementById('praticaBar').style.display = 'none';
    } else {
        const resp = await fetch('/api/upload/discard', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({session_id: state.sessionId, operation_id: operationId})
        });
        if (resp.ok) {
            const data = await resp.json();
            state.documents = data.documents;
            state.skipped = data.skipped;
            state.entities = data.entities;
            renderEntities();
        }
    }
    renderSkipped();
    renderDocumentGrid();
    loadCases();
}

// Small batches keep each request short and give a real counter. PDFs go alone because
// scanned ones need OCR, which can take minutes per file.
function makeBatches(items) {
    const MAX_FILES = 8;
    const MAX_BYTES = 15 * 1024 * 1024;
    const batches = [];
    let current = [];
    let bytes = 0;
    const flush = () => { if (current.length) { batches.push(current); current = []; bytes = 0; } };
    for (const item of items) {
        const isPdf = item.path.toLowerCase().endsWith('.pdf');
        if (isPdf) {
            flush();
            batches.push([item]);
            continue;
        }
        if (current.length >= MAX_FILES || bytes + item.file.size > MAX_BYTES) flush();
        current.push(item);
        bytes += item.file.size;
    }
    flush();
    return batches;
}

function updateProgress(done, total, currentName, startedAt, ocrNote = "") {
    document.getElementById('loadingProgress').style.display = 'block';
    document.getElementById('loadingBar').style.width = `${total ? Math.round(done / total * 100) : 0}%`;
    let eta = "";
    if (startedAt && done > 0) {
        const perFile = (Date.now() - startedAt) / done;
        const secs = Math.round(perFile * (total - done) / 1000);
        eta = secs >= 60 ? ` · circa ${Math.ceil(secs / 60)} min rimasti` : ` · circa ${secs} s rimasti`;
    }
    document.getElementById('loadingCounter').textContent =
        `Elaborati ${done} di ${total} · mancano ${total - done}${eta}` + (currentName ? ` · in corso: ${currentName}` : "") + ocrNote;
}

// ---------- Encrypted archive: password + saved cases ----------
function setSessionName(name) {
    state.sessionName = name || "";
    const input = document.getElementById('praticaName');
    input.value = state.sessionName;
    document.getElementById('praticaBar').style.display = state.sessionId ? 'block' : 'none';
}

// ---------- Optional recogniser (model): always visible whether it is working ----------
async function loadNerStatus() {
    try {
        const st = await (await fetch('/api/ner/status')).json();
        const text = document.getElementById('nerStatusText');
        const row = document.getElementById('nerExtendedRow');
        if (st.state === 'verifying') {
            text.textContent = "⏳ Verifica dei file del modello in corso...";
            text.style.color = "var(--accent-amber)";
            setTimeout(loadNerStatus, 2000);   // until the check has finished
        } else if (st.active) {
            text.textContent = "✓ Attivo: regole + modello locale (file verificati)";
            text.style.color = "var(--accent-emerald)";
        } else if (st.state === 'rejected' || st.state === 'error' || st.state === 'missing') {
            text.textContent = "✗ " + st.reason.charAt(0).toUpperCase() + st.reason.slice(1);
            text.style.color = "var(--accent-amber)";
        } else {
            text.textContent = "⏸ " + st.reason.charAt(0).toUpperCase() + st.reason.slice(1);
            text.style.color = "var(--text-secondary)";
        }
        row.style.display = (st.state === 'ready' || st.state === 'off') ? 'block' : 'none';
        document.getElementById('nerDownloadBtn').style.display =
            (st.state === 'missing' || st.state === 'rejected') ? 'block' : 'none';
        document.getElementById('nerExtended').checked = !!st.extended;
        highlightNerDownload(st);
    } catch { /* ignore: the page works without it */ }
}

// First launch without the model: make the optional recogniser impossible to miss. Asked again on the
// next launch unless the user says "don't ask again"; never while a download is running or the model is active.
let nerWelcomeShown = false;
function highlightNerDownload(st) {
    const missing = st.state === 'missing';
    document.getElementById('nerBox').classList.toggle('ner-attention', missing);
    if (!missing || nerWelcomeShown) return;
    nerWelcomeShown = true;
    if (localStorage.getItem('nerWelcomeNever') === '1') return;
    document.getElementById('nerWelcomeModal').style.display = 'flex';
}
const closeNerWelcome = () => document.getElementById('nerWelcomeModal').style.display = 'none';
document.getElementById('nerWelcomeClose').addEventListener('click', closeNerWelcome);
document.getElementById('nerWelcomeLater').addEventListener('click', closeNerWelcome);
document.getElementById('nerWelcomeNever').addEventListener('click', () => {
    localStorage.setItem('nerWelcomeNever', '1');
    closeNerWelcome();
});
document.getElementById('nerWelcomeYes').addEventListener('click', () => {
    closeNerWelcome();
    document.getElementById('nerDownloadBtn').click();   // same explicit-consent dialog as the sidebar button
});

// ---------- Explicit model download (the only time the program goes online, and only after a yes) ----------
function formatMegabytes(bytes) {
    return (bytes / 1048576).toFixed(bytes >= 1073741824 ? 0 : 1) + ' MB';
}

async function pollModelDownload() {
    const box = document.getElementById('nerDownloadProgress');
    try {
        const st = await (await fetch('/api/model/status')).json();
        const active = st.state === 'downloading' || st.state === 'verifying' || st.state === 'installing';
        box.style.display = active ? 'block' : 'none';
        if (active) {
            const pct = st.total_bytes ? Math.round(100 * st.done_bytes / st.total_bytes) : 0;
            document.getElementById('nerDownloadBar').value = pct;
            const labels = {downloading: 'Scaricamento', verifying: 'Verifica dei file', installing: 'Installazione'};
            document.getElementById('nerDownloadText').textContent =
                `${labels[st.state]}: ${formatMegabytes(st.done_bytes)} di ${formatMegabytes(st.total_bytes)}` +
                (st.state === 'downloading' && st.speed ? ` · ${(st.speed / 1048576).toFixed(1)} MB/s` : '') +
                (st.error ? ` · ${st.error}` : '');
            setTimeout(pollModelDownload, 1000);
        } else {
            if (st.state === 'error') alert('Download del modello non riuscito: ' + st.error);
            loadNerStatus();
        }
    } catch { setTimeout(pollModelDownload, 3000); }
}

document.getElementById('nerDownloadBtn').addEventListener('click', async () => {
    try {
        const info = await (await fetch('/api/model/info')).json();
        document.getElementById('modelModalSize').textContent = formatMegabytes(info.total_bytes);
        document.getElementById('modelModalLicense').textContent = info.license;
        document.getElementById('modelModal').style.display = 'flex';
    } catch { alert('Impossibile leggere le informazioni sul modello.'); }
});
document.getElementById('modelModalNo').addEventListener('click', () => document.getElementById('modelModal').style.display = 'none');
document.getElementById('modelModalClose').addEventListener('click', () => document.getElementById('modelModal').style.display = 'none');
document.getElementById('modelModalYes').addEventListener('click', async () => {
    document.getElementById('modelModal').style.display = 'none';
    const resp = await fetch('/api/model/download', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({consent: true})
    });
    if (!resp.ok) { alert((await resp.json()).detail || 'Download non avviato.'); return; }
    pollModelDownload();
});
document.getElementById('nerDownloadCancel').addEventListener('click', async () => {
    await fetch('/api/model/cancel', {method: 'POST'});
});

document.getElementById('nerExtended').addEventListener('change', async (e) => {
    await fetch('/api/ner/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({extended: e.target.checked})
    });
    loadNerStatus();
});

async function initVault() {
    const st = await (await _nativeFetch('/api/vault/status')).json();
    if (!st.initialized) showVaultModal('setup', st);
    else if (!st.unlocked) showVaultModal('unlock', st);
    else await afterUnlock();
}

async function afterUnlock() {
    document.getElementById('vaultModal').style.display = 'none';
    checkAuth();
    loadNerStatus();
    pollModelDownload();   // shows the progress again if a download is running
    loadGeminiApi();
    await loadCases();
    await restoreSession();
}

function showVaultModal(mode, st) {
    const modal = document.getElementById('vaultModal');
    const title = document.getElementById('vaultTitle');
    const body = document.getElementById('vaultBody');
    const field = 'width:100%; padding:10px; margin:6px 0 12px 0; border-radius:6px; border:1px solid var(--border-color); background:var(--bg-base); color:var(--text-primary); font:inherit;';
    if (mode === 'setup') {
        title.textContent = "🔐 Scegli la password dell'archivio";
        body.innerHTML = `
            <p class="modal-desc">Le pratiche salvate sul computer vengono <strong>cifrate</strong> con questa password.</p>
            <div class="preflight-box block" style="margin:10px 0;"><strong>⚠️ Segnala la password in un posto sicuro.</strong><br>
            Non esiste alcun recupero: se la dimentichi, le pratiche salvate non potranno più essere lette.</div>
            <label>Password (minimo ${st.min_password_length} caratteri)</label>
            <input type="password" id="vaultPw1" autocomplete="new-password" style="${field}">
            <label>Ripeti la password</label>
            <input type="password" id="vaultPw2" autocomplete="new-password" style="${field}">
            <div id="vaultError" style="color:var(--accent-rose); min-height:1.2em; margin-bottom:8px;"></div>
            <button class="btn-primary" id="vaultSubmit">Crea archivio protetto</button>`;
    } else {
        title.textContent = "🔒 Archivio protetto";
        body.innerHTML = `
            <p class="modal-desc">Inserisci la password per aprire le tue pratiche.</p>
            <input type="password" id="vaultPw1" autocomplete="current-password" style="${field}">
            <div id="vaultError" style="color:var(--accent-rose); min-height:1.2em; margin-bottom:8px;"></div>
            <button class="btn-primary" id="vaultSubmit">Sblocca</button>`;
    }
    modal.style.display = 'flex';
    const pw1 = document.getElementById('vaultPw1');
    pw1.focus();
    const error = (msg) => { document.getElementById('vaultError').textContent = msg; };

    const submit = async () => {
        const password = pw1.value;
        const payload = {password: password};
        if (mode === 'setup') {
            payload.confirm = document.getElementById('vaultPw2').value;
            if (password.length < st.min_password_length) return error(`La password deve avere almeno ${st.min_password_length} caratteri.`);
            if (password !== payload.confirm) return error("Le due password non coincidono.");
        }
        const resp = await _nativeFetch(mode === 'setup' ? '/api/vault/setup' : '/api/vault/unlock', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            return error(err.detail || "Operazione non riuscita.");
        }
        if (mode === 'setup') {
            alert("Archivio creato. Ricorda: la password non può essere recuperata. Conservala in un posto sicuro.");
        }
        await afterUnlock();
    };
    document.getElementById('vaultSubmit').addEventListener('click', submit);
    body.querySelectorAll('input').forEach(i => i.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); }));
}

async function loadCases() {
    const resp = await fetch('/api/pratiche');
    if (!resp.ok) return;
    const cases = (await resp.json()).cases;
    const box = document.getElementById('casesBox');
    const list = document.getElementById('casesList');
    if (cases.length === 0) {
        box.style.display = 'none';
        return;
    }
    list.innerHTML = cases.map(c => `
        <div class="preflight-row">
            <div style="display:flex; flex-direction:column;">
                <span class="preflight-term" ${c.error ? 'style="color:var(--accent-rose);"' : ''}>${escapeHtml(c.name)}${c.id === state.sessionId ? ' <span style="color:var(--accent-emerald); font-size:0.75rem;">(aperta)</span>' : ''}</span>
                <span style="font-size:0.75rem; color:var(--text-secondary);">${c.document_count} documenti · aggiornata ${escapeHtml((c.updated || '').replace('T', ' ').slice(0, 16))}</span>
            </div>
            <div class="preflight-actions">
                ${c.error ? '' : `<button type="button" class="preflight-btn" data-case-action="open" data-id="${escapeHtml(c.id)}">Apri</button>`}
                <button type="button" class="preflight-btn" data-case-action="delete" data-id="${escapeHtml(c.id)}" data-name="${escapeHtml(c.name)}">Elimina</button>
            </div>
        </div>`).join("");
    box.style.display = 'block';
}

document.getElementById('casesBox').addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-case-action]');
    if (!btn) return;
    if (btn.dataset.caseAction === 'open') {
        await openCase(btn.dataset.id, 2);
    } else if (confirm(`Eliminare definitivamente la pratica «${btn.dataset.name}»? L'operazione non si può annullare.`)) {
        await fetch('/api/pratiche/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: btn.dataset.id})
        });
        if (btn.dataset.id === state.sessionId) {
            state.sessionId = null;
            state.documents = [];
            state.entities = [];
            docGrid.innerHTML = '';
            filesContainer.style.display = 'none';
            document.getElementById('praticaBar').style.display = 'none';
        }
        loadCases();
    }
});

async function openCase(id, step) {
    const resp = await fetch('/api/pratiche/open', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: id})
    });
    if (!resp.ok) return false;
    const data = await resp.json();
    state.sessionId = data.session_id;
    state.documents = data.documents;
    state.entities = data.entities;
    state.skipped = data.skipped || [];
    setSessionName(data.name);
    renderSkipped();
    renderDocumentGrid();
    renderEntities();
    saveSessionLocally();
    goToStep(step);
    loadCases();
    return true;
}

// ---------- Choose which documents go into the request ----------
function renderDocSelector() {
    const box = document.getElementById('docSelector');
    const docs = state.documents || [];
    if (docs.length === 0) {
        box.style.display = 'none';
        return;
    }
    const selected = docs.filter(d => d.selected !== false).length;
    box.innerHTML = `
        <div style="display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; margin-bottom:8px;">
            <label style="display:flex; align-items:center; gap:8px; cursor:pointer; color:var(--text-primary); font-weight:600;">
                <input type="checkbox" id="selectAllDocs"> Seleziona tutti
            </label>
            <span style="font-size:0.82rem; color:var(--text-secondary);">${selected} di ${docs.length} documenti inclusi nella richiesta</span>
        </div>
        <div style="max-height:200px; overflow:auto;">
            ${docs.map(d => `
                <label class="preflight-row" style="cursor:pointer; margin-bottom:4px;">
                    <span style="display:flex; align-items:center; gap:8px; min-width:0;">
                        <input type="checkbox" class="doc-check" data-id="${escapeHtml(d.id)}" ${d.selected !== false ? 'checked' : ''}>
                        <span class="preflight-term">Documento ${d.number}</span>
                        <span style="font-size:0.82rem; color:var(--text-secondary); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                            ${escapeHtml(d.filename)}${d.source_archive ? ' · in ' + escapeHtml(d.source_archive) : ''}
                        </span>
                    </span>
                    <span style="display:flex; align-items:center; gap:8px;">
                        <span style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml((d.file_type || '').toUpperCase())}</span>
                        <button type="button" class="preflight-btn doc-remove" data-id="${escapeHtml(d.id)}" data-label="Documento ${d.number}: ${escapeHtml(d.filename)}" title="Rimuovi dalla pratica">🗑 Rimuovi</button>
                    </span>
                </label>`).join("")}
        </div>
        <p style="margin:8px 0 0 0; font-size:0.78rem; color:var(--text-muted);">Il modello vede solo i documenti spuntati, numerati come qui (i nomi dei file non vengono inviati). Nella richiesta puoi scrivere, ad esempio, «confronta il Documento 3 con il Documento 7».</p>`;
    box.style.display = 'block';

    const all = document.getElementById('selectAllDocs');
    all.checked = selected === docs.length;
    all.indeterminate = selected > 0 && selected < docs.length;
    all.addEventListener('change', () => saveDocSelection(all.checked ? docs.map(d => d.id) : []));
    box.querySelectorAll('.doc-remove').forEach(btn => btn.addEventListener('click', (e) => {
        e.preventDefault();  // the button sits inside the row's <label>: do not toggle the checkbox
        e.stopPropagation();
        removeDocument(btn.dataset.id, btn.dataset.label);
    }));
    box.querySelectorAll('.doc-check').forEach(cb => cb.addEventListener('change', () => {
        saveDocSelection([...box.querySelectorAll('.doc-check')].filter(c => c.checked).map(c => c.dataset.id));
    }));
}

async function removeDocument(id, label) {
    if (!state.sessionId) return;
    if (!confirm(`Rimuovere «${label}» dalla pratica?\n\nIl testo del documento viene eliminato.`)) return;
    const purge = confirm("Eliminare anche i dati protetti (nomi, società…) presenti solo in questo documento?\n\nOK = elimina anche quelli (le risposte già salvate che li usano non potranno più essere decifrate).\nAnnulla = li tieni nell'elenco del passo 2, per mantenere gli stessi codici.");
    const resp = await fetch('/api/documents/remove', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({session_id: state.sessionId, id: id, purge: purge})
    });
    if (!resp.ok) return;
    const result = await resp.json();
    state.documents = result.documents;
    state.entities = result.entities;
    renderEntities();
    renderDocumentGrid();
    loadCases();
    if (state.currentStep === 3) refreshPreflight();
}

async function saveDocSelection(ids) {
    if (!state.sessionId) return;
    const resp = await fetch('/api/documents/select', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({session_id: state.sessionId, selected_ids: ids})
    });
    if (!resp.ok) return;
    state.documents = (await resp.json()).documents;
    renderDocSelector();
    refreshPreflight();
}

function renderSkipped() {
    const box = document.getElementById('skippedBox');
    const skipped = state.skipped || [];
    if (skipped.length === 0) {
        box.style.display = 'none';
        return;
    }
    box.innerHTML = `<div style="color:var(--accent-rose); font-weight:600; margin-bottom:8px;">⚠️ ${skipped.length} file non verranno considerati nell'analisi</div>` +
        skipped.map(f => `
            <div class="preflight-row" style="flex-direction:column; align-items:flex-start; gap:2px;">
                <span class="preflight-term">${escapeHtml(f.filename)}</span>
                <span style="font-size:0.78rem; color:var(--text-secondary);">Percorso: ${escapeHtml(f.path)}</span>
                <span style="font-size:0.78rem; color:var(--accent-amber);">Motivo: ${escapeHtml(f.reason)}</span>
            </div>`).join("");
    box.style.display = 'block';
}

const MODEL_STATE_LABELS = {
  errore: 'il modello ha dato errore',
  rifiutato: 'file del modello non verificati',
  interrotto: 'analisi interrotta',
};

function renderDocumentGrid() {
    renderDocSelector();
    docCount.textContent = state.documents.length;
    docGrid.innerHTML = '';
    filesContainer.style.display = state.documents.length ? 'block' : 'none';

    state.documents.forEach(doc => {
        const card = document.createElement('div');
        card.className = 'doc-card';
        
        let icon = "📄";
        if (doc.file_type === 'zip') icon = "📦";
        else if (['xlsx', 'xls', 'csv'].includes(doc.file_type)) icon = "📊";
        else if (['eml', 'msg'].includes(doc.file_type)) icon = "✉️";
        else if (['docx', 'doc', 'odt'].includes(doc.file_type)) icon = "📝";
        else if (doc.file_type === 'pdf') icon = "📑";

        const sourceHtml = doc.source_archive ? 
            `<div class="doc-card-source">📦 Estratto da: ${escapeHtml(doc.source_archive)}</div>` : '';

        card.innerHTML = `
            <div class="doc-card-header">
                <span class="doc-card-icon">${icon}</span>
                <div>
                    <div class="doc-card-title">Documento ${doc.number}: ${escapeHtml(doc.filename)}</div>
                </div>
            </div>
            ${sourceHtml}
            <div class="doc-card-meta">
                <span>Formato: <strong>${doc.file_type.toUpperCase()}</strong></span>
                <span>${doc.char_count.toLocaleString()} caratteri</span>
            </div>
            ${doc.model === 'ok' ? '<div class="doc-card-source">🧠 Analizzato con regole + modello</div>'
              : (doc.model === 'interrotto' || doc.model === 'errore' || doc.model === 'rifiutato')
                ? `<div class="doc-card-source" style="color:var(--accent-amber);">⚠ Solo regole (${MODEL_STATE_LABELS[doc.model]})</div>`
                : '<div class="doc-card-source" style="color:var(--text-muted);">Solo regole (modello non usato)</div>'}
            <div style="margin-top:8px;"><button type="button" class="preflight-btn card-remove">🗑 Rimuovi dalla pratica</button></div>
        `;
        card.querySelector('.card-remove').addEventListener('click', () =>
            removeDocument(doc.id, `Documento ${doc.number}: ${doc.filename}`));
        docGrid.appendChild(card);
    });
}

function renderEntities(filter = "") {
    entityCount.textContent = state.entities.length;
    entityTableBody.innerHTML = '';

    const filtered = state.entities.filter(e => 
        e.original.toLowerCase().includes(filter) || 
        e.token.toLowerCase().includes(filter) ||
        e.category.toLowerCase().includes(filter)
    );

    if (filtered.length === 0) {
        entityTableBody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:var(--text-muted); padding:24px;">Nessun dato corrispondente.</td></tr>`;
        return;
    }

    filtered.forEach(item => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${escapeHtml(item.original)}</strong></td>
            <td><span class="category-tag">${escapeHtml(item.category)}</span></td>
            <td><span class="token-badge">${escapeHtml(item.token)}</span></td>
            <td>
                <button class="btn-text entity-merge" data-token="${escapeHtml(item.token)}" title="Dice che questa voce e un'altra sono la stessa">Unisci a…</button>
                <button class="btn-text" style="color:var(--accent-rose);" onclick="removeEntity('${escapeHtml(item.token)}')">Rimuovi</button>
            </td>
        `;
        entityTableBody.appendChild(tr);
    });
}

// "Unisci a…": the user tells that two entries are the same party; they will share ONE code
entityTableBody.addEventListener('click', (e) => {
    const btn = e.target.closest('.entity-merge');
    if (!btn) return;
    e.stopPropagation();
    const source = state.entities.find(x => x.token === btn.dataset.token);
    if (!source) return;
    openEntityPopover(btn, state.entities.filter(x => x.token !== source.token), async (target) => {
        if (!confirm(`«${source.original}» e «${target.original}» diventano la stessa parte, con il codice ${target.token}. Procedere?`)) return;
        const resp = await fetch('/api/entity/merge', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({session_id: state.sessionId, source_token: source.token, target_token: target.token})
        });
        const data = await resp.json();
        if (!resp.ok) { alert(data.detail || 'Unione non riuscita.'); return; }
        state.entities = data.entities;
        renderEntities(entitySearch ? entitySearch.value.toLowerCase() : "");
        refreshPreflight();
    });
});

// A small floating list with a search box to pick ONE of the protected entries
function openEntityPopover(anchor, entities, onPick) {
    closeCategoryPopover();
    const box = document.createElement('div');
    box.className = 'ctx-menu cat-popover';
    const rect = anchor.getBoundingClientRect();
    box.style.position = 'fixed';
    box.style.left = `${Math.max(8, Math.min(rect.left - 120, window.innerWidth - 300))}px`;
    box.style.top = `${rect.bottom + 4}px`;
    box.addEventListener('click', (ev) => ev.stopPropagation());
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'cat-search';
    input.placeholder = 'Cerca la voce con cui unire…';
    const list = document.createElement('div');
    list.className = 'cat-list';
    box.append(input, list);
    function render() {
        const q = input.value.trim();
        const rows = entities.map(x => ({x, s: fuzzyScore(q, x.original)})).filter(r => r.s >= 0)
            .sort((a, b) => b.s - a.s).slice(0, 12);
        list.textContent = '';
        rows.forEach(({x}) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'cat-row';
            b.textContent = `${x.original}  ·  ${x.token}`;
            b.addEventListener('mousedown', (ev) => { ev.preventDefault(); closeCategoryPopover(); onPick(x); });
            list.appendChild(b);
        });
        if (!rows.length) list.textContent = 'Nessuna voce corrispondente.';
    }
    input.addEventListener('input', render);
    input.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') { const first = list.querySelector('.cat-row'); if (first) first.dispatchEvent(new MouseEvent('mousedown')); ev.preventDefault(); }
    });
    render();
    document.body.appendChild(box);
    pickerPopover = box;
    setTimeout(() => input.focus(), 0);
}

async function removeEntity(token) {
    if (!state.sessionId) return;
    const resp = await fetch('/api/entity/remove', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            session_id: state.sessionId,
            token: token
        })
    });
    const data = await resp.json();
    state.entities = data.entities;
    renderEntities();
}

function showResults() {
    goToStep(4);
    renderResultContent();
}

// ---------- PDF with the protected data really removed (the original is not stored: it is chosen again here) ----------
document.getElementById('exportPdfBtn').addEventListener('click', () => {
    if (!state.sessionId) return;
    if (!confirm("Scegli il PDF originale da censurare.\n\nIl programma non lo conserva: lo elabora in memoria, rimuove dal file " +
                 "tutti i dati protetti di questa pratica e lo scarta. Il PDF viene consegnato solo se, riletto, non contiene più nessun dato. " +
                 "I PDF che sono solo immagini (scansioni) non sono supportati.\n\nContinuare?")) return;
    document.getElementById('exportPdfInput').click();
});
document.getElementById('exportPdfInput').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    const asLabel = confirm("Come vuoi indicare i dati rimossi?\n\nOK = con l'etichetta del codice (es. [PERSONA_1])\nAnnulla = riquadro nero");
    const form = new FormData();
    form.append('session_id', state.sessionId);
    form.append('mode', asLabel ? 'etichetta' : 'nero');
    form.append('file', file);
    try {
        const resp = await fetch('/api/export/pdf', {method: 'POST', body: form});
        if (!resp.ok) {
            let detail = 'Esportazione non riuscita.';
            try { detail = (await resp.json()).detail || detail; } catch { /* not JSON */ }
            alert('PDF non consegnato: ' + detail);
            return;
        }
        const blob = await resp.blob();
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = file.name.replace(/\.pdf$/i, '') + '_censurato.pdf';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 10000);
        alert(`PDF censurato scaricato (${resp.headers.get('X-PrivateDoc-Removed') || '?'} occorrenze rimosse e verificate). Controllalo comunque a occhio.`);
    } catch (err) {
        alert('Errore durante l\'esportazione: ' + err.message);
    }
});

// ---------- Optional official Gemini API (off by default; the key is kept encrypted by the server) ----------
async function loadGeminiApi() {
    try {
        const st = await (await fetch('/api/gemini-api')).json();
        document.getElementById('provGeminiApi').style.display = st.enabled ? '' : 'none';
        if (!st.enabled && state.activeProvider === 'gemini_api') {
            document.querySelector('.prov-pill[data-provider="gemini"]').click();
        }
        document.getElementById('geminiApiModel').value = st.model || '';
        document.getElementById('geminiApiAck').checked = !!st.acknowledged;
        document.getElementById('geminiApiEnabled').checked = !!st.enabled;
        document.getElementById('geminiApiState').textContent = st.configured
            ? '✓ Una chiave è salvata (non viene mostrata).' : 'Nessuna chiave salvata.';
        return st;
    } catch { return null; }
}
async function postGeminiApi(body) {
    const resp = await fetch('/api/gemini-api', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (!resp.ok) { alert((await resp.json()).detail || 'Impostazione non salvata.'); return false; }
    return true;
}
document.getElementById('geminiApiOpenBtn').addEventListener('click', async () => {
    await loadGeminiApi();
    document.getElementById('geminiApiModal').style.display = 'flex';
});
document.getElementById('geminiApiClose').addEventListener('click', () => {
    document.getElementById('geminiApiKey').value = '';
    document.getElementById('geminiApiModal').style.display = 'none';
});
document.getElementById('geminiApiSave').addEventListener('click', async () => {
    const keyInput = document.getElementById('geminiApiKey');
    const body = {model: document.getElementById('geminiApiModel').value.trim(),
                  acknowledged: document.getElementById('geminiApiAck').checked};
    if (keyInput.value.trim()) body.key = keyInput.value.trim();
    if (!(await postGeminiApi(body))) return;
    keyInput.value = '';
    if (!(await postGeminiApi({enabled: document.getElementById('geminiApiEnabled').checked}))) {
        document.getElementById('geminiApiEnabled').checked = false;
    }
    await loadGeminiApi();
});
document.getElementById('geminiApiRemove').addEventListener('click', async () => {
    if (!confirm("Cancellare la chiave salvata e disattivare l'API di Gemini?")) return;
    if (await postGeminiApi({key: ''})) await loadGeminiApi();
});

function renderRestoreNotice(report) {
    const box = document.getElementById('restoreNotice');
    if (!box) return;
    const fuzzy = (report && report.fuzzy) || [];
    const unknown = (report && report.unknown) || [];
    const lines = [];
    if (fuzzy.length) {
        lines.push(`⚠ ${fuzzy.length} segnaposto scritti in modo alterato dal modello sono stati ripristinati lo stesso: ` +
            fuzzy.slice(0, 8).map(f => `«${f.found}» → ${f.token}`).join(', ') + '. Controlla che il senso sia giusto.');
    }
    if (unknown.length) {
        lines.push(`⚠ Segnaposto non riconosciuti, lasciati come sono: ${unknown.slice(0, 8).join(', ')}.`);
    }
    box.style.display = lines.length ? 'block' : 'none';
    box.textContent = lines.join(' ');
}

function renderResultContent() {
    if (!state.lastResult) return;
    renderRestoreNotice(state.lastResult.restore_report);
    if (state.currentViewMode === "decrypted") {
        resultOutput.textContent = state.lastResult.deanonymized_response;
    } else {
        resultOutput.textContent = state.lastResult.raw_masked_response;
    }
}

// Navigation flow
function goToStep(stepNum) {
    state.currentStep = stepNum;
    saveSessionLocally();
    navSteps.forEach(item => {
        const s = parseInt(item.getAttribute('data-step'));
        item.classList.toggle('active', s === stepNum);
    });

    document.getElementById('sectionUpload').classList.toggle('active', stepNum === 1);
    document.getElementById('sectionPrivacy').classList.toggle('active', stepNum === 2);
    document.getElementById('sectionAnalyze').classList.toggle('active', stepNum === 3);
    document.getElementById('sectionResult').classList.toggle('active', stepNum === 4);

    if (stepNum === 3) {
        renderDocSelector();
        refreshPreflight();
    }

    const titleMap = {
        1: { title: "1. Carica i Documenti da Analizzare", sub: "Supporta file singoli e archivi ZIP decompressi automaticamente" },
        2: { title: "2. Scudo Privacy & Pseudonimizzazione Coerente", sub: "Verifica e personalizza i dati sensibili prima di inoltrarli al modello" },
        3: { title: "3. Elaborazione & Confronto con LLM", sub: "Configura la richiesta e avvia l'analisi protetta tramite il tuo account" },
        4: { title: "4. Risultato Decifrato & Esportazione", sub: "Visualizza il report completo con i dati reali ripristinati in locale" }
    };
    document.getElementById('pageTitle').textContent = titleMap[stepNum].title;
    document.getElementById('pageSubtitle').textContent = titleMap[stepNum].sub;
}

// Google, OpenAI and Anthropic refuse automated browsers (and the program does not try to hide automation):
// for these the answer is copied and pasted by hand, in the user's own browser
const MANUAL_PROVIDERS = ['gemini', 'chatgpt', 'claude'];
const PROVIDER_URLS = {gemini: 'https://gemini.google.com', chatgpt: 'https://chatgpt.com', claude: 'https://claude.ai'};

function updateProviderUI(prov) {
    state.activeProvider = prov;
    const manualOnly = MANUAL_PROVIDERS.includes(prov);
    const name = getProviderDisplayName(prov);
    openLoginBtn.style.display = prov === 'gemini_api' ? 'none' : '';
    openLoginBtn.lastChild.textContent = ` Apri ${name.split(' (')[0]} nel browser`;
    runAnalysisBtn.lastChild.textContent = manualOnly ? ` Copia e apri ${name.split(' (')[0]}` : " Avvia Elaborazione Protetta";
    document.getElementById('copyOpenName').textContent = manualOnly ? name.split(' (')[0] : 'Gemini';
    activeProviderLabel.textContent = `${name} Bridge`;
    execProviderName.textContent = name;
    checkAuth();
}

function getProviderDisplayName(prov) {
    if (prov === 'gemini') return 'Google Gemini';
    if (prov === 'chatgpt') return 'ChatGPT (OpenAI)';
    if (prov === 'claude') return 'Claude (Anthropic)';
    if (prov === 'gemini_api') return 'Gemini (API ufficiale)';
    return prov;
}

async function checkAuth() {
    if (state.activeProvider === 'gemini_api') {
        authStatusText.textContent = "✓ API ufficiale di Gemini attiva (chiave salvata nell'archivio cifrato)";
        authStatusText.style.color = "var(--accent-emerald)";
        return;
    }
    authStatusText.textContent = "Verifica connessione in corso...";
    authStatusText.style.color = "var(--text-secondary)";
    const provider = state.activeProvider;
    try {
        const resp = await fetch(`/api/auth/status?provider=${provider}`);
        if (resp.status === 423) return;   // archive still locked: checked again right after unlocking
        const data = await resp.json();
        if (!resp.ok || !data.message) throw new Error('unexpected answer');
        if (provider !== state.activeProvider) return; // user switched provider meanwhile
        const styles = {
            connected: ["✓ ", "var(--accent-emerald)"],
            logged_out: ["✗ ", "var(--accent-rose)"],
            manual: ["📋 ", "var(--text-secondary)"],
            login_open: ["⏳ ", "var(--accent-amber)"],
            blocked: ["⚠ ", "var(--accent-amber)"],
            error: ["⚠ ", "var(--accent-amber)"]
        };
        const [icon, color] = styles[data.state] || ["", "var(--text-secondary)"];
        authStatusText.textContent = `${icon}${data.message}`;
        authStatusText.style.color = color;
    } catch {
        authStatusText.textContent = "⚠ Impossibile verificare la connessione";
        authStatusText.style.color = "var(--accent-amber)";
    }
}

function showLoading(title, msg) {
    loadingTitle.textContent = title;
    loadingMsg.textContent = msg;
    loadingOverlay.style.display = 'flex';
}

function hideLoading() {
    loadingOverlay.style.display = 'none';
    document.getElementById('loadingProgress').style.display = 'none';
}

async function refreshPreflight() {
    if (!state.sessionId) {
        preflightBox.className = 'preflight-box warn';
        preflightBox.innerHTML = 'Carica prima almeno un documento per attivare il controllo pre-invio.';
        preflightBox.style.display = 'block';
        return;
    }
    try {
        const resp = await fetch('/api/documents/preflight', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({session_id: state.sessionId, instruction: userInstructionInput.value || ''})
        });
        if (!resp.ok) throw new Error(`risposta ${resp.status}`);
        const pf = await resp.json();
        renderPreflight(pf);
    } catch (e) {
        console.error("Error refreshing preflight:", e);
        preflightBox.className = 'preflight-box warn';
        preflightBox.innerHTML = `⚠ Il controllo non è riuscito (${escapeHtml(e.message)}). Riprova; se si ripete, riapri la pratica.` +
            `<div style="margin-top:10px;"><button type="button" class="preflight-btn" data-action="RECHECK">↻ Ricontrolla</button></div>`;
        preflightBox.style.display = 'block';
    }
}

// Right-click on selected text in the prompt preview: mask it as a chosen category
let pendingMaskText = "";

// ---------- Category picker: the program's categories plus the user's own, with a fuzzy search ----------
const FALLBACK_CATEGORIES = {
    presets: [{id: 'PERSONA', label: 'Persona'}, {id: 'SOCIETA', label: 'Società / Ente'},
              {id: 'RISERVATO', label: 'Altro dato riservato'}],
    custom: [],
};
let categoryLibrary = FALLBACK_CATEGORIES;

async function loadCategories() {
    try {
        const resp = await fetch('/api/categories');
        if (resp.ok) categoryLibrary = await resp.json();
    } catch { /* keep the last known list */ }
    return categoryLibrary;
}

function plainText(text) {
    return (text || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
}

// Subsequence match ("prot" -> "Numero di protocollo"); higher is better, -1 means no match
function fuzzyScore(query, label) {
    const q = plainText(query).replace(/\s+/g, ''), t = plainText(label);
    if (!q) return 0;
    const at = t.indexOf(q);
    if (at >= 0) return 100 - at + (at === 0 || t[at - 1] === ' ' ? 20 : 0);
    let pos = 0, score = 0, last = -2;
    for (const ch of q) {
        const found = t.indexOf(ch, pos);
        if (found < 0) return -1;
        score += (found === last + 1 ? 5 : 1) + (found === 0 || t[found - 1] === ' ' ? 3 : 0);
        last = found;
        pos = found + 1;
    }
    return score;
}

// Fills `container` with a search box and the list; onPick(categoryId) runs when one is chosen
function buildCategoryPicker(container, onPick) {
    container.textContent = '';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'cat-search';
    input.placeholder = 'Cerca o crea una categoria…';
    const list = document.createElement('div');
    list.className = 'cat-list';
    container.append(input, list);
    let rows = [], active = 0;

    function entries() {
        const q = input.value.trim();
        const all = [...categoryLibrary.custom.map(c => ({...c, custom: true})), ...categoryLibrary.presets];
        const scored = all.map((c, i) => ({c, i, s: fuzzyScore(q, c.label)})).filter(x => x.s >= 0)
            .sort((a, b) => b.s - a.s || a.i - b.i).map(x => ({kind: 'pick', ...x.c}));
        const exact = all.some(c => plainText(c.label) === plainText(q));
        if (q && !exact) scored.push({kind: 'create', label: q});
        return scored;
    }
    function render() {
        rows = entries();
        active = Math.min(active, Math.max(rows.length - 1, 0));
        list.textContent = '';
        rows.forEach((row, i) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'cat-row' + (i === active ? ' active' : '');
            b.textContent = row.kind === 'create' ? `＋ Crea «${row.label}»` : (row.custom ? '★ ' : '') + row.label;
            b.addEventListener('mousedown', (e) => { e.preventDefault(); choose(row); });
            list.appendChild(b);
        });
    }
    async function choose(row) {
        if (!row) return;
        if (row.kind === 'create') {
            const resp = await fetch('/api/categories', {
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: row.label})
            });
            const data = await resp.json();
            if (!resp.ok) { alert(data.detail || 'Categoria non valida.'); return; }
            categoryLibrary = {presets: data.presets, custom: data.custom};
            onPick(data.id);
        } else {
            onPick(row.id);
        }
    }
    input.addEventListener('input', () => { active = 0; render(); });
    input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown') { active = Math.min(active + 1, rows.length - 1); render(); e.preventDefault(); }
        else if (e.key === 'ArrowUp') { active = Math.max(active - 1, 0); render(); e.preventDefault(); }
        else if (e.key === 'Enter') { choose(rows[active]); e.preventDefault(); }
    });
    input.addEventListener('click', (e) => e.stopPropagation());
    render();
    setTimeout(() => input.focus(), 0);
}

let pickerPopover = null;
function closeCategoryPopover() {
    if (pickerPopover) { pickerPopover.remove(); pickerPopover = null; }
}
// A floating picker under `anchor` (used for the doubtful words)
async function openCategoryPopover(anchor, onPick) {
    closeCategoryPopover();
    await loadCategories();
    const box = document.createElement('div');
    box.className = 'ctx-menu cat-popover';
    const rect = anchor.getBoundingClientRect();
    box.style.position = 'fixed';
    box.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 260))}px`;
    box.style.top = `${rect.bottom + 4}px`;
    box.addEventListener('click', (e) => e.stopPropagation());
    buildCategoryPicker(box, (id) => { closeCategoryPopover(); onPick(id); });
    document.body.appendChild(box);
    pickerPopover = box;
}
document.addEventListener('click', closeCategoryPopover);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeCategoryPopover(); });

function hideMaskMenu() {
    document.getElementById('maskContextMenu').style.display = 'none';
}

function setupMaskContextMenu() {
    const menu = document.getElementById('maskContextMenu');

    maskedPromptPreview.addEventListener('contextmenu', (e) => {
        const selection = window.getSelection();
        const text = selection ? selection.toString().trim() : "";
        if (!text || !maskedPromptPreview.contains(selection.anchorNode)) {
            hideMaskMenu();
            return; // no selection: leave the browser's own menu
        }
        e.preventDefault();
        pendingMaskText = text;
        const box = maskedPromptPreview.parentElement.getBoundingClientRect();
        menu.style.left = `${Math.max(0, e.clientX - box.left)}px`;
        menu.style.top = `${Math.max(0, e.clientY - box.top)}px`;
        menu.style.display = 'block';
        loadCategories().then(() => buildCategoryPicker(document.getElementById('maskPicker'), async (id) => {
            const term = pendingMaskText;
            hideMaskMenu();
            await maskSelectedText(term, id);
        }));
    });

    menu.addEventListener('click', (e) => e.stopPropagation());   // clicks inside the picker keep the menu open

    document.addEventListener('click', hideMaskMenu);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideMaskMenu(); });
    maskedPromptPreview.addEventListener('scroll', hideMaskMenu);
}

async function maskSelectedText(term, category) {
    if (!state.sessionId || term.length < 2) return;
    if (/\[[A-Z_]+_[A-Z0-9]+\]/.test(term)) {
        alert("La selezione contiene un dato già mascherato: seleziona solo il testo ancora in chiaro.");
        return;
    }
    try {
        const resp = await fetch('/api/documents/quick-protect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({session_id: state.sessionId, term: term, action: category})
        });
        const data = await resp.json();
        state.entities = data.entities;
        renderEntities();
        // Rebuild the preview so the user sees the result immediately
        const gen = await fetch('/api/prompt/generate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_id: state.sessionId,
                instruction: userInstructionInput.value || "Confronta i documenti"
            })
        });
        const prompt = await gen.json();
        maskedPromptPreview.textContent = prompt.prompt;
        renderPreflight(prompt.preflight);
    } catch (err) {
        alert("Errore nel mascherare il testo selezionato: " + err.message);
    }
}

function renderPreflight(pf) {
    if (!pf) {
        preflightBox.style.display = 'none';
        return;
    }
    const leaks = pf.leaks || [];
    const suspects = pf.suspects || [];
    let html = '';
    if (leaks.length > 0) {
        preflightBox.className = 'preflight-box block';
        html += `<div style="color:var(--accent-rose); font-weight:600; margin-bottom:8px;">⛔ Invio bloccato: dati sensibili ancora in chiaro</div>` +
            leaks.map(l => `
                <div class="preflight-row">
                    <span class="preflight-term">${escapeHtml(l.original)}</span>
                    <button type="button" class="preflight-btn" data-action="REMOVE" data-token="${escapeHtml(l.expected_token)}">Rimuovi protezione</button>
                </div>`).join("");
    }
    if (suspects.length > 0) {
        if (leaks.length === 0) preflightBox.className = 'preflight-box warn';
        html += `<div style="color:var(--accent-amber); font-weight:600; margin:${leaks.length ? '12px' : '0'} 0 6px 0;">⚠️ Termini sospetti (${suspects.length})</div>` +
            `<p style="margin:0 0 10px 0; font-size:0.85rem; color:var(--text-secondary);">Parole con iniziale maiuscola non riconosciute automaticamente. Scegli come gestirle:</p>` +
            suspects.map(w => `
                <div class="preflight-row">
                    <span class="preflight-term">${escapeHtml(w)}</span>
                    <div class="preflight-actions">
                        <button type="button" class="preflight-btn" data-action="SOCIETA" data-term="${escapeHtml(w)}">🏢 Società</button>
                        <button type="button" class="preflight-btn" data-action="PERSONA" data-term="${escapeHtml(w)}">👤 Persona</button>
                        <button type="button" class="preflight-btn" data-action="OTHER" data-term="${escapeHtml(w)}">… Altra categoria</button>
                        <button type="button" class="preflight-btn" data-action="IGNORE" data-term="${escapeHtml(w)}">✓ Termine comune</button>
                    </div>
                </div>`).join("");
    }
    if (leaks.length === 0 && suspects.length === 0) {
        preflightBox.className = 'preflight-box ok';
        html = `<div style="color:var(--accent-emerald); font-weight:600;">✅ Controllo superato</div>` +
               `<p style="margin:4px 0 0 0; font-size:0.85rem; color:var(--text-secondary);">Nessun dato sensibile rilevato in chiaro nel testo che verrà inviato.</p>`;
    }
    html += `<div style="margin-top:10px; display:flex; align-items:center; gap:12px;"><button type="button" class="preflight-btn" data-action="RECHECK">↻ Ricontrolla</button>` +
            `<span style="font-size:0.78rem; color:var(--text-muted);">Ultimo controllo: ${new Date().toLocaleTimeString('it-IT')}</span></div>`;
    preflightBox.innerHTML = html;
    preflightBox.style.display = 'block';
}

// One delegated listener: buttons are re-created on every render
preflightBox.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    if (btn.dataset.action === 'OTHER') {
        e.stopPropagation();
        openCategoryPopover(btn, (id) => handlePreflightAction(id, btn.dataset.term));
        return;
    }
    handlePreflightAction(btn.dataset.action, btn.dataset.term, btn.dataset.token);
});

async function handlePreflightAction(action, term, token) {
    if (action === 'RECHECK') {
        const btn = preflightBox.querySelector('button[data-action="RECHECK"]');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ Controllo in corso…'; }
        await refreshPreflight();
        return;
    }
    if (!state.sessionId) return;
    try {
        const isRemove = action === 'REMOVE';
        const resp = await fetch(isRemove ? '/api/entity/remove' : '/api/documents/quick-protect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(isRemove
                ? {session_id: state.sessionId, token: token}
                : {session_id: state.sessionId, term: term, action: action})
        });
        const data = await resp.json();
        state.entities = data.entities;
        renderEntities();
        // Recompute with the user's current instruction, not an empty one
        await refreshPreflight();
    } catch (err) {
        alert("Errore nell'azione sul termine: " + err.message);
    }
}

// Remember the session so a page reload does not lose the work
function saveSessionLocally() {
    try {
        localStorage.setItem('privatedoc_session', JSON.stringify({id: state.sessionId, step: state.currentStep}));
    } catch { /* storage unavailable */ }
}

async function restoreSession() {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem('privatedoc_session') || 'null'); } catch { /* ignore */ }
    if (!saved || !saved.id) return;
    try {
        const ok = await openCase(saved.id, Math.min(saved.step || 1, 3));
        if (!ok) localStorage.removeItem('privatedoc_session');
    } catch (e) {
        console.error("Impossibile ripristinare la sessione:", e);
    }
}

function escapeHtml(text) {
    if (!text) return "";
    return text.toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
