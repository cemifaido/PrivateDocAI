"""
Fail-closed check run after the build: the folder to distribute must not contain working data
(password files, saved cases, browser profiles with login cookies).

Usage: python check_dist.py [folder]      (default: dist\\PrivateDocAI)
Exit code 0 = clean, 1 = something that must not be shipped was found.
"""
import os
import sys

FORBIDDEN_TOP_LEVEL = {"data", "profiles", "vault.json"}
FORBIDDEN_FILE_NAMES = {"vault.json", "cookies", "login data", "login data for account", "web data", "local state"}
FORBIDDEN_SUFFIXES = (".enc",)


def scan(folder: str):
    problems = []
    for name in os.listdir(folder):
        if name.lower() in FORBIDDEN_TOP_LEVEL:
            problems.append(os.path.join(folder, name))
    for root, dirs, files in os.walk(folder):
        # the bundled libraries live in _internal; only look for data we would create ourselves
        for fname in files:
            lowered = fname.lower()
            if lowered in FORBIDDEN_FILE_NAMES or lowered.endswith(FORBIDDEN_SUFFIXES):
                problems.append(os.path.join(root, fname))
    return sorted(set(problems))


def main() -> int:
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join("dist", "PrivateDocAI")
    if not os.path.isdir(folder):
        print(f"Cartella non trovata: {folder}")
        return 1
    problems = scan(folder)
    if problems:
        print("ATTENZIONE: la cartella contiene dati che non vanno distribuiti:")
        for p in problems:
            print("  -", p)
        print("Non distribuire questa cartella: ricostruiscila (build_exe.bat) senza averla mai avviata.")
        return 1
    print(f"OK: {folder} non contiene password, pratiche né profili del browser.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
