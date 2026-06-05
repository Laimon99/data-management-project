"""
Arricchisce un dataset JSON di ristoranti con latitudine e longitudine
utilizzando Nominatim (OpenStreetMap) tramite la libreria geopy — 100% gratuito.

Utilizzo:
    python geocode_restaurants.py                          # usa i path di default
    python geocode_restaurants.py input.json output.json   # path personalizzati

Requisiti:
    pip install geopy
"""

import json
import sys
import time
from collections import OrderedDict
from pathlib import Path

from geopy.exc import GeocoderServiceError, GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim

# ──────────────────────────────────────────────
# CONFIGURAZIONE
# ──────────────────────────────────────────────
INPUT_FILE  = "tripadvisor_scraper_results_notgeocoded.json"          # path del file JSON di input
OUTPUT_FILE = "tripadvisor_scraper_results_geocoded.json" # path del file JSON di output
DELAY_SECONDS = 1.2                      # ≥ 1 s obbligatorio per Nominatim (ToS)
TIMEOUT       = 10                       # timeout singola richiesta HTTP (secondi)
MAX_RETRIES   = 2                        # tentativi in caso di timeout/errore rete
USER_AGENT    = "restaurant_geocoder_milan_v1/1.0 (geocoding-script)"

NAN_VALUE = "NaN"  # valore sentinella usato sia in input che in output


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────

def is_nan(value) -> bool:
    """Restituisce True se il valore è assente, None o la stringa 'NaN'."""
    if value is None:
        return True
    return str(value).strip().lower() == "nan"


def reorder_with_coords(restaurant: dict, lat: str, lon: str) -> OrderedDict:
    """
    Ricostruisce il dizionario del ristorante inserendo latitude e longitude
    subito dopo la chiave 'address', preservando l'ordine di tutte le altre chiavi.
    """
    result = OrderedDict()
    for key, value in restaurant.items():
        result[key] = value
        if key == "address":
            result["latitude"]  = lat
            result["longitude"] = lon
    # Sicurezza: se 'address' non esistesse nel record, aggiunge in coda
    if "latitude" not in result:
        result["latitude"]  = lat
        result["longitude"] = lon
    return result


def geocode_address(geocoder: Nominatim, address: str) -> tuple[str, str]:
    """
    Esegue la richiesta di geocoding con retry su errori transitori.
    Restituisce una coppia (latitude, longitude) come stringhe, oppure (NaN, NaN).
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            location = geocoder.geocode(address, timeout=TIMEOUT)
            if location:
                return str(location.latitude), str(location.longitude)
            else:
                return NAN_VALUE, NAN_VALUE  # indirizzo non trovato
        except GeocoderTimedOut:
            print(f"  [WARN] Timeout (tentativo {attempt}/{MAX_RETRIES}) — '{address}'")
            if attempt < MAX_RETRIES:
                time.sleep(DELAY_SECONDS * attempt)  # back-off progressivo
        except (GeocoderServiceError, GeocoderUnavailable) as exc:
            print(f"  [WARN] Errore di rete (tentativo {attempt}/{MAX_RETRIES}): {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(DELAY_SECONDS * attempt)
        except Exception as exc:  # noqa: BLE001 — rete / parser imprevedibili
            print(f"  [ERR]  Eccezione imprevista: {exc}")
            break

    return NAN_VALUE, NAN_VALUE


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main(input_path: str, output_path: str) -> None:
    # 1. Lettura del file di input
    source = Path(input_path)
    if not source.exists():
        print(f"[ERRORE] File di input non trovato: {input_path}")
        sys.exit(1)

    with source.open(encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, list):
        print("[ERRORE] Il file JSON deve contenere un array di oggetti ristorante.")
        sys.exit(1)

    total = len(data)
    print(f"[INFO] Caricati {total} ristoranti da '{input_path}'")
    print(f"[INFO] Delay tra richieste: {DELAY_SECONDS} s  |  Timeout: {TIMEOUT} s\n")

    # 2. Inizializzazione geocoder
    geocoder = Nominatim(user_agent=USER_AGENT)

    # 3. Ciclo di geocoding
    enriched = []
    for idx, restaurant in enumerate(data, start=1):
        name    = restaurant.get("restaurant_name", f"<record #{idx}>")
        address = restaurant.get("address", NAN_VALUE)

        if is_nan(address):
            # Indirizzo assente o già NaN → skip rete, coordinate NaN
            lat, lon = NAN_VALUE, NAN_VALUE
            print(f"[{idx:>4}/{total}] [SKIP]     {name!r:45s} -> indirizzo NaN")
        else:
            lat, lon = geocode_address(geocoder, address)
            status = "OK" if lat != NAN_VALUE else "NOT FOUND"
            print(
                f"[{idx:>4}/{total}] [{status:<9}] {name!r:45s} "
                f"-> Lat: {lat}, Lon: {lon}"
            )
            # Rispetto del rate-limit Nominatim (1 req/s)
            time.sleep(DELAY_SECONDS)

        enriched.append(reorder_with_coords(restaurant, lat, lon))

    # 4. Scrittura del file di output
    dest = Path(output_path)
    with dest.open("w", encoding="utf-8") as fh:
        json.dump(enriched, fh, ensure_ascii=False, indent=4)

    # 5. Riepilogo finale
    found     = sum(1 for r in enriched if r.get("latitude")  != NAN_VALUE)
    not_found = sum(1 for r in enriched if r.get("latitude")  == NAN_VALUE
                                        and not is_nan(r.get("address", NAN_VALUE)))
    skipped   = sum(1 for r in enriched if is_nan(r.get("address", NAN_VALUE)))

    print("\n" + "─" * 60)
    print(f"[DONE]  File salvato in '{output_path}'")
    print(f"        ✔  Coordinate trovate : {found}")
    print(f"        ✘  Non trovate         : {not_found}")
    print(f"        ⊘  Saltati (addr NaN)  : {skipped}")
    print(f"        Totale                : {total}")
    print("─" * 60)


if __name__ == "__main__":
    # Argomenti opzionali da riga di comando
    _input  = sys.argv[1] if len(sys.argv) > 1 else INPUT_FILE
    _output = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_FILE
    main(_input, _output)