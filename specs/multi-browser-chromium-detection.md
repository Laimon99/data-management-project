# Spec for multi-browser-chromium-detection
branch: feature/multi-browser-chromium-detection

## Summary

The Tripadvisor scraper currently only auto-detects Brave Browser. Many contributors do not have Brave installed and must rely on Playwright's bundled Chromium, which offers weaker anti-bot fingerprinting. This feature extends browser detection to cover all common Chromium-based browsers — Google Chrome, Microsoft Edge, Vivaldi, Opera, and Chromium — across macOS, Windows, and Linux. If none are found, the scraper falls back gracefully to Playwright's bundled Chromium. The CLI argument and README documentation are updated to reflect the broadened support.

## Functional Requirements

- Rename `resolve_brave_path` to `resolve_chromium_browser` (or equivalent) and generalise it to detect any installed Chromium-based browser.
- Detection priority order: Brave → Google Chrome → Microsoft Edge → Vivaldi → Opera → Chromium.
- Candidate paths must be checked for all three supported OSes: macOS (Darwin), Windows, Linux.
- After exhausting hardcoded paths, fall back to `shutil.which` for each browser's known executable names.
- If no installed browser is found, fall back silently to Playwright's managed Chromium (existing behaviour).
- Rename the `--brave-path` CLI argument to `--browser-path`; keep `--brave-path` as a deprecated alias so existing invocations do not break.
- Rename the persistent browser profile directory from `brave_automation_profile/` to `browser_automation_profile/`.
- Update all user-facing print messages to say "browser" rather than "Brave".
- Update README: remove "Brave browser" from the Requirements section and replace with "any Chromium-based browser (Brave, Chrome, Edge, Vivaldi, Opera, or Chromium)".
- Update README scraper section to reflect `--browser-path` and the new detection behaviour.
- Update README data directory listing to show `browser_automation_profile/` instead of `brave_automation_profile/`.

## Possible Edge Cases

- User has multiple Chromium-based browsers installed; the first match in priority order is used without prompting.
- User passes a `--browser-path` pointing to a non-Chromium binary; Playwright will raise its own error — no special handling needed.
- Windows `PROGRAMFILES` or `PROGRAMFILES(X86)` env vars are empty strings; path construction must not crash.
- `shutil.which` returns a path the current user cannot execute (permissions); Playwright will surface the error.
- Existing users have a `brave_automation_profile/` directory; the renamed directory means a fresh profile is created on next run — cookies/session state is lost.
- Snap-installed Chromium on Linux lives at `/snap/bin/chromium`, not `/usr/bin/chromium`.

## Acceptance Criteria

- On a machine with Brave installed, the scraper launches Brave (no behavioural change).
- On a machine with only Chrome installed (no Brave), the scraper detects and launches Chrome.
- On a machine with no recognised browser, the scraper prints a clear fallback message and launches Playwright's bundled Chromium.
- Passing `--browser-path /path/to/chrome` uses that path regardless of auto-detection.
- Passing the legacy `--brave-path /path/to/brave` still works without error.
- The persistent profile directory is created as `browser_automation_profile/`.
- README no longer lists Brave as a hard requirement.
- All existing tests pass; new unit tests cover the detection priority and the `--brave-path` alias.

## Open Questions

- Should the deprecated `--brave-path` alias emit a deprecation warning to stderr, or stay silent? emit deprecation warning but still functional
- Should the profile directory migration (old `brave_automation_profile/` → new `browser_automation_profile/`) be handled automatically, or left to the user? - ideally automatically, all browsers should be functional and scraper should work

## Out of Scope

- Supporting non-Chromium browsers (Firefox, Safari, WebKit).
- Any changes to scraper logic, CAPTCHA handling, or output format.
- Docker/CI browser provisioning.

## Feature Testing Guidelines

Create or extend tests in `/tests` for the browser resolution logic:

- Test that `resolve_chromium_browser()` returns the first existing path from the candidate list (mock `Path.exists`).
- Test that `resolve_chromium_browser()` falls through to `shutil.which` when no hardcoded path exists (mock `shutil.which`).
- Test that `resolve_chromium_browser()` returns `None` when neither hardcoded paths nor `shutil.which` find anything.
- Test that passing a valid `--browser-path` override returns that path.
- Test that passing a non-existent `--browser-path` override raises `FileNotFoundError`.
- Test that the legacy `--brave-path` argument is accepted and forwarded correctly.
