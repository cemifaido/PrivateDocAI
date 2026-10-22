import re
import unicodedata
import uuid
from typing import Dict, List, Any, Optional, Tuple

from backend.validators import is_valid_iban, is_valid_partita_iva

# How acts introduce a short name for a party: "(d'ora in avanti “X”)", ", di seguito “X”," ...
_INTRO_WORDS = (
    r"d[’']ora\s+(?:in\s+avanti|innanzi)|qui\s+di\s+seguito|di\s+seguito|in\s+seguito|nel\s+seguito|"
    r"(?:nel|in)\s+prosieguo|in\s+appresso|per\s+brevit[àa]|breviter|c\.d\.|cosiddett[oa]|"
    r"hereinafter(?:\s+referred\s+to\s+as|\s+called)?|anche|detta|detto|denominat[ao]|definit[ao]|chiamat[ao]"
)
_QUOTE_OPEN, _QUOTE_CLOSE = "[“\"«]", "[”\"»]"


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
        # Uffici e registri citati come tali (non sono persone), e parole inglesi di contratto
        'catasto', 'fabbricati', 'terreni', 'agenzia', 'entrate', 'service', 'services',
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

    # Words that name a ROLE in an act ("la Compagnia", "il Contraente"), not a person or company.
    # They are common usage: they stay readable, and the definition sentence that links them to
    # the masked party ("[SOCIETA_A] (d'ora in avanti “Compagnia”)") is kept in the text.
    LEGAL_ROLE_WORDS = {
        'compagnia', 'societa', 'società', 'contraente', 'assicurato', 'assicuratore', 'assicuratrice',
        'attore', 'attrice', 'convenuto', 'convenuta', 'appellante', 'appellato', 'appellata',
        'ricorrente', 'resistente', 'opponente', 'opposto', 'opposta', 'chiamato', 'chiamata',
        'terzo', 'terza', 'garante', 'fideiussore', 'cedente', 'cessionario', 'cessionaria',
        'locatore', 'locatrice', 'conduttore', 'conduttrice', 'venditore', 'venditrice', 'acquirente',
        'committente', 'appaltatore', 'appaltatrice', 'fornitore', 'fornitrice', 'cliente', 'mandante',
        'mandatario', 'mandataria', 'socio', 'soci', 'azionista', 'controllante', 'controllata',
        'capogruppo', 'banca', 'istituto', 'ente', 'azienda', 'impresa', 'gruppo', 'parte', 'parti',
        'polizza', 'contratto', 'accordo', 'convenzione', 'atto', 'lettera', 'garanzia', 'finanziatore',
        'mutuante', 'mutuatario', 'debitore', 'creditore', 'datore', 'lavoratore', 'dipendente',
        'professionista', 'consulente', 'perito', 'ctu', 'ctp', 'tribunale', 'giudice', 'curatore',
        'liquidatore', 'amministratore', 'sindaco', 'revisore', 'maggioranza', 'minoranza',
        'company', 'client', 'borrower', 'lender', 'seller', 'buyer', 'contractor', 'subcontractor',
        'employer', 'employee', 'licensor', 'licensee', 'plaintiff', 'defendant', 'insurer', 'insured',
        'party', 'parties', 'agreement', 'policy',
    }
    STOPWORDS = STOPWORDS | LEGAL_ROLE_WORDS

    _DEF_PAREN = re.compile(r"\(([^()]{1,240})\)")
    _DEF_INTRO = re.compile(rf"(?i:{_INTRO_WORDS})")
    _QUOTED_TERM = re.compile(rf"{_QUOTE_OPEN}([^”\"»]{{1,80}}){_QUOTE_CLOSE}")
    # ", di seguito “X” o “Y”," written without parentheses
    _INLINE_DEF = re.compile(
        rf"(?:,\s*|\s+)(?i:{_INTRO_WORDS})(?:[,\s]+(?i:anche|rispettivamente|denominat[ao]|detta|detto))*[,\s:–-]+"
        rf"({_QUOTE_OPEN}[^”\"»]{{1,80}}{_QUOTE_CLOSE}(?:\s*(?:,|;|\be\b|\bed\b|\bo\b|\boppure\b)\s*"
        rf"{_QUOTE_OPEN}[^”\"»]{{1,80}}{_QUOTE_CLOSE})*)")
    _UNQUOTED_TERM = re.compile(
        r"(?i:denominat[ao]|detta|detto|definit[ao]|chiamat[ao])\s+"
        r"([A-ZÀ-Ý][\w&'’.-]*(?:\s+(?:(?:di|del|della|dei|degli|delle)\s+)?[A-ZÀ-Ý][\w&'’.-]*){0,3})")
    # a bare acronym "(TI)" / "(sigla: TI)" / "con sigla TI" right after a party
    _ACRONYM_PAREN = re.compile(r"\(\s*(?:sigla[:\s]+)?([A-Z][A-Z0-9&.]{1,5})\s*\)")
    _ACRONYM_WITH = re.compile(r"\bcon\s+sigla\s+([A-Z][A-Z0-9&.]{1,5})\b")
    _LEADING_ARTICLE = re.compile(r"(?i)^(?:il|lo|la|l[’']|i|gli|le|un|uno|una)\s*")

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
        # Terms defined in the acts ("d'ora in avanti “Pippo”") that point to a masked party:
        # canonical term -> {"token", "text", "cs"}; kept across saves (they cannot be re-derived)
        self._defined: Dict[str, Dict[str, Dict[str, Any]]] = {}  # document key -> canonical term -> info
        # Defined terms that look like names but could not be tied to one party (to be checked)
        self._unassigned: Dict[str, List[str]] = {}  # document key -> defined names not tied to a party
        self._ambiguous_defined: set = set()         # same word defined for different parties in different acts

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

    # Identifiers with a fixed shape: when rules and model disagree, the rule keeps its category
    # (the rules validate the shape, a neural tagger can fragment a long code)
    _MODEL_NAME_CATEGORIES = ("PERSONA", "SOCIETA", "INDIRIZZO")

    @staticmethod
    def _canon(raw: str) -> str:
        return " ".join(raw.lower().rstrip('.,;:').split())

    # a model category may overrule a rule's PERSONA only when the rule had the weakest evidence
    # (two capitalised words) and the model is very sure
    _OVERRULE_SCORE = 0.95

    @staticmethod
    def _occurrences(text: str, phrase: str) -> List[Any]:
        return [m.span() for m in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE)]

    def _merge_model_candidates(self, documents: List[Dict[str, Any]], rule_items: List[Dict[str, Any]],
                                model_by_doc: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Rules first, model on top, DOCUMENT BY DOCUMENT (what one act says never decides what
        happens in another):
        - role words and common terms from the model are ignored whatever the definitions say;
        - same text found by both: the rule's category stays; only a rule PERSONA made of two
          capitalised words yields to a more specific, very confident model category;
        - the model's extra findings are added;
        - a rule PERSONA that, in THIS document, appears only inside a longer name the model found
          is dropped (it would only be noise); if it also appears on its own, it stays.
        """
        by_doc_rules: Dict[Any, List[Dict[str, Any]]] = {}
        for item in rule_items:
            by_doc_rules.setdefault(item.get("doc_key"), []).append(item)
        result: List[Dict[str, Any]] = []
        for index, doc in enumerate(documents):
            key = self._doc_key(doc, index)
            text = doc.get("text", "")
            rules = by_doc_rules.get(key, [])
            model = [m for m in model_by_doc.get(key, [])
                     if not self._is_common_term(m["raw"]) and self._canon(m["raw"]) not in self.STOPWORDS]
            by_canon: Dict[str, Dict[str, Any]] = {}
            same_text: Dict[str, List[Dict[str, Any]]] = {}
            for i in rules:
                canon = self._canon(i["raw"])
                by_canon.setdefault(canon, i)
                same_text.setdefault(canon, []).append(i)
            additions = []
            for m in model:
                canon = self._canon(m["raw"])
                existing = by_canon.get(canon)
                if existing is not None:
                    # the same text can be seen by several rules: it is a weak guess only if EVERY
                    # one of them was the capital-letters guess (a title/role anywhere makes it strong)
                    weak = all(i["category"] == "PERSONA" and i.get("origin") == "bare" for i in same_text[canon])
                    if weak and m["category"] != "PERSONA" and m.get("score", 0) >= self._OVERRULE_SCORE:
                        for i in same_text[canon]:
                            i["category"] = m["category"]
                    continue
                added = {"raw": m["raw"], "category": m["category"], "doc_name": doc.get("filename", key),
                         "doc_key": key, "source": "model"}
                additions.append(added)
                by_canon[canon] = added
            longer = [m["raw"] for m in model
                      if m["category"] in self._MODEL_NAME_CATEGORIES and " " in m["raw"].strip()]
            inside_spans = [span for whole in longer for span in self._occurrences(text, whole)]
            kept = []
            for item in rules:
                if item["category"] == "PERSONA" and inside_spans:
                    own = self._occurrences(text, item["raw"])
                    if own and all(any(w0 <= o0 and o1 <= w1 and (w1 - w0) > (o1 - o0) for w0, w1 in inside_spans)
                                   for o0, o1 in own):
                        continue
                kept.append(item)
            result.extend(kept + additions)
        return result

    def analyze_documents(self, documents: List[Dict[str, Any]],
                          extra_candidates: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> List[Dict[str, Any]]:
        combined_candidates = []

        for doc_idx, doc in enumerate(documents):
            text = doc.get("text", "")
            doc_name = doc.get("filename", f"Doc_{doc_idx}")
            found = self._detect_entities(text)
            for item in found:
                item["doc_name"] = doc_name
                item["doc_key"] = self._doc_key(doc, doc_idx)
                combined_candidates.append(item)

        if extra_candidates:
            combined_candidates = self._merge_model_candidates(documents, combined_candidates, extra_candidates)

        # Prioritize non-PERSONA candidates first (SOCIETA, IBAN, CF, IMPORTO, DATA, etc.)
        # so company aliases are claimed before bare person name heuristics match them.
        def sort_key(x):
            is_person = 1 if x["category"] == "PERSONA" else 0
            return (is_person, -len(x["raw"]))

        combined_candidates.sort(key=sort_key)

        # Definitions ("X (d'ora in avanti “Y”)"): role words stay readable and must never turn
        # into entities of their own; names are linked to X once everything is registered.
        definitions = [(self._doc_key(doc, i), doc.get("text", ""), self._find_definitions(doc.get("text", "")))
                       for i, doc in enumerate(documents)]
        common_terms = {self._norm_term(t) for _, _, defs in definitions for d in defs
                        for t in d["linked"] + d["unlinked"] if self._is_common_term(t)}

        for item in combined_candidates:
            raw = item["raw"]
            cat = item["category"]
            canon = raw.lower().rstrip('.,;:')
            if canon in self.whitelist or self._norm_term(raw) in common_terms:
                continue
            if canon in self.forward_map:
                continue
            self.get_or_create_token(raw, cat)

        self._link_definitions(definitions)

        self._rebuild_aliases()
        return self.get_registry()

    # ----- defined terms ("d'ora in avanti ...") -----
    @staticmethod
    def _doc_key(doc: Dict[str, Any], index: int = 0) -> str:
        return str(doc.get("id") or doc.get("filename") or f"doc{index}")

    def _norm_term(self, term: str) -> str:
        t = " ".join(term.strip().strip("“”\"«»'’").lower().split())
        t = self._LEADING_ARTICLE.sub("", t).strip()
        return t.rstrip('.,;:')

    def _is_common_term(self, term: str) -> bool:
        """A role word or phrase ("Compagnia", "Socio di Maggioranza"): not worth masking."""
        words = self._norm_term(term).replace("’", " ").replace("'", " ").split()
        if not words:
            return True
        connectors = {"di", "del", "della", "dei", "degli", "delle", "e", "ed", "d"}
        return words[0] in self.LEGAL_ROLE_WORDS or all(w in self.LEGAL_ROLE_WORDS or w in connectors for w in words)

    def _group_quoted(self, inside: str, quoted) -> List[List[str]]:
        """Quoted terms in groups: 'o' keeps them together, 'e' / ',' starts a new group."""
        groups = [[quoted[0].group(1).strip()]]
        for prev, cur in zip(quoted, quoted[1:]):
            separator = inside[prev.end():cur.start()]
            if re.search(r"(?i)\bo\b|\boppure\b|\bor\b", separator):
                groups[-1].append(cur.group(1).strip())
            else:
                groups.append([cur.group(1).strip()])
        return groups

    def _find_definitions(self, text: str) -> List[Dict[str, Any]]:
        """
        Where the act gives a short name to the party written just before: in parentheses, inline
        ("..., di seguito “X”,") or as a bare acronym. With "rispettivamente" only the LAST group
        of terms belongs to that party (the earlier ones refer to earlier items of the sentence).
        """
        found: List[Dict[str, Any]] = []
        for m in self._DEF_PAREN.finditer(text):
            inside = m.group(1)
            quoted = list(self._QUOTED_TERM.finditer(inside))
            starts_quoted = re.match(r"\s*[“\"«]", inside) is not None
            acronym = self._ACRONYM_PAREN.fullmatch(m.group(0))
            if acronym:
                found.append({"start": m.start(), "linked": [acronym.group(1)], "unlinked": []})
                continue
            if not (self._DEF_INTRO.search(inside) or starts_quoted):
                continue
            groups: List[List[str]] = []
            if quoted:
                groups = self._group_quoted(inside, quoted)
            else:
                un = self._UNQUOTED_TERM.search(inside)
                if un:
                    groups = [[un.group(1).strip().rstrip('.,;:')]]
            if not groups:
                continue
            respectively = re.search(r"(?i)rispettivamente|respectively", inside) is not None
            linked = groups[-1] if respectively else [t for g in groups for t in g]
            unlinked = [t for g in groups[:-1] for t in g] if respectively else []
            found.append({"start": m.start(), "linked": linked, "unlinked": unlinked})

        for m in self._INLINE_DEF.finditer(text):
            quoted = list(self._QUOTED_TERM.finditer(m.group(1)))
            if quoted:
                groups = self._group_quoted(m.group(1), quoted)
                found.append({"start": m.start(), "linked": [t for g in groups for t in g], "unlinked": []})
        for m in self._ACRONYM_WITH.finditer(text):
            found.append({"start": m.start(), "linked": [m.group(1)], "unlinked": []})
        return found

    def _find_antecedent(self, before: str) -> Optional[Dict[str, Any]]:
        """The registered entity whose name ends right where the definition starts."""
        tail = " ".join(before.lower().split()).rstrip(" .,;:")
        best = None
        for r in self.registry:
            canon = r["canonical"]
            if tail.endswith(canon) and (best is None or len(canon) > len(best["canonical"])):
                best = r
        return best

    def _merge_tokens(self, src: str, dst: str):
        """Two codes that turned out to be the same party: src becomes dst everywhere."""
        if src == dst:
            return
        for key in [k for k, v in self.forward_map.items() if v == src]:
            self.forward_map[key] = dst
        for scope in self._defined.values():
            for info in scope.values():
                if info["token"] == src:
                    info["token"] = dst
        self.reverse_map.pop(src, None)
        self.registry = [r for r in self.registry if r["token"] != src]

    @property
    def unassigned_terms(self) -> set:
        return {t for terms in self._unassigned.values() for t in terms}

    def forget_document(self, doc_key: str):
        """A removed document takes its own definitions with it."""
        self._defined.pop(str(doc_key), None)
        self._unassigned.pop(str(doc_key), None)

    def _link_definitions(self, definitions):
        """
        Binds each defined name to its party INSIDE the document that defines it: in another act
        the same word may mean someone else. A name that shows up unbound elsewhere is flagged by
        the pre-flight as a suspect instead of being guessed.
        """
        for doc_key, text, defs in definitions:
            self._defined.pop(doc_key, None)  # re-read from scratch when the document is analysed again
            self._unassigned.pop(doc_key, None)
            for d in defs:
                entity = self._find_antecedent(text[:d["start"]])
                for term in d["unlinked"]:
                    if not self._is_common_term(term):
                        self._unassigned.setdefault(doc_key, []).append(term)
                if entity is None:
                    continue
                token = entity["token"]
                for term in d["linked"]:
                    if self._is_common_term(term):
                        continue
                    canon = self._norm_term(term)
                    if len(canon) < 2 or canon in self.whitelist:
                        continue
                    existing = self.forward_map.get(canon)
                    if existing == token:
                        continue  # already masked everywhere with the right code
                    if existing:
                        owner = next((r for r in self.registry if r["token"] == existing), None)
                        if owner is None or not self._is_automatic(owner):
                            continue  # chosen by the user: not touched
                        self._merge_tokens(existing, token)
                        continue
                    clean = self._LEADING_ARTICLE.sub("", term.strip()).strip()
                    acronym = clean.isupper() and " " not in clean and len(clean) <= 5
                    self._defined.setdefault(doc_key, {})[canon] = {"token": token, "text": clean, "cs": acronym}

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

        # A company written without its legal form ("Zeta Holding") must not be a second, different party
        company_base = {}
        for r in self.registry:
            if r["category"] == "SOCIETA":
                cleaned = self._STRIP_CORP_SUFFIX.sub("", r["canonical"]).strip()
                if cleaned and cleaned != r["canonical"]:
                    company_base.setdefault(cleaned, set()).add(r["token"])
        for r in list(self.registry):
            tokens = company_base.get(r["canonical"])
            if r["category"] == "PERSONA" and self._is_automatic(r) and tokens and len(tokens) == 1:
                self._merge_tokens(r["token"], next(iter(tokens)))

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

        # Defined terms whose party has been removed are dropped
        for doc_key in list(self._defined):
            scope = self._defined[doc_key]
            for canon in [c for c, info in scope.items() if info["token"] not in self.reverse_map]:
                del scope[canon]
            if not scope:
                del self._defined[doc_key]

    def _defined_for(self, doc_key: Optional[str]) -> Dict[str, Dict[str, Any]]:
        """Terms defined in one document; for text that belongs to no document (the request), all of them."""
        if doc_key is not None:
            return dict(self._defined.get(str(doc_key), {}))
        merged: Dict[str, Dict[str, Any]] = {}
        ambiguous: set = set()
        for scope in self._defined.values():
            for canon, info in scope.items():
                if canon in merged and merged[canon]["token"] != info["token"]:
                    ambiguous.add(canon)  # two acts, two different parties: do not guess
                merged.setdefault(canon, info)
        for canon in ambiguous:
            merged.pop(canon, None)
        self._ambiguous_defined = ambiguous
        return merged

    def _build_mask_pattern(self, doc_key: Optional[str] = None):
        """One combined regex, longest entity first, so the text is scanned once."""
        defined = self._defined_for(doc_key)
        keys = set(self.forward_map) | set(defined)
        alternatives = []
        for key in sorted(keys, key=len, reverse=True):
            body = r"\s+".join(re.escape(part) for part in key.split())
            info = defined.get(key) if key not in self.forward_map else None
            if info and info["cs"]:
                # "TI" must not hit the pronoun "ti": acronyms match their exact capitals only
                body = "(?-i:" + re.escape(info["text"]) + ")"
            if key[-1].isalnum():
                dot = r"\.?" if key[-1].isalpha() and "." in key else ""
                tail = rf"{dot}(?![\w\]])"
            else:
                tail = r"(?=[\s|:,.;)]|$)(?!\])"
            alternatives.append(body + tail)
        if not alternatives:
            return None, defined
        return re.compile(r"(?<![\w\[])(?:" + "|".join(alternatives) + ")", re.IGNORECASE), defined

    def mask_text(self, text: str, doc_key: Optional[str] = None) -> str:
        """Replaces all detected entities, their aliases and the terms defined in `doc_key` with their tokens."""
        pattern, defined = self._build_mask_pattern(doc_key)
        if pattern is None:
            return text

        def lookup(key: str) -> Optional[str]:
            if key in self.forward_map:
                return self.forward_map[key]
            info = defined.get(key)
            return info["token"] if info else None

        def to_token(m):
            found = " ".join(m.group(0).lower().split())
            return lookup(found) or lookup(found.rstrip(".,;:")) or m.group(0)

        return pattern.sub(to_token, text)

    # An LLM answer often damages the placeholders: brackets lost, lower case, spaces or hyphens
    # instead of the underscore. Only tokens registered in THIS session are ever replaced.
    _BRACKETED_TOKEN = re.compile(r"\[\s*([A-Za-z]+(?:[\s_\-]+[A-Za-z0-9]+)+)\s*\]")
    _BARE_TOKEN = re.compile(r"(?<![\w\[])([A-Z]+(?:_[A-Z]+)*_[A-Z0-9]+)(?![\w\]])")

    def de_anonymize_with_report(self, masked_text: str) -> Tuple[str, Dict[str, Any]]:
        """
        Restores real values into the LLM answer in a single pass (restored text is never re-scanned).
        Exact tokens are replaced as before; damaged forms of a registered token ([persona_1],
        [ PERSONA 1 ], bare PERSONA_1) are replaced too and REPORTED, and a bracketed token of a known
        category that is not registered (e.g. [PERSONA_9]) is left in place and reported as unknown.
        """
        fuzzy: List[Dict[str, str]] = []
        unknown: List[str] = []
        categories = set(self.counters)

        def lookup(inner: str) -> Optional[str]:
            token = "[" + re.sub(r"[\s_\-]+", "_", inner).upper() + "]"
            return token if token in self.reverse_map else None

        def replace(m):
            bracketed = m.group(1) is not None
            inner = m.group(1) if bracketed else m.group(2)
            token = lookup(inner)
            if token is None:
                prefix = re.sub(r"[\s_\-]+", "_", inner).upper().rsplit("_", 1)[0]
                if bracketed and prefix in categories and m.group(0) not in unknown:
                    unknown.append(m.group(0))
                return m.group(0)
            if m.group(0) != token:
                fuzzy.append({"found": m.group(0), "token": token})
            return self.reverse_map[token]

        # one combined pass: whatever is inserted is not scanned again
        pattern = re.compile(f"{self._BRACKETED_TOKEN.pattern}|{self._BARE_TOKEN.pattern}")
        restored = pattern.sub(replace, masked_text)
        return restored, {"fuzzy": fuzzy, "unknown": unknown}

    def de_anonymize_text(self, masked_text: str) -> str:
        """Restores real entity values into the LLM generated output (see de_anonymize_with_report)."""
        return self.de_anonymize_with_report(masked_text)[0]

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
        for canon in sorted(self._ambiguous_defined):
            if canon.title() not in suspects and re.search(
                    rf'(?<![\w\[]){re.escape(canon)}(?![\w\]])', without_tokens, re.IGNORECASE):
                suspects.append(canon.title())
        for term in sorted(self.unassigned_terms):
            if term not in suspects and re.search(
                    rf'(?<![\w\[]){re.escape(term)}(?![\w\]])', without_tokens, re.IGNORECASE):
                suspects.append(term)
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

    # Categories the user can pick for text the program did not recognise (right-click menu, doubtful words).
    PRESET_CATEGORIES = {
        "PERSONA": "Persona", "SOCIETA": "Società / Ente", "RIFERIMENTO": "Numero di protocollo / pratica",
        "INDIRIZZO": "Indirizzo", "CODICE_FISCALE": "Codice fiscale", "PARTITA_IVA": "Partita IVA",
        "IBAN": "IBAN / conto", "IMPORTO": "Importo", "DATA": "Data", "EMAIL": "E-mail",
        "TELEFONO": "Telefono", "TARGA": "Targa", "RISERVATO": "Altro dato riservato",
    }

    @staticmethod
    def normalize_category(name: str) -> str:
        """'Numero di Protocollo' -> 'NUMERO_DI_PROTOCOLLO': letters and underscores only, as the
        placeholders [CATEGORIA_1] are recognised in the answers by exactly that shape."""
        plain = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
        ident = re.sub(r"[^A-Za-z]+", "_", plain).strip("_").upper()
        if len(re.sub(r"_", "", ident)) < 2 or len(ident) > 30 or ident == "IGNORE":
            raise ValueError("Nome di categoria non valido: usa da 2 a 30 lettere.")
        return ident

    def add_custom_entity(self, text: str, category: str) -> str:
        token = self.get_or_create_token(text, category)
        for r in self.registry:
            if r["token"] == token:
                r["manual"] = True  # chosen by the user: never garbage-collected
        self._rebuild_aliases()
        return token

    def _forget_token(self, token: str):
        for scope in self._defined.values():
            for canon in [c for c, info in scope.items() if info["token"] == token]:
                del scope[canon]
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
            "defined_aliases": {k: dict(v) for k, v in self._defined.items()},
            "unassigned_terms": {k: list(v) for k, v in self._unassigned.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeterministicAnonymizer":
        anonymizer = cls()
        anonymizer.counters.update(data.get("counters", {}))
        anonymizer.registry = list(data.get("registry", []))
        anonymizer.whitelist = set(data.get("whitelist", []))
        anonymizer.forward_map = dict(data.get("forward_map", {}))
        anonymizer.reverse_map = dict(data.get("reverse_map", {}))
        anonymizer._defined = {k: dict(v) for k, v in data.get("defined_aliases", {}).items()}
        anonymizer._unassigned = {k: list(v) for k, v in data.get("unassigned_terms", {}).items()}
        anonymizer._rebuild_aliases()
        return anonymizer

    def _detect_entities(self, text: str) -> List[Dict[str, str]]:
        references = self._detect_references(text)
        # blank the references first: digits inside a VIN or a CUP must not be read as a phone number
        without_refs = text
        for ref in references:
            without_refs = without_refs.replace(ref["raw"], " " * len(ref["raw"]))
        entities = self._detect_identifiers(without_refs)
        entities += references
        b_entities = self._detect_business_data(text)
        entities += b_entities

        # Blank out detected business entities so bare person patterns do not match substrings of company names
        working_text = text
        for b in b_entities + references:
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

        # IBAN in the printed form (groups of four): too loose to trust by shape alone, so only a
        # valid checksum accepts it. A failed checksum never REMOVES a mask found by the rules above
        # (a typo or an OCR error must not make a real identifier readable).
        for m in re.finditer(r'\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b', working_text):
            if " " in m.group(0) and is_valid_iban(m.group(0)):
                entities.append({"raw": m.group(0), "category": "IBAN"})
                working_text = working_text.replace(m.group(0), ' ' * len(m.group(0)))

        # Italian Codice Fiscale
        cf_pattern = r'\b[A-Z]{6}[0-9LMNPQRSTUV]{2}[A-EHLMPR-T][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]\b'
        for m in re.finditer(cf_pattern, working_text, re.IGNORECASE):
            entities.append({"raw": m.group(0).upper(), "category": "CODICE_FISCALE"})
        working_text = re.sub(cf_pattern, ' ' * 16, working_text, flags=re.IGNORECASE)

        # Italian Partita IVA / VAT ID
        piva_pattern = r'(?:P\.?\s*IVA|Partita\s+IVA|C\.?F\.?\/P\.?IVA|VAT\s*(?:ID|No|Number)?)\s*[:.]?\s*([A-Z0-9]{8,14})'
        for m in re.finditer(piva_pattern, working_text, re.IGNORECASE):
            entities.append({"raw": m.group(1), "category": "PARTITA_IVA"})

        # Partita IVA with the country prefix and no label: accepted only with a valid check digit
        for m in re.finditer(r'\bIT ?\d{11}\b', working_text):
            if is_valid_partita_iva(m.group(0)):
                entities.append({"raw": m.group(0), "category": "PARTITA_IVA"})

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

    # Identifiers that follow a keyword ("polizza n. ...", "CIG ...", "Foglio 21, particella 345").
    # (category, keyword-led pattern; the capture group is the value to mask, or the whole match)
    _REFERENCE_PATTERNS = [
        ("RIFERIMENTO", re.compile(
            r"(?i)\b(?:polizza|sinistro|pratica|protocollo|fascicolo|repertorio|rep\.|(?:n\.?\s*)?R\.?\s?G\.?(?:\s?N\.?)?)"
            r"\s*(?:n\.?|nr\.?|numero|n°)?\s*[:.]?\s*([A-Z0-9][A-Z0-9/.\-]*\d[A-Z0-9/.\-]*)")),
        ("RIFERIMENTO", re.compile(r"(?i)\bREA\s*[:.]?\s*([A-Z]{2}\s*[-–]?\s*\d{5,8})\b")),
        ("RIFERIMENTO", re.compile(r"(?i)\b(?:codice\s+destinatario|codice\s+univoco|SDI)\s*[:.]?\s*([A-Z0-9]{7})\b")),
        ("RIFERIMENTO", re.compile(r"(?i)\bCIG\s*[:.]?\s*([A-Z0-9]{10})\b")),
        ("RIFERIMENTO", re.compile(r"(?i)\bCUP\s*[:.]?\s*([A-Z]\d{2}[A-Z]\d{11})\b")),
        ("CATASTO", re.compile(
            r"(?i)\b(?:foglio|fg\.?)\s*\d+[\s,;]*(?:particella|part\.?|p\.lla|mapp(?:ale)?\.?)\s*\d+"
            r"(?:[\s,;]*sub(?:alterno)?\.?\s*\d+)?")),
        ("TELAIO", re.compile(r"(?i)\b(?:telaio|VIN)\s*(?:n\.?)?\s*[:.]?\s*([A-HJ-NPR-Z0-9]{17})\b")),
        ("DOC_IDENTITA", re.compile(
            r"(?i)\b(?:passaporto|patente(?:\s+di\s+guida)?|carta\s+d[’']identit[àa]|C\.?I\.?E\.?)"
            r"\s*(?:n\.?|nr\.?|numero|n°)?\s*[:.]?\s*([A-Z0-9]{6,12})\b")),
        ("BIC", re.compile(r"(?i)\b(?:BIC|SWIFT)\s*[:/-]?\s*([A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b")),
        ("MATRICOLA", re.compile(r"(?i)\bmatricola\s*(?:n\.?|nr\.?|numero|n°)?\s*[:.]?\s*([A-Z0-9][A-Z0-9-]{2,11})\b")),
    ]

    def _detect_references(self, text: str) -> List[Dict[str, str]]:
        found = []
        for category, pattern in self._REFERENCE_PATTERNS:
            for m in pattern.finditer(text):
                raw = (m.group(1) if m.groups() else m.group(0)).strip().rstrip(".,;:-/")
                has_digit = any(c.isdigit() for c in raw)
                if category in ("RIFERIMENTO", "DOC_IDENTITA", "MATRICOLA", "TELAIO") and not has_digit:
                    continue  # a word, not a number ("pratica legale", "patente di guida")
                if category == "RIFERIMENTO" and len(raw) < 5 and "/" not in raw:
                    continue  # "pratica 12", "protocollo 7": too short to be a reference
                if len(raw) >= 3:
                    found.append({"raw": raw, "category": category})
        return found

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

        # "bare" = two capitalised words and nothing else: the weakest evidence; a title or a role
        # in front of the name ("Avv.", "rappresentata da") is strong evidence
        for origin, pattern in (("prefix", prefix_pattern), ("role", role_pattern), ("bare", bare_pattern)):
            for m in re.finditer(pattern, text):
                name = m.group(1).strip()
                if not self._has_stopword(name) and not self._STRIP_CORP_SUFFIX.search(name):
                    entities.append({"raw": name, "category": "PERSONA", "origin": origin})
        return entities
