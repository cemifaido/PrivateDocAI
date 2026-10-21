import re
import uuid
from typing import Dict, List, Any, Optional

class DeterministicAnonymizer:
    """
    Deterministic Pseudonymization and Re-identification Engine.
    Conforms to EDPB Guidelines 01/2025 on Pseudonymisation:
    - Maintains the separation of pseudonymisation domains (keys/mapping stored only in private local domain).
    - Preserves relational consistency across multiple documents (same entity = same pseudonym).
    - Performs pre-flight verification against unmasked residue (singling out / linkability prevention).
    - Supports bilingual documents (Italian & English) and cross-lingual legal translations.
    """

    STOPWORDS = {
        # Italiano - Città & Mesi
        'italia', 'roma', 'milano', 'torino', 'napoli', 'bologna', 'firenze',
        'gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
        'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre',
        'lunedi', 'martedi', 'mercoledi', 'giovedi', 'venerdi', 'sabato', 'domenica',
        # Italiano - Termini contrattuali e comuni
        'contratto', 'accordo', 'fornitura', 'servizi', 'foglio', 'tabella', 'riepilogo',
        'cliente', 'fornitore', 'societa', 'azienda', 'oggetto', 'allegato',
        'corpo', 'messaggio', 'mittente', 'destinatario', 'segreteria', 'ufficio',
        'importo', 'totale', 'prezzo', 'costo', 'data', 'scadenza', 'firma', 'luogo',
        'legge', 'articolo', 'decreto', 'clausola', 'descrizione', 'note', 'stato',
        'pagina', 'tribunale', 'civile', 'penale', 'vostro', 'onore', 'scansionata',
        'uno', 'due', 'tre', 'gentili', 'cordiali', 'saluti', 'sintesi', 'documento',
        'documenti', 'pagamento', 'fattura', 'bonifico', 'termini', 'condizioni',
        'poi', 'ora', 'quindi', 'inoltre', 'infine', 'pertanto', 'dunque', 'tuttavia',
        'mentre', 'dopo', 'prima', 'anche', 'questo', 'questa', 'secondo', 'come',
        'dott', 'dottssa', 'sig', 'sigra', 'ing', 'avv', 'arch', 'rag', 'geom',
        # Italiano - Termini processuali e forensi
        'giudice', 'magistrato', 'presidente', 'relatore', 'sezione', 'collegio',
        'cancelleria', 'udienza', 'ordinanza', 'sentenza', 'ricorso', 'controricorso',
        'comparsa', 'costituzione', 'risposta', 'memoria', 'replica', 'atto', 'citazione',
        'notifica', 'notificazione', 'precetto', 'pignoramento', 'istanza', 'opposizione',
        'giudizio', 'causa', 'ruolo', 'generale', 'fascicolo', 'doc', 'docc',
        'verbale', 'domanda', 'eccezione', 'conclusioni', 'preliminare', 'preliminarmente',
        'rito', 'merito', 'onere', 'prova', 'testimone', 'testi', 'ctu', 'ctp',
        'perito', 'consulente', 'relazione', 'perizia', 'attrice', 'convenuta',
        'terzo', 'chiamato', 'appellante', 'appellata', 'ricorrente', 'resistente',
        'compagnia', 'assicurazione', 'assicurazioni', 'impresa', 'società', 'avvocato',
        'ordinario', 'specializzata', 'materia', 'sezione',

        # English - Common & Legal vocabulary
        'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
        'september', 'october', 'november', 'december', 'monday', 'tuesday',
        'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
        'agreement', 'contract', 'section', 'clause', 'article', 'pursuant',
        'exhibit', 'schedule', 'annex', 'appendix', 'whereas', 'therefore',
        'hereby', 'hereof', 'herein', 'hereunder', 'thereunder', 'thereof',
        'plaintiff', 'defendant', 'appellant', 'appellee', 'claimant', 'respondent',
        'court', 'judge', 'justice', 'magistrate', 'counsel', 'attorney', 'solicitor', 'barrister',
        'jurisdiction', 'governing', 'liability', 'damages', 'indemnification',
        'warranty', 'warranties', 'breach', 'termination', 'assignment', 'notice',
        'counterpart', 'execution', 'recital', 'recitals', 'provision', 'provisions',
        'terms', 'conditions', 'definition', 'definitions', 'party', 'parties',
        'witness', 'witnesseth', 'hearing', 'trial', 'motion', 'order', 'brief',
        'complaint', 'answer', 'claim', 'counterclaim', 'discovery', 'subpoena',
        'evidence', 'summary', 'judgment', 'memorandum', 'opinion', 'appeal',
        'confidential', 'confidentiality', 'disclosure', 'intellectual', 'property',
        'effective', 'expiration', 'deliverable', 'services', 'invoice', 'payment'
    }

    # Single name word: Rossi, O'Neil, D'Angelo, Rossi-Bianchi, Smith-Jones
    _NAME_WORD = r"[A-Z](?:['’][A-Z])?[a-zàèéìòù]{2,}(?:-[A-Z][a-zàèéìòù]{2,})?"
    _PARTICLE = r"(?i:de|di|del|della|delle|dei|degli|da|dal|dalla|lo|la|le|van|von|mc|mac|d['’])"
    _SURNAME_MIN_LEN = 4

    # Corporate suffix pattern (Italian + English + International, case-insensitive)
    _CORP_SUFFIX = (
        r'(?i:'
        # Italian forms
        r's\.?r\.?l\.?s?|'                       # srl, s.r.l., srls, s.r.l.s.
        r's\.?p\.?a\.?|'                         # spa, s.p.a.
        r's\.?a\.?s\.?|'                         # sas, s.a.s.
        r's\.?n\.?c\.?|'                         # snc, s.n.c.
        r's\.?a\.?p\.?a\.?|'                     # sapa, s.a.p.a.
        r's\.?s\.?|'                             # ss, s.s. (società semplice)
        r's\.?e\.?|'                             # se, s.e. (Societas Europaea)
        r's\.?c\.?a?\.?r\.?l\.?|'                # scarl, scrl, s.c.a.r.l.
        r's\.?t\.?p\.?|'                         # stp, s.t.p. (società tra professionisti)
        r'soc(?:iet[àa])?\.?\s*coop(?:\.|\b)(?:\s*(?:a\s*r\.?l\.?|a\s+responsabilit[àa]\s+limitata))?|'
        r'societ[àa]\s+(?:a\s+responsabilit[àa]\s+limitata(?:\s+semplificata)?|per\s+azioni|in\s+accomandita(?:\s+per\s+azioni|\s+semplice)?|in\s+nome\s+collettivo|semplice|benefit)|'
        r'societ[àa]\s+benefit|'
        r'studio\s+legale|studio\s+associato|studi\s+associati|studio\s+tributario|studio\s+professionale|'
        r'associazione\s+professionale|'
        # English & International forms
        r'ltd\.?|limited|'
        r'l\.?l\.?c\.?|llc|'
        r'l\.?l\.?p\.?|llp|'
        r'l\.?p\.?|lp|'
        r'inc\.?|incorporated|'
        r'corp\.?|corporation|'
        r'p\.?l\.?c\.?|plc|public\s+limited\s+company|'
        r'co\.?|company|'
        r'law\s+firm|attorneys\s+at\s+law|law\s+offices?|'
        r'gmbh|ag|sa|s\.?a\.?|b\.?v\.?|n\.?v\.?|s\.?l\.?'
        r')'
    )

    _STRIP_CORP_SUFFIX = re.compile(
        r'(?i:\s+(?:s\.?r\.?l\.?s?|s\.?p\.?a\.?|s\.?a\.?s\.?|s\.?n\.?c\.?|s\.?a\.?p\.?a\.?|s\.?s\.?|s\.?e\.?|s\.?c\.?a?\.?r\.?l\.?|s\.?t\.?p\.?|soc(?:iet[àa])?\.?\s*coop(?:\.|\b)(?:\s*(?:a\s*r\.?l\.?|a\s+responsabilit[àa]\s+limitata))?|societ[àa]\s+(?:a\s+responsabilit[àa]\s+limitata(?:\s+semplificata)?|per\s+azioni|in\s+accomandita(?:\s+per\s+azioni|\s+semplice)?|in\s+nome\s+collettivo|semplice|benefit)|societ[àa]\s+benefit|studio\s+legale|studio\s+associato|ltd\.?|limited|l\.?l\.?c\.?|llc|l\.?l\.?p\.?|llp|inc\.?|incorporated|corp\.?|corporation|plc|p\.?l\.?c\.?|co\.?|company|law\s+firm|gmbh|ag|sa|b\.?v\.?|n\.?v\.?|s\.?l\.?))+$',
        re.IGNORECASE
    )

    def __init__(self):
        self.session_id = str(uuid.uuid4())
        # Maps canonical text -> token (e.g. "mario rossi" -> "[PERSONA_1]")
        self.forward_map: Dict[str, str] = {}
        # Maps token -> canonical original display text (e.g. "[PERSONA_1]" -> "Mario Rossi")
        self.reverse_map: Dict[str, str] = {}
        # Detailed registry of entities found
        self.registry: List[Dict[str, Any]] = []
        # Counters for tokens
        self.counters = {
            "PERSONA": 1,
            "SOCIETA": 1,
            "CODICE_FISCALE": 1,
            "PARTITA_IVA": 1,
            "IBAN": 1,
            "EMAIL": 1,
            "TELEFONO": 1,
            "CARTA_PAGAMENTO": 1,
            "TARGA": 1,
            "IMPORTO": 1,
            "DATA": 1,
            "INDIRIZZO": 1
        }
        # Whitelist / ignore list
        self.whitelist = set()
        # Upload operation that is currently registering entities (to undo it if interrupted)
        self.current_operation: Optional[str] = None
        # Aliases in forward_map pointing to an entity token
        self._aliases = set()
        # Surnames shared by different people: not masked alone, flagged by the pre-flight
        self._ambiguous_surnames = set()

    def _letter_label(self, num: int) -> str:
        """Converts 1 -> A, 2 -> B, ..., 26 -> Z, 27 -> AA"""
        result = ""
        while num > 0:
            num -= 1
            result = chr(65 + (num % 26)) + result
            num //= 26
        return result

    def get_or_create_token(self, original_text: str, category: str) -> str:
        # Normalize internal whitespace (including non-breaking spaces \xa0) to single space
        canonical_key = " ".join(original_text.strip().rstrip('.,;:').lower().split())

        if canonical_key in self.forward_map:
            return self.forward_map[canonical_key]

        c_num = self.counters.get(category, 1)
        if category in ("SOCIETA", "DATA"):
            token_label = self._letter_label(c_num)
        else:
            token_label = str(c_num)

        token = f"[{category}_{token_label}]"
        self.counters[category] = c_num + 1

        self.forward_map[canonical_key] = token
        self.reverse_map[token] = original_text.strip()

        self.registry.append({
            "original": original_text.strip(),
            "canonical": canonical_key,
            "category": category,
            "token": token,
            "user_modified": False,
            "operation_id": self.current_operation
        })

        return token

    def analyze_documents(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        combined_candidates = []

        for doc_idx, doc in enumerate(documents):
            text = doc.get("text", "")
            doc_name = doc.get("filename", f"Doc_{doc_idx}")
            found = self._detect_entities(text)
            for item in found:
                item["doc_name"] = doc_name
                combined_candidates.append(item)

        # Prioritize non-PERSONA candidates first (SOCIETA, IBAN, CF, IMPORTO, DATA, etc.)
        # so company aliases are claimed before bare person name heuristics match them.
        def sort_key(x):
            is_person = 1 if x["category"] == "PERSONA" else 0
            return (is_person, -len(x["raw"]))

        combined_candidates.sort(key=sort_key)

        for item in combined_candidates:
            raw = item["raw"]
            cat = item["category"]
            canon = raw.lower().rstrip('.,;:')
            if canon in self.whitelist:
                continue
            if canon in self.forward_map:
                continue

            token = self.get_or_create_token(raw, cat)

            # Check if this company entity has an immediate legal alias in any document
            if cat == "SOCIETA":
                for doc in documents:
                    doc_text = doc.get("text", "")
                    aliases = self._extract_legal_aliases_from_text(raw, doc_text)
                    for alias in aliases:
                        canon_alias = alias.lower().rstrip('.,;:')
                        if canon_alias not in self.forward_map and canon_alias not in self.STOPWORDS:
                            self.forward_map[canon_alias] = token
                            self._aliases.add(canon_alias)

        self._rebuild_aliases()
        return self.get_registry()

    def _extract_legal_aliases_from_text(self, company_name: str, text: str) -> List[str]:
        """
        Extracts defined aliases in legal acts and contracts (IT + EN):
        e.g. Alfaservizi s.r.l. (d’ora in avanti, “Alfaservizi” o “Attrice”)
        e.g. Acme Corp. (hereinafter referred to as "Acme" or "Borrower")
        e.g. Betamedia s.r.l. ("Betamedia")
        """
        aliases = []
        if not text:
            return aliases
        escaped_name = re.escape(company_name)
        # Italian & English defined alias patterns (swallowing optional trailing dot before parens)
        alias_regex = (
            rf'{escaped_name}\.?\s*\([^)]*?(?:'
            rf'd[’\']ora\s+in\s+avanti|di\s+seguito|in\s+prosieguo|anche\s+solo|'
            rf'hereinafter(?:\s+referred\s+to\s+as)?|hereinafter\s+called'
            rf')?[,\s]*[“"«]([^”"»]+)[”"»]'
        )
        for m in re.finditer(alias_regex, text, re.IGNORECASE):
            cand = m.group(1).strip()
            # Ignore generic legal role terms (IT + EN)
            generic_roles = {
                "attrice", "convenuta", "societa", "società", "compagnia", "terzo chiamato",
                "parte", "ricorrente", "resistente", "company", "client", "borrower", "lender",
                "seller", "buyer", "contractor", "subcontractor", "employer", "employee",
                "licensor", "licensee", "plaintiff", "defendant"
            }
            if cand.lower() not in generic_roles and len(cand) >= 3:
                aliases.append(cand)
        return aliases

    def _rebuild_aliases(self):
        """
        1. Lets a surname appearing alone ("Rossi" / "Smith") reuse the token of the full name
           ("Mario Rossi" / "John Smith").
        2. Lets a company base brand appearing alone ("Alfaservizi", "Betamedia", "Epsilon", "Acme")
           reuse the token of the full corporate name ("Alfaservizi s.r.l. società benefit").
        """
        for key in list(self._aliases):
            self.forward_map.pop(key, None)
        self._aliases = set()
        self._ambiguous_surnames = set()

        # Person surnames
        by_surname: Dict[str, set] = {}
        for r in self.registry:
            if r["category"] != "PERSONA":
                continue
            parts = r["canonical"].split(" ", 1)
            if len(parts) == 2 and len(parts[1]) >= self._SURNAME_MIN_LEN:
                by_surname.setdefault(parts[1], set()).add(r["token"])

        for surname, tokens in by_surname.items():
            if len(tokens) == 1 and surname not in self.forward_map and surname not in self.STOPWORDS:
                self.forward_map[surname] = next(iter(tokens))
                self._aliases.add(surname)
            elif len(tokens) > 1:
                self._ambiguous_surnames.add(surname)

        # Company base brands & aliases
        by_corp_alias: Dict[str, set] = {}
        for r in self.registry:
            if r["category"] != "SOCIETA":
                continue
            canonical = r["canonical"]
            cleaned = self._STRIP_CORP_SUFFIX.sub("", canonical).strip()
            candidates = []
            if cleaned and cleaned != canonical and len(cleaned) >= 3:
                candidates.append(cleaned)
                parts = cleaned.split()
                if len(parts) > 1 and len(parts[0]) >= 3 and parts[0] not in {'studio', 'societa', 'società', 'banca', 'gruppo', 'fondazione', 'the'}:
                    candidates.append(parts[0])
            for cand in candidates:
                if cand not in self.STOPWORDS:
                    by_corp_alias.setdefault(cand, set()).add(r["token"])

        for alias, tokens in by_corp_alias.items():
            if len(tokens) == 1 and alias not in self.forward_map and alias not in self.STOPWORDS:
                self.forward_map[alias] = next(iter(tokens))
                self._aliases.add(alias)

    def _build_mask_pattern(self):
        """One combined regex, longest entity first, so the text is scanned once."""
        alternatives = []
        for key in sorted(self.forward_map, key=len, reverse=True):
            body = r"\s+".join(re.escape(part) for part in key.split())
            if key[-1].isalnum():
                dot = r"\.?" if key[-1].isalpha() and "." in key else ""
                tail = rf"{dot}(?![\w\]])"
            else:
                tail = r"(?=[\s|:,.;)]|$)(?!\])"
            alternatives.append(body + tail)
        if not alternatives:
            return None
        return re.compile(r"(?<![\w\[])(?:" + "|".join(alternatives) + ")", re.IGNORECASE)

    def mask_text(self, text: str) -> str:
        """Replaces all detected entities (and surname/brand aliases) with their tokens."""
        pattern = self._build_mask_pattern()
        if pattern is None:
            return text

        def to_token(m):
            found = " ".join(m.group(0).lower().split())
            return self.forward_map.get(found) or self.forward_map.get(found.rstrip(".,;:"), m.group(0))

        return pattern.sub(to_token, text)

    def de_anonymize_text(self, masked_text: str) -> str:
        """
        Restores real entity values into the LLM generated output.
        Replaces longest tokens first to avoid substring collisions.
        """
        restored = masked_text
        sorted_tokens = sorted(self.reverse_map.items(), key=lambda kv: len(kv[0]), reverse=True)

        for token, original_val in sorted_tokens:
            restored = restored.replace(token, original_val)

            # Also catch if LLM replaced underscore with space: [PERSONA 1]
            spaced_token = token.replace("_", " ")
            if spaced_token in restored:
                restored = restored.replace(spaced_token, original_val)

        return restored

    def verify_masking_coverage(self, masked_text: str) -> List[Dict[str, Any]]:
        """
        Pre-flight check: any registered entity still readable in the masked text.
        It cannot see entities the detector never found: see find_unmasked_suspects.
        """
        leaks = []
        for canonical_val, token in self.forward_map.items():
            if len(canonical_val) < 3:
                continue
            flex_body = r"\s+".join(re.escape(p) for p in canonical_val.split())
            if re.search(rf'(?<![\w\[]){flex_body}(?![\w\]])', masked_text, re.IGNORECASE):
                leaks.append({
                    "value": canonical_val,
                    "expected_token": token,
                    "original": self.reverse_map.get(token, canonical_val)
                })
        return leaks

    def find_unmasked_suspects(self, masked_text: str) -> List[str]:
        """
        Capitalized words in the middle of a sentence that survived masking and are
        not common document vocabulary: possible names the detector missed.
        """
        without_tokens = re.sub(r'\[[A-Z_]+_[A-Z0-9]+\]', ' ', masked_text)
        suspects = []
        pattern = r'(?<=[a-zàèéìòù,;(]\s)([A-Z][A-Za-z0-9àèéìòù\'\-]{2,})\b'
        for m in re.finditer(pattern, without_tokens):
            word = m.group(1)
            if (word.lower() not in self.STOPWORDS
                    and word.lower() not in self.whitelist
                    and word not in suspects):
                suspects.append(word)
        for surname in sorted(self._ambiguous_surnames):
            if surname not in (w.lower() for w in suspects) and re.search(
                    rf'(?<![\w\[]){re.escape(surname)}(?![\w\]])', without_tokens, re.IGNORECASE):
                suspects.append(surname.title())
        return suspects

    def _drop_keys_for_token(self, token: str):
        for key in [k for k, v in self.forward_map.items() if v == token]:
            del self.forward_map[key]
            self._aliases.discard(key)

    def update_entity(self, token: str, new_original: str):
        if token in self.reverse_map:
            self._drop_keys_for_token(token)
            new_canonical = " ".join(new_original.strip().rstrip('.,;:').lower().split())
            self.forward_map[new_canonical] = token
            self.reverse_map[token] = new_original.strip()
            for r in self.registry:
                if r["token"] == token:
                    r["original"] = new_original.strip()
                    r["canonical"] = new_canonical
                    r["user_modified"] = True
            self._rebuild_aliases()

    def remove_entity(self, token: str):
        if token in self.reverse_map:
            canonical = " ".join(self.reverse_map[token].strip().rstrip('.,;:').lower().split())
            self.whitelist.add(canonical)
            self._drop_keys_for_token(token)
            del self.reverse_map[token]
            self.registry = [r for r in self.registry if r["token"] != token]
            self._rebuild_aliases()

    def add_custom_entity(self, text: str, category: str) -> str:
        token = self.get_or_create_token(text, category)
        for r in self.registry:
            if r["token"] == token:
                r["manual"] = True  # chosen by the user: never garbage-collected
        self._rebuild_aliases()
        return token

    def _forget_token(self, token: str):
        self._drop_keys_for_token(token)
        self.reverse_map.pop(token, None)
        self.registry = [r for r in self.registry if r["token"] != token]

    def _is_automatic(self, entry: Dict[str, Any]) -> bool:
        return not entry.get("manual") and not entry.get("user_modified")

    def remove_by_operation(self, operation_id: str) -> int:
        """Forgets the automatic entities found by one (interrupted) upload operation."""
        doomed = [r["token"] for r in self.registry
                  if r.get("operation_id") == operation_id and self._is_automatic(r)]
        for token in doomed:
            self._forget_token(token)
        self._rebuild_aliases()
        return len(doomed)

    def purge_unreferenced(self, remaining_texts: List[str]) -> int:
        """
        Forgets automatic entities that no remaining document contains. Tokens already used in
        saved answers can then no longer be restored in those answers.
        """
        haystack = "\n".join(remaining_texts)
        doomed = []
        for r in self.registry:
            if not self._is_automatic(r):
                continue
            body = r"\s+".join(re.escape(p) for p in r["canonical"].split())
            if not re.search(rf"(?<!\w){body}(?!\w)", haystack, re.IGNORECASE):
                doomed.append(r["token"])
        for token in doomed:
            self._forget_token(token)
        self._rebuild_aliases()
        return len(doomed)

    def get_registry(self) -> List[Dict[str, Any]]:
        return list(self.registry)

    def to_dict(self) -> Dict[str, Any]:
        """Serializable state; surname aliases are derived, so they are not stored."""
        return {
            "counters": dict(self.counters),
            "registry": list(self.registry),
            "whitelist": sorted(self.whitelist),
            "forward_map": {k: v for k, v in self.forward_map.items() if k not in self._aliases},
            "reverse_map": dict(self.reverse_map),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeterministicAnonymizer":
        anonymizer = cls()
        anonymizer.counters.update(data.get("counters", {}))
        anonymizer.registry = list(data.get("registry", []))
        anonymizer.whitelist = set(data.get("whitelist", []))
        anonymizer.forward_map = dict(data.get("forward_map", {}))
        anonymizer.reverse_map = dict(data.get("reverse_map", {}))
        anonymizer._rebuild_aliases()
        return anonymizer

    def _detect_entities(self, text: str) -> List[Dict[str, str]]:
        entities = self._detect_identifiers(text)
        b_entities = self._detect_business_data(text)
        entities += b_entities

        # Blank out detected business entities so bare person patterns do not match substrings of company names
        working_text = text
        for b in b_entities:
            raw = b["raw"]
            working_text = working_text.replace(raw, " " * len(raw))

        entities += self._detect_names(working_text)
        return entities

    def _detect_identifiers(self, text: str) -> List[Dict[str, str]]:
        entities = []
        working_text = text

        # IBAN
        iban_pattern = r'\b[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}\b'
        for m in re.finditer(iban_pattern, working_text):
            entities.append({"raw": m.group(0), "category": "IBAN"})
        working_text = re.sub(iban_pattern, ' ' * 27, working_text)

        # Italian Codice Fiscale
        cf_pattern = r'\b[A-Z]{6}[0-9LMNPQRSTUV]{2}[A-EHLMPR-T][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]\b'
        for m in re.finditer(cf_pattern, working_text, re.IGNORECASE):
            entities.append({"raw": m.group(0).upper(), "category": "CODICE_FISCALE"})
        working_text = re.sub(cf_pattern, ' ' * 16, working_text, flags=re.IGNORECASE)

        # Italian Partita IVA / VAT ID
        piva_pattern = r'(?:P\.?\s*IVA|Partita\s+IVA|C\.?F\.?\/P\.?IVA|VAT\s*(?:ID|No|Number)?)\s*[:.]?\s*([A-Z0-9]{8,14})'
        for m in re.finditer(piva_pattern, working_text, re.IGNORECASE):
            entities.append({"raw": m.group(1), "category": "PARTITA_IVA"})

        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
        for m in re.finditer(email_pattern, working_text):
            entities.append({"raw": m.group(0), "category": "EMAIL"})

        phone_pattern = r'(?:\+?[0-9]{1,4}[\s.-]?)?(?:3\d{2}[\s.-]?\d{3}[\s.-]?\d{3,4}|0\d{1,4}[\s.-]?\d{5,8}|\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})\b'
        for m in re.finditer(phone_pattern, working_text):
            cleaned = m.group(0).strip()
            if len(re.sub(r'\D', '', cleaned)) >= 9:
                entities.append({"raw": cleaned, "category": "TELEFONO"})

        card_pattern = r'(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)'
        for m in re.finditer(card_pattern, working_text):
            candidate = m.group(0).strip()
            digits = re.sub(r'\D', '', candidate)
            if 13 <= len(digits) <= 19 and self._luhn_valid(digits):
                entities.append({"raw": candidate, "category": "CARTA_PAGAMENTO"})

        plate_pattern = r'\b[A-Z]{2}\s?\d{3}\s?[A-Z]{2}\b'
        for m in re.finditer(plate_pattern, working_text, re.IGNORECASE):
            entities.append({"raw": m.group(0), "category": "TARGA"})
        return entities

    @staticmethod
    def _luhn_valid(digits: str) -> bool:
        total = 0
        parity = len(digits) % 2
        for index, char in enumerate(digits):
            value = int(char)
            if index % 2 == parity:
                value *= 2
                if value > 9:
                    value -= 9
            total += value
        return total % 10 == 0

    def _detect_business_data(self, text: str) -> List[Dict[str, str]]:
        entities = []

        # 1. Corporate entities (Title/Upper words followed by exhaustive corporate suffix)
        # Note: corp_word does not include prepositions like "di" or "da" so it never swallows preceding names!
        corp_word = r'(?:[A-Z0-9][A-Za-z0-9.\'\-–]*|&)'
        pattern_suffix = rf'\b({corp_word}(?:[^\S\r\n]+{corp_word}){{0,4}}[^\S\r\n]+{self._CORP_SUFFIX}(?:[^\S\r\n]+(?i:societ[àa]\s+benefit))?)\b'

        # 2. Prefix forms: Studio Legale ..., Studio Associato ..., Società Cooperativa ..., Law Offices of ...
        pattern_prefix = (
            r'\b((?i:Studio\s+Legale|Studio\s+Associato|Studi\s+Associati|Studio\s+Tributario|'
            r'Studio\s+Professionale|Associazione\s+Professionale|Studio\s+Revisori\s+Associati|'
            r'Societ[àa]\s+Cooperativa|Law\s+Offices?\s+of)'
            rf'(?:[^\S\r\n]+(?:{corp_word}|d[’\']|de[li]|della|delle|dei|di|da|e|ed|&|of|and)){{1,5}})\b'
        )

        # 3. Law firms ending with "Associati": Studio ... Associati
        pattern_firm_associati = (
            rf'\b(Studio[^\S\r\n]+{corp_word}(?:[^\S\r\n]+(?:{corp_word}|e|ed|&)){{0,4}}[^\S\r\n]+(?i:Associati))\b'
        )

        for pat in (pattern_suffix, pattern_prefix, pattern_firm_associati):
            for m in re.finditer(pat, text):
                raw = m.group(1).strip()
                clean = re.sub(
                    r'^(?:Per|Con|Tra|Fra|La|Il|Lo|Dalla|Dallo|Dall\'|Dal|Della|Dello|Del|Dei|Degli|The|By|From|For)\s+',
                    '',
                    raw,
                    flags=re.IGNORECASE
                ).strip()
                if len(clean) > 3 and clean.lower() not in self.STOPWORDS:
                    entities.append({"raw": clean, "category": "SOCIETA"})

        # Monetary amounts (€, $, £, EUR, USD, GBP, euro, dollars, pounds)
        amount_pattern = (
            r'(?:'
            r'(?:€|EUR|euro|\$|USD|£|GBP)\s*[0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?|'
            r'[0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{2})?\s*(?:€|\$|£|EUR|euro|USD|GBP|dollars?|pounds?)'
            r')(?!\w)'
        )
        for m in re.finditer(amount_pattern, text, re.IGNORECASE):
            entities.append({"raw": m.group(0).strip(), "category": "IMPORTO"})

        # Dates (Italian + English)
        # e.g. 15/10/2026, 2026-10-15, 15 ottobre 2026, October 15, 2026, 15th October 2026
        months_it_en = (
            r'gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre|'
            r'january|february|march|april|may|june|july|august|september|october|november|december|'
            r'jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec'
        )
        date_pattern = (
            rf'\b(?:'
            rf'[0-3]?[0-9][./-][0-1]?[0-9][./-](?:20|19)\d{{2}}|'
            rf'(?:20|19)\d{{2}}[./-][0-1]?[0-9][./-][0-3]?[0-9]|'
            rf'[0-3]?[0-9](?:st|nd|rd|th)?\s+(?:{months_it_en})\s+(?:20|19)\d{{2}}|'
            rf'(?:{months_it_en})\s+[0-3]?[0-9](?:st|nd|rd|th)?,?\s+(?:20|19)\d{{2}}'
            rf')\b'
        )
        for m in re.finditer(date_pattern, text, re.IGNORECASE):
            entities.append({"raw": m.group(0).strip(), "category": "DATA"})

        # Addresses (IT: Via/Corso/Piazza... EN: Street, Avenue, Blvd, Road...)
        addr_pattern_it = r'\b((?:Via|Viale|Corso|Piazza|Largo|Strada|Vicolo)\s+[A-Z][a-zA-Zàèéìòù\'\s]{3,25},?\s*\d{1,4}(?:\/[a-zA-Z0-9]+)?)\b'
        addr_pattern_en = r'\b(\d{1,5}\s+[A-Z][a-zA-Z0-9\'\s]{2,25}\s+(?:Street|St\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Road|Rd\.?|Lane|Ln\.?|Drive|Dr\.?|Way|Court|Ct\.?))\b'

        for m in re.finditer(addr_pattern_it, text):
            entities.append({"raw": m.group(1).strip(), "category": "INDIRIZZO"})
        for m in re.finditer(addr_pattern_en, text, re.IGNORECASE):
            entities.append({"raw": m.group(1).strip(), "category": "INDIRIZZO"})

        return entities

    def _has_stopword(self, name: str) -> bool:
        return any(part in self.STOPWORDS for part in name.lower().split())

    def _detect_names(self, text: str) -> List[Dict[str, str]]:
        entities = []
        word, particle = self._NAME_WORD, self._PARTICLE
        full_name = rf'{word}(?:\s+{particle})?(?:\s+{word}){{1,2}}'

        # Contextual prefixes (IT: Sig., Dott., Avv... EN: Mr., Mrs., Ms., Dr., Esq., Judge...)
        prefix_pattern = (
            rf'\b(?:'
            rf'Sig\.?(?:ra)?|Dott\.?(?:ssa)?|Ing\.?|Avv\.?|Arch\.?|Rag\.?|Geom\.?|nato a|Sig\.re|'
            rf'Mr\.?|Mrs\.?|Ms\.?|Miss|Dr\.?|Prof\.?|Esq\.?|Judge|Justice|Attorney|Counsel'
            rf')\s+({full_name})\b'
        )

        # Contract roles (IT: tra il signor X, rappresentato da X... EN: by and between X, on behalf of X, represented by X)
        role_pattern = (
            rf'\b(?:'
            rf'tra\s+(?:il\s+signor|la\s+signora|l\'utente)?|da\s+parte\s+di|rappresentat[ao]\s+da(?:l|lla)?|'
            rf'by\s+and\s+between|on\s+behalf\s+of|represented\s+by|executed\s+by|signed\s+by'
            rf')\s+({word}(?:\s+{particle})?\s+{word})\b'
        )

        # Bare "Firstname Lastname"
        bare_pattern = rf'\b({word}(?:\s+{particle})?\s+{word})\b'

        for pattern in (prefix_pattern, role_pattern, bare_pattern):
            for m in re.finditer(pattern, text):
                name = m.group(1).strip()
                if not self._has_stopword(name) and not self._STRIP_CORP_SUFFIX.search(name):
                    entities.append({"raw": name, "category": "PERSONA"})
        return entities
