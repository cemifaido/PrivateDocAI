import os
import time
import threading
import traceback
import webbrowser
from typing import Optional, Dict, Any
from playwright.sync_api import sync_playwright

from .runtime import APP_DIR, FROZEN, installed_chrome

class BrowserBridge:
    """
    Manages persistent browser sessions for Gemini, ChatGPT, and Claude.
    Allows non-technical users to log in with their regular username/password / Google account
    directly in the official web interface without needing API keys.
    """

    PROVIDERS = {
        "gemini": {
            "name": "Google Gemini",
            "url": "https://gemini.google.com/app",
            "check_selector": ".ql-editor, rich-textarea, div[contenteditable='true'], [aria-label*='prompt']",
            "prompt_selector": ".ql-editor, rich-textarea, div[contenteditable='true']",
            "logged_out_selector": "a[href*='accounts.google.com/ServiceLogin'], a[href*='accounts.google.com/AccountChooser'], a[href*='accounts.google.com/v3/signin']",
            "send_selector": "button[aria-label*='Invia messaggio'], button[aria-label*='Invia'], button[aria-label*='Send'], button.send-button",
            "response_selector": "message-content, .model-response-text, [class*='model-response'], .response-content"
        },
        "chatgpt": {
            "name": "ChatGPT (OpenAI)",
            "url": "https://chatgpt.com/",
            "check_selector": "#prompt-textarea, textarea[placeholder*='Message']",
            "prompt_selector": "#prompt-textarea, textarea",
            "logged_out_selector": "[data-testid='login-button'], [data-testid='signup-button']",
            "send_selector": "button[data-testid='send-button']",
            "response_selector": "div[data-message-author-role='assistant']"
        },
        "claude": {
            "name": "Claude (Anthropic)",
            "url": "https://claude.ai/",
            "check_selector": "div[contenteditable='true'], textarea",
            "prompt_selector": "div[contenteditable='true'], textarea",
            "logged_out_selector": "a[href*='/login'], button[data-testid='login-button'], input[type='email']",
            "send_selector": "button[aria-label*='Send Message'], button[aria-label*='Invia']",
            "response_selector": ".font-claude-message, [data-is-streaming='false']"
        }
    }

    # Providers whose anti-bot check (Cloudflare, Google sign-in) rejects any
    # automated browser: they are used only through copy & paste.
    MANUAL_ONLY = {"gemini", "claude", "chatgpt"}

    def __init__(self, base_profile_dir: Optional[str] = None):
        # abspath: a ".." left in the path makes headless Chromium fail to read its profile
        self.base_profile_dir = os.path.abspath(
            base_profile_dir or os.path.join(APP_DIR, "profiles"))
        os.makedirs(self.base_profile_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._login_threads: Dict[str, threading.Thread] = {}
        self.login_headless = False  # tests only
        self._notices: Dict[str, str] = {}   # provider -> why the automatic login cannot work (this run only)

    @staticmethod
    def _browser_kwargs() -> Dict[str, Any]:
        """
        Packaged app: use the Chrome installed on the PC (Chromium is not bundled).
        From source: Playwright's own Chromium, so existing profiles keep working.
        """
        return {"channel": "chrome"} if FROZEN and installed_chrome() else {}

    def get_profile_path(self, provider: str) -> str:
        path = os.path.join(self.base_profile_dir, provider)
        os.makedirs(path, exist_ok=True)
        return path

    def open_login_window(self, provider: str) -> Dict[str, Any]:
        """
        Launches a headful browser window for the user to log in with their standard username/password.
        Runs in a separate thread so it doesn't block FastAPI.
        """
        if provider not in self.PROVIDERS:
            return {"status": "error", "message": f"Provider {provider} non supportato."}

        profile_path = self.get_profile_path(provider)
        target_url = self.PROVIDERS[provider]["url"]

        if provider in self.MANUAL_ONLY:
            webbrowser.open(target_url)
            return {
                "status": "success",
                "message": (f"{self.PROVIDERS[provider]['name']} non consente l'accesso tramite il browser automatico "
                            "(verifica anti-bot). Ho aperto il sito nel tuo browser normale: usa il pannello "
                            "«Copia & Decifra» per incollare il testo anonimo e la risposta.")
            }

        self._notices.pop(provider, None)
        opened = threading.Event()
        outcome: Dict[str, Any] = {"error": None}

        def _run_login():
            context = None
            try:
                with sync_playwright() as p:
                    context = p.chromium.launch_persistent_context(
                        **self._browser_kwargs(),
                        user_data_dir=profile_path,
                        headless=self.login_headless,
                        args=["--start-maximized"],
                        viewport=None
                    )
                    closed = []
                    context.on("close", lambda *_: closed.append(True))
                    page = context.new_page()
                    opened.set()          # the window exists: the caller can answer "open"
                    page.goto(target_url, wait_until="domcontentloaded")

                    # Keep open until the user closes the window. wait_for_timeout (not
                    # time.sleep) lets Playwright process the "browser closed" event,
                    # otherwise this loop never ends and the profile stays marked as busy.
                    while not closed and context.pages:
                        context.pages[0].wait_for_timeout(500)
                        # Google refuses sign-in in a browser driven by automation: say so and hand over to the
                        # user's normal browser (the program does not try to hide that it is automated)
                        if any(self.GOOGLE_REJECTED in pg.url for pg in context.pages):
                            self._notices[provider] = (
                                f"{self.PROVIDERS[provider]['name']} non consente l'accesso tramite il browser "
                                "automatico: usa «Copia & Decifra» con il tuo browser normale.")
                            webbrowser.open(target_url)
                            break
            except Exception as exc:
                # never swallowed in silence: the user is told why no window appeared
                outcome["error"] = exc
                traceback.print_exc()
            finally:
                opened.set()
                try:
                    if context is not None:
                        context.close()
                except Exception:
                    pass

        t = threading.Thread(target=_run_login, daemon=True)
        self._login_threads[provider] = t
        t.start()
        opened.wait(timeout=40)
        if outcome["error"] is not None:
            detail = (str(outcome["error"]).strip().splitlines() or [type(outcome["error"]).__name__])[0][:250]
            return {"status": "error",
                    "message": f"Non sono riuscito ad aprire la finestra del browser: {detail}"}
        return {
            "status": "success", 
            "message": f"Finestra di login aperta per {self.PROVIDERS[provider]['name']}. Accedi con il tuo account, poi chiudi la finestra del browser per salvare la sessione!"
        }

    GOOGLE_REJECTED = "accounts.google.com/v3/signin/rejected"

    def _login_window_open(self, provider: str) -> bool:
        t = self._login_threads.get(provider)
        return bool(t and t.is_alive())

    def _launch_error_message(self, provider: str, err: str) -> str:
        if self._login_window_open(provider):
            return "La finestra di login è ancora aperta. Chiudila per salvare e rilasciare il profilo!"
        return f"Impossibile avviare il browser del profilo: {err.strip().splitlines()[0][:200]}"

    def check_login_status(self, provider: str) -> Dict[str, Any]:
        """
        Opens a headless check. `logged_in` is True only when the chat input is present
        AND the page shows no login button / is not redirected to a login page
        (Gemini and ChatGPT show the chat box to guests too).
        """
        if provider not in self.PROVIDERS:
            return {"logged_in": False, "message": "Provider sconosciuto"}
        if provider in self.MANUAL_ONLY:
            # no automated visit: those sites reject automated browsers anyway
            return {"logged_in": False, "provider": provider, "state": "manual",
                    "message": f"{self.PROVIDERS[provider]['name']}: uso manuale. Usa «Copia & Decifra»."}
        if provider in self._notices:
            return {"logged_in": False, "provider": provider, "state": "blocked",
                    "message": self._notices[provider]}
        if self._login_window_open(provider):
            return {"logged_in": False, "provider": provider, "state": "login_open",
                    "message": "Finestra di login aperta: chiudila dopo l'accesso, poi ricontrolla."}

        profile_path = self.get_profile_path(provider)
        prov_info = self.PROVIDERS[provider]

        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                        **self._browser_kwargs(),
                    user_data_dir=profile_path,
                    headless=True,
                    args=[]
                )
                try:
                    page = context.new_page()
                    page.goto(prov_info["url"], wait_until="domcontentloaded", timeout=20000)
                    time.sleep(3)
                    has_input = page.query_selector(prov_info["check_selector"]) is not None
                    has_login_cta = page.query_selector(prov_info["logged_out_selector"]) is not None
                    on_login_page = any(k in page.url for k in ("/login", "/signin", "accounts.google.com"))
                    blocked = "__cf_chl" in page.url or "just a moment" in page.title().lower()
                finally:
                    context.close()
                if blocked:
                    return {"logged_in": False, "provider": provider, "state": "blocked",
                            "message": f"{prov_info['name']} blocca l'accesso automatico (verifica anti-bot): usa «Copia & Decifra»."}
                logged_in = has_input and not has_login_cta and not on_login_page
                return {
                    "logged_in": logged_in,
                    "provider": provider,
                    "state": "connected" if logged_in else "logged_out",
                    "message": "Account connesso" if logged_in else "Non connesso: usa «Accedi all'Account»"
                }
        except Exception as e:
            return {"logged_in": False, "provider": provider, "state": "error",
                    "message": self._launch_error_message(provider, str(e))}

    def execute_prompt(self, provider: str, masked_prompt: str, timeout_seconds: int = 90) -> Dict[str, Any]:
        """
        Injects the masked prompt into the user's active session, triggers generation,
        and retrieves the output text. Uses insert_text to adhere to Trusted Types CSP.
        """
        if provider not in self.PROVIDERS:
            return {"status": "error", "message": f"Provider non valido: {provider}"}

        if provider in self.MANUAL_ONLY:
            return {
                "status": "error",
                "message": f"{self.PROVIDERS[provider]['name']} non può essere pilotato automaticamente (verifica anti-bot)."
            }

        profile_path = self.get_profile_path(provider)
        prov_info = self.PROVIDERS[provider]

        with self._lock:
            try:
                with sync_playwright() as p:
                    context = p.chromium.launch_persistent_context(
                        **self._browser_kwargs(),
                        user_data_dir=profile_path,
                        headless=True,
                        args=[]
                    )
                    page = context.new_page()
                    page.goto(prov_info["url"], wait_until="domcontentloaded", timeout=25000)
                    time.sleep(3)

                    # Look for input area
                    input_elem = page.wait_for_selector(prov_info["prompt_selector"], timeout=15000)
                    if not input_elem:
                        context.close()
                        return {
                            "status": "error", 
                            "message": "Impossibile trovare la barra di inserimento. Assicurati di aver effettuato l'accesso all'account."
                        }

                    # Click and type using insert_text (immune to Google TrustedHTML restrictions)
                    input_elem.click()
                    time.sleep(0.4)
                    page.keyboard.insert_text(masked_prompt)
                    time.sleep(1)

                    # Click send button or press Enter
                    send_btn = page.query_selector(prov_info["send_selector"])
                    if send_btn and send_btn.is_enabled():
                        send_btn.click()
                    else:
                        input_elem.click()
                        page.keyboard.press("Enter")

                    # Wait for response completion
                    time.sleep(3)
                    start_time = time.time()
                    last_text = ""
                    stable_count = 0

                    while time.time() - start_time < timeout_seconds:
                        responses = page.query_selector_all(prov_info["response_selector"])
                        if responses:
                            curr_text = responses[-1].inner_text().strip()
                            if curr_text and curr_text == last_text:
                                stable_count += 1
                                if stable_count >= 3:
                                    context.close()
                                    return {"status": "success", "response": curr_text}
                            else:
                                stable_count = 0
                                last_text = curr_text
                        time.sleep(1)

                    context.close()
                    if last_text:
                        return {"status": "success", "response": last_text}
                    return {"status": "error", "message": "Timeout in attesa della risposta del modello."}

            except Exception as e:
                err_msg = str(e)
                if "Target page, context or browser has been closed" in err_msg:
                    return {"status": "error", "message": self._launch_error_message(provider, err_msg)}
                return {"status": "error", "message": f"Errore durante l'interazione con {prov_info['name']}: {err_msg}"}
