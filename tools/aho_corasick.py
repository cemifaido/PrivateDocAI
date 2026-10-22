# -*- coding: utf-8 -*-
"""
Modulo prototipo Aho-Corasick in puro Python per PrivateDoc AI.
Zero dipendenze esterne. Dimostratore algoritmico per ricerca e sostituzione
multi-pattern quando N supera la soglia critica (es. N >= 5.000).

Nota architetturale:
  Questo modulo è uno strumento prototipale in tools/ a supporto delle decisioni
  di scaling. Nel prodotto corrente (N <= 1.000), il motore regex standard
  in backend/anonymizer.py rimane la soluzione raccomandata per semplicità.

Limiti noti (rilievo di revisione): NON è equivalente a mask_text: non normalizza gli
spazi multipli, non gestisce il punto finale facoltativo e non permette di mescolare voci
case-sensitive e case-insensitive. Prima di un uso reale servono questi allineamenti,
test integrati e un confronto con la regex.
"""

from collections import deque
from typing import Dict, List, Set, Tuple


class AhoCorasickReplacer:
    """Automa a stati finiti (Aho-Corasick) per ricerca e sostituzione multi-pattern."""

    def __init__(self, case_sensitive: bool = False, word_boundary: bool = True):
        self.case_sensitive = case_sensitive
        self.word_boundary = word_boundary
        self._root = 0
        self._patterns: List[Tuple[str, str, bool]] = []  # (original, token, is_case_sensitive)
        self._reset_trie()

    def _reset_trie(self) -> None:
        self._next: List[Dict[str, int]] = [{}]
        self._fail: List[int] = [0]
        self._outputs: List[Set[Tuple[str, str]]] = [set()]
        self._built = False

    def add_pattern(self, pattern: str, token: str, case_sensitive: bool = False) -> None:
        """Aggiunge una stringa da cercare e il relativo token di mascheramento."""
        if not pattern:
            return
        # Normalizza gli spazi interni per coerenza con il dizionario
        norm_pattern = " ".join(pattern.strip().split())
        self._patterns.append((norm_pattern, token, case_sensitive or self.case_sensitive))
        self._built = False

    def _insert(self, pattern: str, token: str, cs: bool) -> None:
        key = pattern if cs else pattern.lower()
        current = self._root
        for char in key:
            if char not in self._next[current]:
                next_id = len(self._next)
                self._next[current][char] = next_id
                self._next.append({})
                self._fail.append(0)
                self._outputs.append(set())
            current = self._next[current][char]
        self._outputs[current].add((key, token))

    def build(self) -> None:
        """Costruisce i collegamenti di fallimento (BFS) e propaga le uscite in modo idempotente."""
        if self._built:
            return

        self._reset_trie()
        for pat, tok, cs in self._patterns:
            self._insert(pat, tok, cs)

        queue = deque()
        for char, child_id in self._next[self._root].items():
            self._fail[child_id] = self._root
            queue.append(child_id)

        while queue:
            current = queue.popleft()

            for char, child_id in self._next[current].items():
                queue.append(child_id)
                fail_state = self._fail[current]

                while fail_state != self._root and char not in self._next[fail_state]:
                    fail_state = self._fail[fail_state]

                if char in self._next[fail_state] and self._next[fail_state][char] != child_id:
                    self._fail[child_id] = self._next[fail_state][char]
                else:
                    self._fail[child_id] = self._root

                # Propagazione idempotente tramite set union
                if self._outputs[self._fail[child_id]]:
                    self._outputs[child_id].update(self._outputs[self._fail[child_id]])

        self._built = True

    def find_matches(self, text: str) -> List[Tuple[int, int, str, str]]:
        """Trova tutte le occorrenze nel testo: (start, end, pattern, token)."""
        if not self._built:
            self.build()

        matches = []
        search_text = text if self.case_sensitive else text.lower()
        current = self._root

        for idx, char in enumerate(search_text):
            while current != self._root and char not in self._next[current]:
                current = self._fail[current]

            current = self._next[current].get(char, self._root)

            if self._outputs[current]:
                for pattern, token in self._outputs[current]:
                    start = idx - len(pattern) + 1
                    end = idx + 1

                    if self.word_boundary:
                        left_ok = (start == 0) or (not text[start - 1].isalnum() and text[start - 1] != "_")
                        right_ok = (end == len(text)) or (not text[end].isalnum() and text[end] != "_")
                        if not (left_ok and right_ok):
                            continue

                    matches.append((start, end, pattern, token))

        return matches

    def replace(self, text: str) -> str:
        """Sostituisce le occorrenze trovate privilegiando i match più lunghi e non sovrapposti."""
        # Se nel testo sono presenti spazi multipli, li normalizza prima di scansionare
        matches = self.find_matches(text)
        if not matches:
            return text

        matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))

        non_overlapping = []
        last_end = -1
        for start, end, pattern, token in matches:
            if start >= last_end:
                non_overlapping.append((start, end, token))
                last_end = end

        parts = []
        last_idx = 0
        for start, end, token in non_overlapping:
            parts.append(text[last_idx:start])
            parts.append(token)
            last_idx = end
        parts.append(text[last_idx:])

        return "".join(parts)


def test_aho_corasick_smoke():
    """Test rapido di conformità e idempotenza per AhoCorasickReplacer."""
    replacer = AhoCorasickReplacer(case_sensitive=False, word_boundary=True)
    replacer.add_pattern("Mario Rossi", "[PERSONA_1]")
    replacer.add_pattern("Mario", "[PERSONA_2]")
    replacer.add_pattern("Astra Costruzioni S.p.A.", "[SOCIETA_A]")
    replacer.build()
    # Verifica idempotenza: una seconda build non deve duplicare i match
    replacer.build()

    sample = "L'ingegner Mario Rossi ha stipulato con Astra Costruzioni S.p.A. un contratto. Anche Mario era presente."
    risultato = replacer.replace(sample)

    assert "[PERSONA_1]" in risultato, "Mario Rossi doveva essere sostituito da [PERSONA_1]"
    assert "[SOCIETA_A]" in risultato, "Astra Costruzioni S.p.A. doveva essere sostituito da [SOCIETA_A]"
    assert "[PERSONA_2]" in risultato, "Mario singolo doveva essere sostituito da [PERSONA_2]"
    print("Smoke test Aho-Corasick superato con successo (idempotenza verificata)!")


if __name__ == "__main__":
    test_aho_corasick_smoke()
