# transform/common — shared transform helpers

Small helper module shared by the per-platform clean transforms
(`transform.google_clean`, `transform.tripadvisor_clean`, `transform.thefork_clean`).
Import path: `transform.common`.

## Contents

- `contacts.py` — contact-field normalization used before matching:
  - `normalize_phone(value)` — compact Italian phone numbers toward E.164 (prefixes bare
    `0…`/`3…` numbers with `+39`).
  - `normalize_website(value)` — strip scheme / `www.` / trailing slash so websites compare
    for equality.

These are deliberately dependency-free string helpers; keep them pure so the clean
transforms stay easy to unit-test.
