# Analisi anti-rollback del vault

**Stato:** threat model e opzioni progettuali; nessuna modifica al prodotto.  
**Ambito:** vault locale Windows di PrivateDoc AI (`vault.json` e `pratiche/*.enc`).

## Esito in breve

AES-256-GCM protegge autenticità e integrità del contenuto, ma una copia vecchia e
autentica resta crittograficamente valida. Per rilevare un rollback serve quindi
uno stato di freschezza esterno all'insieme ripristinabile.

La scelta proporzionata per il prodotto attuale è, se il rischio lo giustifica,
un'**ancora locale DPAPI per utente, fuori dalla cartella `data/`, usata solo per
rilevare e avvisare**. Non deve mai diventare necessaria per derivare la chiave o
decifrare le pratiche. Questa opzione rileva bene ripristini accidentali della sola
cartella dati, ma **non** un ripristino congiunto di dati e ancora, né un attaccante
locale intenzionale che abbia conservato entrambe le versioni.

TPM e servizio remoto aumentano la copertura, ma hanno costi UX e operativi non
giustificati oggi. In particolare, una chiave TPM non esportabile da sola firma le
versioni ma non rende una vecchia versione meno valida: per impedire il replay
servirebbe anche uno stato monotono non ripristinabile.

## Stato attuale e proprietà già garantite

Il formato v2 usa:

- scrypt per derivare la chiave dalla password;
- AES-256-GCM con nonce casuale;
- AAD contenente l'identificativo della pratica;
- identificativo interno cifrato, confrontato con il nome del file;
- scrittura atomica con `fsync` e `os.replace`.

Queste proprietà rilevano password errate, bit modificati, file corrotti e copia di
una pratica sul nome di un'altra. Non rilevano la sostituzione di una pratica con
una sua versione precedente autentica. Anche `vault.json` può essere ripristinato
insieme alle pratiche: la password continua a funzionare e non esiste oggi un punto
di confronto più recente.

## Threat model

### Beni da proteggere

1. **Integrità temporale:** sapere se una pratica aperta è almeno recente quanto
   l'ultima versione osservata dall'installazione.
2. **Disponibilità:** un guasto, un cambio PC o un ripristino legittimo non deve
   rendere definitivamente illeggibili pratiche di cui l'utente conosce la password.
3. **Confidenzialità:** non indebolire la cifratura esistente e non introdurre copie
   in chiaro nell'ancora o nei log.
4. **Comprensibilità:** distinguere “file alterato”, “versione precedente” e
   “ancora non disponibile” con azioni recuperabili.

### Avversari ed eventi considerati

| Scenario | Obiettivo realistico | Copertura richiesta |
|---|---|---|
| Backup ripristina solo `data/` | Rilevare pratica o vault più vecchi | Sì |
| Utente copia per errore un vecchio `.enc` | Rilevare e offrire recupero | Sì |
| Ripristino congiunto di `data/` e ancora software | Evitare promesse false | Limite dichiarato |
| Ripristino immagine completa del sistema | Evitare promesse false | Limite di DPAPI |
| Altro utente standard modifica i file | Rilevare modifica o rollback non coordinato | Parziale |
| Amministratore locale o malware con pari privilegi | Proteggere i dati a riposo quando il vault è chiuso | AES/scrypt; anti-rollback non garantito |
| Admin modifica eseguibile o memoria mentre il vault è aperto | Nessuna garanzia credibile solo lato client | Fuori dal confine di fiducia |
| Disco guasto, reinstallazione, nuovo PC, TPM azzerato | Non perdere accesso ai dati cifrati | Obbligatorio |

L'amministratore locale non è un confine di sicurezza difendibile dall'applicazione:
può sostituire programma e controlli o leggere il processo quando il vault è aperto.
L'anti-rollback locale serve soprattutto contro errori operativi e attacchi offline
non coordinati, non contro il proprietario completo della macchina.

## Dati minimi dell'ancora

Una futura ancora non deve contenere PII. È sufficiente un record autenticato con:

```text
schema_version
vault_id casuale
per ogni case_id: revisione massima, SHA-256 del ciphertext, stato active/deleted
revision_counter globale (diagnostico, non assunto come hardware-monotono)
```

Il payload cifrato della pratica deve contenere lo stesso `vault_id`, `case_id` e
numero di revisione. Il digest riguarda il blob cifrato, non il testo in chiaro.
Le cancellazioni richiedono tombstone nell'ancora, altrimenti un backup potrebbe
far riapparire silenziosamente una pratica eliminata.

### Ordine di aggiornamento e crash

1. Scrivere atomicamente la nuova pratica cifrata con revisione `n+1`.
2. Aggiornare atomicamente l'ancora con revisione e digest appena scritti.
3. Se un crash avviene fra 1 e 2, la pratica risulta **più avanti** dell'ancora:
   dopo decifratura valida si può avanzare l'ancora, registrando l'evento.
4. Se la pratica risulta **più indietro** dell'ancora o ha stesso numero ma digest
   diverso, segnalarla come rollback/conflitto e non sovrascrivere nulla.

Aggiornare prima l'ancora creerebbe falsi rollback dopo un crash e va evitato.

## Opzioni

### A. Ancora DPAPI per utente fuori da `data/` — raccomandata come pilot

**Disegno.** Salvare l'ancora sotto `%LOCALAPPDATA%/PrivateDocAI/`, protetta con
DPAPI `CurrentUser`, ed escluderla dal backup ordinario delle pratiche. DPAPI lega
normalmente la decifratura alle credenziali dell'utente e alla macchina e aggiunge
un controllo di integrità. L'ancora non contiene la password né la chiave AES.

**Protegge da:** ripristino della sola cartella `data/`, vecchio `.enc` copiato a
mano, cancellazione e successiva riapparizione se il tombstone è ancora presente.

**Non protegge da:** snapshot/ripristino coordinato di dati e blob DPAPI; immagine
completa del profilo/sistema; amministratore che modifica o aggira l'app; perdita
o sostituzione della macchina.

**Costo UX:** basso nell'uso normale, medio durante migrazione o disaster recovery.
L'assenza dell'ancora è ambigua: nuova installazione e cancellazione ostile sono
indistinguibili. Va mostrata come “freschezza non verificabile”, non “file corrotto”.

**Rischio lockout:** basso soltanto se l'ancora è un sensore e non parte della
decifratura. Raccomandazione operativa:

- consentire apertura in sola lettura dopo password corretta;
- offrire “Importa come copia storica” oppure “Accetta come nuova linea temporale”;
- richiedere conferma esplicita e conservare la versione conflittuale;
- non cancellare né riscrivere automaticamente un file sospetto;
- al primo aggiornamento di un vault esistente, dichiarare che la protezione vale
  “da questo momento”, senza pretendere di validare il passato.

### B. Stato monotono TPM — più forte, non raccomandato ora

Una chiave non esportabile nel TPM può firmare l'ancora senza esporre la chiave
privata. Tuttavia una vecchia ancora conserva una firma valida: la freschezza
richiede un contatore/stato TPM monotono o un protocollo equivalente, non la sola
firma. Provisioning, ACL, disponibilità delle API e politiche aziendali rendono la
soluzione fragile per un'app desktop senza amministrazione centralizzata.

**Protegge da:** rollback del disco mentre lo stato monotono del TPM sopravvive;
estrazione della chiave privata software.

**Non protegge da:** modifica dell'app mentre gira con privilegi dell'utente;
amministratore che disabilita o azzera il TPM (può almeno causare DoS); perdita o
sostituzione della scheda madre.

**Costo UX:** alto. Clear TPM, guasto hardware, reimaging o cambio PC possono
invalidare le chiavi TPM. Microsoft avverte che il clear elimina le chiavi create
nel TPM e può causare perdita dei dati protetti soltanto da esse. Per questo il TPM
non deve mai essere l'unico modo di decifrare il vault: al massimo rafforza il
segnale di freschezza, con recovery code/export dell'ancora e flusso amministrato.

### C. Ancora remota append-only — copertura migliore, fuori dal prodotto base

Registrare per `vault_id` l'ultima revisione/digest su un servizio autenticato o su
un log aziendale append-only rende il confronto indipendente dai backup locali.

**Protegge da:** rollback congiunto di tutti i file locali e clonazione su altro PC,
finché account e servizio remoto non sono compromessi.

**Costo UX e privacy:** rete, account, disponibilità del servizio, gestione tenant,
metadati e supporto. Contrasta i pilastri offline e zero-friction. Ha senso solo
come opzione enterprise esplicita, mai come requisito del prodotto locale.

## Matrice decisionale

| Opzione | Ripristino solo `data/` | Ripristino congiunto locale | Admin locale | Migrazione | Costo |
|---|---:|---:|---:|---:|---:|
| Nessuna ancora | No | No | No | Ottima | Nessuno |
| DPAPI fuori backup | Sì | No | No | Recovery manuale | Basso/medio |
| TPM + stato monotono | Sì | Sì, se solo disco | No; DoS possibile | Difficile | Alto |
| Servizio append-only | Sì | Sì | Parziale | Buona con account | Alto/continuo |

## Raccomandazione e gate prima di implementare

1. **Decidere il rischio da coprire.** Se è il ripristino accidentale o parziale,
   prototipare A. Se si richiede resistenza a un admin locale, nessuna delle opzioni
   client-only soddisfa il requisito e la promessa va rifiutata.
2. **Mantenere separati accesso e freschezza.** Password + AES restano l'unico
   requisito per decifrare; l'ancora decide solo stato e avvisi.
3. **Definire prima il recovery.** Apri sola lettura, importa copia, accetta nuova
   linea temporale; mai cancellazione automatica o lockout permanente.
4. **Testare almeno:** rollback di un caso, rollback di tutto `data/`, ripristino
   congiunto, file più avanti dell'ancora dopo crash, tombstone, ancora assente o
   corrotta, cambio account/PC, concorrenza fra salvataggi e backup.
5. **Misurare falsi allarmi** con i software di backup realmente usati. Un controllo
   di freschezza che induce ad accettare sempre gli avvisi non aggiunge sicurezza.

## Fonti primarie

- Microsoft, [CryptProtectData](https://learn.microsoft.com/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata): ambito utente/macchina e MAC di integrità DPAPI.
- Microsoft, [How Windows uses the TPM](https://learn.microsoft.com/windows/security/hardware-security/tpm/how-windows-uses-the-tpm): chiavi TPM non esportabili e limiti delle protezioni software.
- Microsoft, [Troubleshoot the TPM](https://learn.microsoft.com/windows/security/information-protection/tpm/initialize-and-configure-ownership-of-the-tpm): effetti distruttivi del clear TPM e requisiti di recovery.
- Microsoft, [BitLocker countermeasures](https://learn.microsoft.com/windows/security/operating-system-security/data-protection/bitlocker/countermeasures): esempio di binding TPM a misure di boot e relativo confine di sicurezza.
