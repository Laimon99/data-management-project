# ruff: noqa: E501
"""
TRIPADVISOR SCRAPER V11
===========================================================
Uno scraper professionale aggiornato con le correzioni del capitolato v11:
  - Debug della paginazione del primo loop tramite selettore data-smoke-attr.
  - Refactoring dello schema autore (rimozione residence ed estrazione nickname da href).
  - Temporizzazione asincrona randomica nativa (anti-bot) priva di time.sleep().
  - Mantenimento del sistema di checkpoint/resume.
"""

import argparse
import asyncio
import json
import os
import platform
import random
import shutil
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

# ============================================================================
# CONFIGURAZIONE COSTANTI
# ============================================================================

BASE_URL = "https://www.tripadvisor.it/Restaurants-g187849-Milan_Lombardy.html"

PACKAGE_DIR = Path(__file__).resolve().parent
BUNDLED_URL_FILE = PACKAGE_DIR / "tripadvisor_list_restaurant.txt"
DEFAULT_DATA_DIR = Path("data/raw/tripadvisor")

DATA_DIR = Path(os.environ.get("TRIPADVISOR_DATA_DIR", DEFAULT_DATA_DIR)).expanduser()
URL_FILE = Path(
    os.environ.get("TRIPADVISOR_URL_FILE", DATA_DIR / "tripadvisor_list_restaurant.txt")
).expanduser()
JSON_FILE = DATA_DIR / "tripadvisor_scraper_results.json"
CHECKPOINT_FILE = DATA_DIR / "tripadvisor_checkpoint.json"
OLD_USER_DATA_DIR = DATA_DIR / "brave_automation_profile"
USER_DATA_DIR = DATA_DIR / "browser_automation_profile"


def _windows_path(base_env, *parts):
    """Build a Windows candidate path, returning None when the base env var is empty."""
    base = os.environ.get(base_env, "")
    if not base:
        return None
    return Path(base).joinpath(*parts)


# Chromium-based browsers in detection priority order. Each entry maps the current
# OS to a list of hardcoded candidate executable paths, plus PATH executable names
# probed via shutil.which as a last resort.
CHROMIUM_BROWSERS = [
    {
        "name": "Brave",
        "paths": {
            "Darwin": [
                Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
                Path.home() / "Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            ],
            "Windows": [
                _windows_path("PROGRAMFILES", "BraveSoftware/Brave-Browser/Application/brave.exe"),
                _windows_path(
                    "PROGRAMFILES(X86)", "BraveSoftware/Brave-Browser/Application/brave.exe"
                ),
                Path.home() / "AppData/Local/BraveSoftware/Brave-Browser/Application/brave.exe",
            ],
            "Linux": [
                Path("/usr/bin/brave-browser"),
                Path("/usr/bin/brave"),
                Path("/opt/brave.com/brave/brave-browser"),
            ],
        },
        "which": ("brave-browser", "brave", "brave.exe"),
    },
    {
        "name": "Google Chrome",
        "paths": {
            "Darwin": [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            ],
            "Windows": [
                _windows_path("PROGRAMFILES", "Google/Chrome/Application/chrome.exe"),
                _windows_path("PROGRAMFILES(X86)", "Google/Chrome/Application/chrome.exe"),
                Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
            ],
            "Linux": [
                Path("/usr/bin/google-chrome"),
                Path("/usr/bin/google-chrome-stable"),
                Path("/opt/google/chrome/chrome"),
            ],
        },
        "which": ("google-chrome", "google-chrome-stable", "chrome", "chrome.exe"),
    },
    {
        "name": "Microsoft Edge",
        "paths": {
            "Darwin": [
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            ],
            "Windows": [
                _windows_path("PROGRAMFILES", "Microsoft/Edge/Application/msedge.exe"),
                _windows_path("PROGRAMFILES(X86)", "Microsoft/Edge/Application/msedge.exe"),
            ],
            "Linux": [
                Path("/usr/bin/microsoft-edge"),
                Path("/opt/microsoft/msedge/msedge"),
            ],
        },
        "which": ("microsoft-edge", "msedge", "msedge.exe"),
    },
    {
        "name": "Vivaldi",
        "paths": {
            "Darwin": [
                Path("/Applications/Vivaldi.app/Contents/MacOS/Vivaldi"),
            ],
            "Windows": [
                _windows_path("PROGRAMFILES", "Vivaldi/Application/vivaldi.exe"),
                _windows_path("PROGRAMFILES(X86)", "Vivaldi/Application/vivaldi.exe"),
                Path.home() / "AppData/Local/Vivaldi/Application/vivaldi.exe",
            ],
            "Linux": [
                Path("/usr/bin/vivaldi"),
                Path("/opt/vivaldi/vivaldi"),
            ],
        },
        "which": ("vivaldi", "vivaldi-stable", "vivaldi.exe"),
    },
    {
        "name": "Opera",
        "paths": {
            "Darwin": [
                Path("/Applications/Opera.app/Contents/MacOS/Opera"),
            ],
            "Windows": [
                Path.home() / "AppData/Local/Programs/Opera/opera.exe",
            ],
            "Linux": [
                Path("/usr/bin/opera"),
            ],
        },
        "which": ("opera", "opera.exe"),
    },
    {
        "name": "Chromium",
        "paths": {
            "Darwin": [
                Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            ],
            "Windows": [
                _windows_path("PROGRAMFILES", "Chromium/Application/chrome.exe"),
                _windows_path("PROGRAMFILES(X86)", "Chromium/Application/chrome.exe"),
            ],
            "Linux": [
                Path("/usr/bin/chromium"),
                Path("/usr/bin/chromium-browser"),
                Path("/snap/bin/chromium"),
            ],
        },
        "which": ("chromium", "chromium-browser", "chromium.exe"),
    },
]


def resolve_chromium_browser(browser_path_override=None):
    """Return an installed Chromium-based browser executable path for the current OS.

    Detection follows the priority order in CHROMIUM_BROWSERS: hardcoded per-OS
    paths first, then a shutil.which fallback. Returns None if nothing is found.
    """
    if browser_path_override:
        override_path = Path(browser_path_override).expanduser()
        if override_path.exists():
            return override_path
        raise FileNotFoundError(f"Percorso browser non trovato: {override_path}")

    system = platform.system()

    for browser in CHROMIUM_BROWSERS:
        for candidate in browser["paths"].get(system, []):
            if candidate is not None and candidate.exists():
                return candidate

    for browser in CHROMIUM_BROWSERS:
        for executable in browser["which"]:
            discovered = shutil.which(executable)
            if discovered:
                return Path(discovered)

    return None


def configure_runtime_paths(data_dir=None, url_file=None):
    """Configure runtime paths outside the importable source package."""
    global CHECKPOINT_FILE, DATA_DIR, JSON_FILE, OLD_USER_DATA_DIR, URL_FILE, USER_DATA_DIR

    if data_dir:
        DATA_DIR = Path(data_dir).expanduser()
    DATA_DIR = DATA_DIR.resolve()

    URL_FILE = Path(url_file).expanduser().resolve() if url_file else (DATA_DIR / URL_FILE.name)
    JSON_FILE = DATA_DIR / "tripadvisor_scraper_results.json"
    CHECKPOINT_FILE = DATA_DIR / "tripadvisor_checkpoint.json"
    OLD_USER_DATA_DIR = DATA_DIR / "brave_automation_profile"
    USER_DATA_DIR = DATA_DIR / "browser_automation_profile"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not URL_FILE.exists() and BUNDLED_URL_FILE.exists():
        shutil.copyfile(BUNDLED_URL_FILE, URL_FILE)

    migrate_profile_dir()


def migrate_profile_dir():
    """Rename the legacy brave_automation_profile/ to browser_automation_profile/.

    Preserves cookies/session state for users who ran the scraper before the
    rename. Only migrates when the old dir exists and the new one does not.
    """
    if OLD_USER_DATA_DIR.exists() and not USER_DATA_DIR.exists():
        shutil.move(str(OLD_USER_DATA_DIR), str(USER_DATA_DIR))
        print(f"[*] Profilo browser migrato: {OLD_USER_DATA_DIR.name} -> {USER_DATA_DIR.name}")


def order_urls(urls, scrape_order):
    """Return URLs in the requested teammate coordination order."""
    if scrape_order == "bottom":
        return list(reversed(urls))
    return list(urls)


def parse_args():
    default_order = os.environ.get("TRIPADVISOR_SCRAPE_ORDER", "top").lower()
    if default_order not in {"top", "bottom"}:
        default_order = "top"

    parser = argparse.ArgumentParser(description="TripAdvisor scraper v11")
    parser.add_argument(
        "--order",
        choices=("top", "bottom"),
        default=default_order,
        help="Ordine del secondo loop: 'top' dall'inizio lista, 'bottom' dalla fine lista.",
    )
    parser.add_argument(
        "--browser-path",
        default=os.environ.get("BROWSER_PATH", os.environ.get("BRAVE_PATH")),
        help=(
            "Percorso manuale del binario di un browser Chromium "
            "(Brave, Chrome, Edge, Vivaldi, Opera, Chromium), "
            "se il rilevamento automatico non funziona."
        ),
    )
    # Deprecated alias for --browser-path, kept so existing invocations keep working.
    parser.add_argument(
        "--brave-path",
        dest="brave_path",
        default=None,
        help="(deprecato) Alias di --browser-path; usa --browser-path.",
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("TRIPADVISOR_DATA_DIR"),
        help="Directory per URL, risultati, checkpoint e profilo browser.",
    )
    parser.add_argument(
        "--url-file",
        default=os.environ.get("TRIPADVISOR_URL_FILE"),
        help=(
            "File URL ristoranti da usare al posto di "
            "data/raw/tripadvisor/tripadvisor_list_restaurant.txt."
        ),
    )
    return parser.parse_args()


# ============================================================================
# FUNZIONI DI UTILITÀ E TEMPORIZZAZIONE UMANA (ANTIBAN)
# ============================================================================


async def async_input(prompt_text):
    """
    Gestisce l'input da terminale in modo asincrono senza bloccare Playwright.
    Utile per prompt all'utente durante l'esecuzione asincrona.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, input, prompt_text)


async def micro_reading_pause(page):
    """
    REGOLA 4 (CAPITOLATO): Simula il tempo di lettura dell'occhio umano tra una feature e l'altra.
    Intervallo: 340-1020 millisecondi con distribuzione casuale uniforme.
    """
    delay_ms = random.uniform(340, 1020)
    await page.wait_for_timeout(delay_ms)


async def pause_between_pages(page, description="pagina"):
    """
    REGOLA 1 e AGGIORNAMENTO V11: Pausa casuale lunga tra le pagine per evitare rilevamento anti-bot.
    Intervallo: 2.5-5 secondi per simulare comportamento umano. Utilizza esclusivamente wait_for_timeout.

    Args:
        page: Oggetto pagina di Playwright corrente.
        description: Descrizione dell'azione successiva (es. "ristorante", "pagina")
    """
    delay_ms = random.uniform(2500, 5000)
    print(
        f"   [⏳] Attesa strategica anti-bot ({delay_ms / 1000:.1f}s) prima di accedere alla prossima {description}..."
    )
    await page.wait_for_timeout(delay_ms)


async def human_scroll_slow(page):
    """
    REGOLA 3 (CAPITOLATO): Scorre la pagina a piccoli scatti di ~300px con pause di 0.85-1.7 secondi.
    Simula la lettura naturale di un utente che scorre lentamente la pagina.
    """
    print("   [~] Simulazione lettura umana lenta (scroll a scatti)...")
    steps = random.randint(3, 4)

    for step in range(steps):
        await page.evaluate("window.scrollBy(0, 300)")
        pause_ms = random.uniform(850, 1700)
        await page.wait_for_timeout(pause_ms)

    # Piccolo scroll verso l'alto per simulare un ripensamento umano
    if random.random() > 0.5:
        await page.evaluate("window.scrollBy(0, -150)")
        await page.wait_for_timeout(random.uniform(680, 1020))


async def check_and_handle_antibot(page):
    """
    Rileva schermate di blocco anti-bot e gestisce l'intervento umano.
    Emette un beep e mette in pausa fino a quando l'utente non risolve il captcha.
    """
    content = await page.content()

    antibot_keywords = [
        "Accesso è temporaneamente limitato",
        "Please verify you are a human",
        "velocità sovrumana",
        "captcha",
        "reCAPTCHA",
    ]

    if any(keyword.lower() in content.lower() for keyword in antibot_keywords):
        print("\a")  # Segnale acustico (BEEP) di sistema
        print("\n" + "=" * 80)
        print("[!!!] ATTENZIONE: RILEVATO BLOCCO ANTI-BOT DI TRIPADVISOR [!!!]")
        print("[!] Risolvi manualmente il CAPTCHA o il blocco nella finestra del browser.")
        print("[!] Una volta sbloccato, premi [INVIO] qui nel terminale per riprendere.")
        print("=" * 80)
        await async_input(">>> Premi [INVIO] per riprendere lo scraping...")
        await page.wait_for_timeout(random.uniform(1700, 3400))


async def safe_text(locator, default="NaN"):
    """
    Estrae il testo da un elemento DOM in modo sicuro.
    Ritorna 'NaN' se l'elemento non esiste o se il testo è vuoto.
    """
    try:
        if await locator.count() > 0:
            text = await locator.first.text_content(timeout=2500)
            return text.strip() if text else default
    except Exception:
        pass
    return default


async def safe_attr(locator, attr_name, default="NaN"):
    """
    Estrae un attributo HTML da un elemento DOM in modo sicuro.
    Ritorna 'NaN' se l'elemento o l'attributo non esiste.
    """
    try:
        if await locator.count() > 0:
            val = await locator.first.get_attribute(attr_name, timeout=2500)
            return val.strip() if val else default
    except Exception:
        pass
    return default


# ============================================================================
# SISTEMA DI CHECKPOINT E RESUME
# ============================================================================


def load_checkpoint():
    """
    Carica il file di checkpoint che traccia i progressi di scraping.
    Consente di riprendere l'esecuzione dopo un crash o blocco IP.
    """
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return create_empty_checkpoint()
    return create_empty_checkpoint()


def create_empty_checkpoint():
    """Crea una struttura di checkpoint vuota."""
    return {"processed_urls": [], "failed_urls": [], "last_update": datetime.now().isoformat()}


def save_checkpoint(checkpoint):
    """Salva il checkpoint su disco per tracciamento affidabile."""
    checkpoint["last_update"] = datetime.now().isoformat()
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)


def mark_url_processed(checkpoint, url):
    """Marca un URL come elaborato nel checkpoint."""
    if url not in checkpoint["processed_urls"]:
        checkpoint["processed_urls"].append(url)
    save_checkpoint(checkpoint)


def mark_url_failed(checkpoint, url):
    """Marca un URL come fallito nel checkpoint."""
    if url not in checkpoint["failed_urls"]:
        checkpoint["failed_urls"].append(url)
    save_checkpoint(checkpoint)


# ============================================================================
# PRIMO LOOP: ESTRAZIONE URL RISTORANTI CON PAGINAZIONE INTELLIGENTE
# ============================================================================


async def extract_restaurant_urls(page):
    """
    PRIMO LOOP - Estrae gli URL di tutti i ristoranti dalla pagina di listing di Milano.
    Implementa la correzione della paginazione avanzata tramite attributi esatti (Capitolato v11).
    """
    print("\n" + "=" * 80)
    print("--- PRIMO LOOP: ESTRAZIONE LINK RISTORANTI ---")
    print("=" * 80)

    await page.goto(BASE_URL, wait_until="domcontentloaded")

    print("\n[!] Pagina inizializzata sul browser.")
    print("[!] Accetta manualmente i cookie o chiudi i pop-up grafici nella finestra del browser.")
    await async_input(">>> Premi [INVIO] quando la pagina è pulita per iniziare...")

    pages_input = await async_input(
        ">>> Quante pagine vuoi scansionare? (Premi [INVIO] per scansionare TUTTE): "
    )
    pages_to_scrape = int(pages_input) if pages_input.strip().isdigit() else float("inf")
    print(
        f"[*] Obiettivo: scansionare {'TUTTE le pagine' if pages_to_scrape == float('inf') else f'{pages_to_scrape} pagina/e'}.\n"
    )

    current_page = 1
    extracted_urls = []

    if os.path.exists(URL_FILE):
        with open(URL_FILE, "r", encoding="utf-8") as f:
            extracted_urls = [line.strip() for line in f if line.strip()]
        print(f"[*] File {URL_FILE} già presente. Trovati {len(extracted_urls)} URL precedenti.\n")

    while current_page <= pages_to_scrape:
        print(f"\n[→] Scansione Pagina {current_page} in corso...")

        await check_and_handle_antibot(page)
        await human_scroll_slow(page)

        cards = page.locator('div[data-automation="restaurantCard"]')
        card_count = await cards.count()
        print(f"   [*] Rilevate {card_count} card ristorante su questa pagina.")

        urls_this_page = 0
        for i in range(card_count):
            card = cards.nth(i)
            link_locator = card.locator('a[href^="/Restaurant_Review-"]')

            if await link_locator.count() > 0:
                href = await link_locator.first.get_attribute("href")

                if href and "#REVIEWS" not in href:
                    full_url = f"https://www.tripadvisor.it{href}"

                    if full_url not in extracted_urls:
                        extracted_urls.append(full_url)
                        urls_this_page += 1

        with open(URL_FILE, "w", encoding="utf-8") as f:
            for url in extracted_urls:
                f.write(f"{url}\n")

        print(f"   [+] +{urls_this_page} nuovi URL estratti (Totale: {len(extracted_urls)})")

        if current_page >= pages_to_scrape:
            print(f"\n[✓] Raggiunto il limite di {pages_to_scrape} pagina/e richieste.")
            break

        # --- MODIFICA CORREZIONE PAGINAZIONE (CAPITOLATO V11) ---
        # Selettore esatto basato sui due attributi richiesti per la freccia "Avanti"
        next_button = page.locator(
            'a[data-smoke-attr="pagination-next-arrow"][aria-label="Pagina successiva"]'
        )
        next_button_count = await next_button.count()

        if next_button_count > 0:
            href_estratto = await next_button.first.get_attribute("href")
            if href_estratto:
                url_ricostruito = f"https://www.tripadvisor.it{href_estratto}"
                print(f"   [→] Prossima pagina individuata: {url_ricostruito}")

                # Applicazione del delay asincrono randomico (5-10s) prima della navigazione
                await pause_between_pages(page, "pagina")

                print(f"   [→] Navigazione diretta alla pagina {current_page + 1}...")
                await page.goto(url_ricostruito, wait_until="domcontentloaded")
                current_page += 1
            else:
                print(
                    "   [✗] Attributo href del pulsante 'Avanti' non valido o assente. Fine delle pagine."
                )
                break
        else:
            print(
                "   [✗] Pulsante 'Avanti' con gli attributi specificati non trovato. Siamo sull'ultima pagina."
            )
            break

    print(f"\n[✓] Primo loop completato. Estratti {len(extracted_urls)} URL totali.")
    print(f"[✓] URL salvati in: {URL_FILE}\n")


# ============================================================================
# SECONDO LOOP: ESTRAZIONE FEATURES STRUTTURATE CON NUOVO SCHEMA REVIEWS V11
# ============================================================================


async def extract_author_from_review(review_card):
    """
    Estrae il dizionario dell'autore di una recensione.

    Nuovo Schema Richiesto (Capitolato v11):
    {
        "nickname": "Isolato da attributo href",
        "number_of_contribution": "Numero di contributi"
    }
    Nota: La chiave 'residence' è stata completamente rimossa.
    """
    try:
        author_dict = {"nickname": "NaN", "number_of_contribution": "NaN"}

        # Estrazione nickname dall'attributo href (Invece del testo visibile)
        # Individua il tag <a> con target="_self" e href che inizia con /Profile/
        profile_link = review_card.locator('a[target="_self"][href^="/Profile/"]')
        if await profile_link.count() > 0:
            href = await profile_link.first.get_attribute("href")
            if href and "/Profile/" in href:
                # Isola il testo che appare subito dopo lo slash di /Profile/
                author_dict["nickname"] = href.split("/Profile/")[-1].strip()

        # Estrazione number_of_contribution da <span class="b">NN</span> contributi
        bold_spans = review_card.locator("span.b")
        if await bold_spans.count() > 0:
            for i in range(await bold_spans.count()):
                bold_text = await bold_spans.nth(i).text_content()
                if bold_text and bold_text.strip().isdigit():
                    parent_text = await review_card.text_content()
                    if "contributi" in parent_text.lower():
                        author_dict["number_of_contribution"] = bold_text.strip()
                        break

        return author_dict

    except Exception as e:
        print(f"   [!] Errore nell'estrazione dell'autore: {str(e)}")
        return "NaN"


async def extract_date_of_publication_from_review(review_card):
    """Estrae la data di pubblicazione della recensione."""
    try:
        date_elements = review_card.locator("text=/Scritta in data/")
        if await date_elements.count() > 0:
            raw_date = await date_elements.first.text_content()
            return raw_date.replace("Scritta in data", "").strip()

        all_divs = review_card.locator("div")
        div_count = await all_divs.count()
        for i in range(div_count):
            div_text = await all_divs.nth(i).text_content()
            if div_text and "Scritta in data" in div_text:
                return div_text.replace("Scritta in data", "").strip()

        return "NaN"
    except Exception as e:
        print(f"   [!] Errore nell'estrazione date_of_publication: {str(e)}")
        return "NaN"


async def extract_restaurant_features(page, url):
    """Estrae tutte le features strutturate di un singolo ristorante."""
    print(f"\n   [→] Navigazione: {url}")

    try:
        await page.goto(url, wait_until="domcontentloaded")
    except Exception as e:
        print(f"   [!] Errore nel navigare all'URL: {str(e)}")
        return None

    await check_and_handle_antibot(page)
    await human_scroll_slow(page)

    data = {
        "restaurant_name": "NaN",
        "rating": "NaN",
        "total_review": "NaN",
        "cuisine_type": "NaN",
        "price_range": "NaN",
        "number_photo_uploaded": "NaN",
        "address": "NaN",
        "website": "NaN",
        "phone_number": "NaN",
        "email": "NaN",
        "working_days_hours": "NaN",
        "review": "NaN",
    }

    # === FEATURE 1: restaurant_name ===
    data["restaurant_name"] = await safe_text(
        page.locator('div[data-test-target="restaurant-detail-info"] h1')
    )
    await micro_reading_pause(page)
    print(f"   [✓] Nome ristorante: {data['restaurant_name']}")

    # === FEATURE 2: rating ===
    data["rating"] = await safe_text(page.locator('div[data-automation="bubbleRatingValue"] span'))
    await micro_reading_pause(page)

    # === FEATURE 3: total_review ===
    data["total_review"] = await safe_text(
        page.locator('div[data-automation="bubbleReviewCount"] span')
    )
    await micro_reading_pause(page)

    # === FEATURE 4: cuisine_type ===
    try:
        cuisine_locators = page.locator(
            'div[data-test-target="restaurant-detail-info"] a[href*="/Restaurants-g187849-c"]'
        )
        cuisine_count = await cuisine_locators.count()
        cuisines = []
        for i in range(cuisine_count):
            c_text = await cuisine_locators.nth(i).text_content()
            if c_text:
                cuisines.append(c_text.strip())
        if cuisines:
            data["cuisine_type"] = ", ".join(cuisines)
    except Exception:
        pass
    await micro_reading_pause(page)

    # === FEATURE 5: price_range ===
    data["price_range"] = await safe_text(page.locator('a[href*="-zfp"] span'))
    await micro_reading_pause(page)

    # === FEATURE 6: number_photo_uploaded ===
    try:
        photo_btn = page.locator('button[data-automation="seeAllPhotosCountButton"] span')
        if await photo_btn.count() > 0:
            raw_text = await photo_btn.first.text_content()
            cleaned_num = "".join(filter(str.isdigit, raw_text))
            data["number_photo_uploaded"] = cleaned_num if cleaned_num else "NaN"
    except Exception:
        pass
    await micro_reading_pause(page)

    # === FEATURE 7: address ===
    data["address"] = await safe_text(
        page.locator('span[data-automation="restaurantsMapLinkOnName"]')
    )
    await micro_reading_pause(page)

    # === FEATURE 8: website ===
    website_href = await safe_attr(
        page.locator('a[data-automation="restaurantsWebsiteButton"]'), "href"
    )
    data["website"] = website_href if website_href != "NaN" else "NaN"
    await micro_reading_pause(page)

    # === FEATURE 9: phone_number ===
    phone_href = await safe_attr(page.locator('a[href^="tel:"]'), "href")
    if phone_href != "NaN":
        data["phone_number"] = phone_href.replace("tel:", "").strip()
    await micro_reading_pause(page)

    # === FEATURE 10: email ===
    email_href = await safe_attr(page.locator('a[href^="mailto:"]'), "href")
    if email_href != "NaN":
        data["email"] = email_href.replace("mailto:", "").split("?")[0].strip()
    await micro_reading_pause(page)

    # === FEATURE 11: working_days_hours ===
    try:
        hours_section = page.locator('div[data-automation="hours-section"] > div.f')
        hours_count = await hours_section.count()
        days_list = []
        for i in range(hours_count):
            day_row = hours_section.nth(i)
            day_name = await safe_text(day_row.locator("div.cGgaa"))

            hours_elements = day_row.locator("span.biGQs, div.biGQs._P")
            h_count = await hours_elements.count()
            hours_texts = []
            for j in range(h_count):
                ht = await hours_elements.nth(j).text_content()
                if ht and day_name not in ht:
                    hours_texts.append(ht.strip())

            hours_str = " and ".join([h for h in hours_texts if h]) if hours_texts else "Chiuso"
            if day_name != "NaN":
                days_list.append(f"{day_name}: {hours_str}")
        if days_list:
            data["working_days_hours"] = "; ".join(days_list)
    except Exception:
        pass
    await micro_reading_pause(page)

    # === FEATURE 12: review (SCHEMA AGGIORNATO V11 SENZA RESIDENCE) ===
    try:
        reviews_tab = page.locator('div[data-test-target="reviews-tab"]')
        if await reviews_tab.count() > 0:
            review_cards = reviews_tab.locator('div[data-automation="reviewCard"]')
            review_count = await review_cards.count()

            if review_count == 0:
                data["review"] = "NaN"
            else:
                reviews_list = []
                for i in range(review_count):
                    card = review_cards.nth(i)

                    author = await extract_author_from_review(card)
                    title = await safe_text(card.locator('h3[data-test-target="review-title"] a'))
                    text = await safe_text(card.locator('div[data-test-target="review-body"]'))
                    date_pub = await extract_date_of_publication_from_review(card)

                    review_obj = {
                        "author": author,
                        "title": title,
                        "text": text,
                        "date_of_publication": date_pub,
                    }
                    reviews_list.append(review_obj)

                data["review"] = reviews_list if reviews_list else "NaN"
        else:
            data["review"] = "NaN"
    except Exception as e:
        print(f"   [!] Errore nell'estrazione delle recensioni: {str(e)}")
        data["review"] = "NaN"

    await micro_reading_pause(page)
    return data


# ============================================================================
# FUNZIONE PRINCIPALE CON SISTEMA CHECKPOINT/RESUME
# ============================================================================


async def main(scrape_order="top", browser_path_override=None, data_dir=None, url_file=None):
    configure_runtime_paths(data_dir=data_dir, url_file=url_file)

    async with async_playwright() as p:
        print("\n" + "=" * 80)
        print("[*] TRIPADVISOR SCRAPER V11 - Avviamento con Correzioni Capitolato")
        print("=" * 80)
        print(f"[*] Directory package: {PACKAGE_DIR}")
        print(f"[*] Directory dati: {DATA_DIR}")
        print(f"[*] File URL: {URL_FILE}")
        print(f"[*] Directory Profilo Isolata: {USER_DATA_DIR}")

        browser_path = resolve_chromium_browser(browser_path_override)
        if browser_path:
            print(f"[*] Browser rilevato: {browser_path}\n")
        else:
            print(
                "[!] Nessun browser Chromium trovato. "
                "Uso il browser Chromium gestito da Playwright.\n"
            )

        launch_options = {
            "user_data_dir": str(USER_DATA_DIR),
            "headless": False,
            "viewport": {"width": 1280, "height": 800},
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
        }
        if browser_path:
            launch_options["executable_path"] = str(browser_path)

        context = await p.chromium.launch_persistent_context(**launch_options)

        page = context.pages[0] if context.pages else await context.new_page()

        # ====== PRIMO LOOP: ESTRAZIONE URL ======
        if not os.path.exists(URL_FILE):
            print(f"[*] File {URL_FILE} non trovato. Avvio PRIMO LOOP...")
            await extract_restaurant_urls(page)
        else:
            print(f"[+] File {URL_FILE} già presente. Salto primo loop.")
            with open(URL_FILE, "r", encoding="utf-8") as f:
                existing_urls = [line.strip() for line in f if line.strip()]
            print(f"[+] Trovati {len(existing_urls)} URL precedentemente estratti.\n")

        # ====== SECONDO LOOP: SCRAPING FEATURES CON CHECKPOINT ======
        if os.path.exists(URL_FILE):
            print("\n" + "=" * 80)
            print("--- SECONDO LOOP: ESTRAZIONE FEATURES STRUTTURATE ---")
            print("=" * 80 + "\n")

            with open(URL_FILE, "r", encoding="utf-8") as f:
                all_urls = [line.strip() for line in f if line.strip()]

            print(f"[*] Totale URL da scrapare: {len(all_urls)}\n")
            if scrape_order == "bottom":
                ordered_urls = order_urls(all_urls, scrape_order)
                print("[*] Ordine scraping: dal fondo della lista verso l'inizio.")
            else:
                ordered_urls = order_urls(all_urls, scrape_order)
                print("[*] Ordine scraping: dall'inizio della lista verso il fondo.")

            checkpoint = load_checkpoint()
            processed = checkpoint["processed_urls"]
            failed = checkpoint["failed_urls"]

            print("[*] Checkpoint caricato:")
            print(f"    - URL già elaborati: {len(processed)}")
            print(f"    - URL falliti: {len(failed)}\n")

            urls_to_scrape = [url for url in ordered_urls if url not in processed]

            if not urls_to_scrape:
                print("[✓] Tutti gli URL sono già stati elaborati! Nulla da scrapare.\n")
                await context.close()
                return

            print(f"[*] URL rimanenti da scrapare: {len(urls_to_scrape)}\n")

            results = []
            if os.path.exists(JSON_FILE):
                try:
                    with open(JSON_FILE, "r", encoding="utf-8") as jf:
                        results = json.load(jf)
                    print(f"[+] File {JSON_FILE} caricato: {len(results)} record precedenti.\n")
                except json.JSONDecodeError:
                    results = []

            for idx, url in enumerate(urls_to_scrape, 1):
                print(f"\n[{idx}/{len(urls_to_scrape)}] Processing: {url}")

                # Pausa casuale lunga (5-10s) prima dell'apertura del nuovo ristorante
                await pause_between_pages(page, "ristorante")

                try:
                    restaurant_data = await extract_restaurant_features(page, url)

                    if restaurant_data:
                        results.append(restaurant_data)

                        with open(JSON_FILE, "w", encoding="utf-8") as jf:
                            json.dump(results, jf, ensure_ascii=False, indent=2)

                        mark_url_processed(checkpoint, url)
                        rest_name = restaurant_data.get("restaurant_name", "Unknown")
                        print(f"   [✓] '{rest_name}' salvato. (Tot: {len(results)})")
                    else:
                        mark_url_failed(checkpoint, url)
                        print("   [!] Estrazione fallita per URL.")

                except Exception as e:
                    print(f"   [!] Errore critico durante lo scraping: {str(e)}")
                    mark_url_failed(checkpoint, url)
                    print("   [!] URL segnato come fallito nel checkpoint.")
                    continue

            print("\n" + "=" * 80)
            print("[✓] SECONDO LOOP COMPLETATO")
            print("=" * 80)
            print(f"[✓] Record estratti: {len(results)}")
            print(f"[✓] Risultati salvati in: {JSON_FILE}")
            print(f"[✓] Checkpoint salvato in: {CHECKPOINT_FILE}\n")
        else:
            print("[!] Nessun URL disponibile. Impossibile procedere con secondo loop.\n")

        await context.close()
        print("[✓] Browser chiuso. Scraping completato.\n")


def resolve_browser_path_override(args):
    """Combine --browser-path / legacy --brave-path, warning on the deprecated alias."""
    if args.brave_path:
        print(
            "[!] --brave-path è deprecato; usa --browser-path. "
            "L'alias continua a funzionare per ora.",
            file=sys.stderr,
        )
        return args.browser_path or args.brave_path
    return args.browser_path


def run_cli():
    try:
        args = parse_args()
        asyncio.run(
            main(
                scrape_order=args.order,
                browser_path_override=resolve_browser_path_override(args),
                data_dir=args.data_dir,
                url_file=args.url_file,
            )
        )
    except KeyboardInterrupt:
        print("\n\n[!] Interruzione dell'utente rilevata.")
        print("[!] Lo script si arresterà. Il checkpoint ha salvato i progressi.\n")
    except Exception as e:
        print(f"\n[!!!] Errore critico non gestito: {str(e)}\n")


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    run_cli()
