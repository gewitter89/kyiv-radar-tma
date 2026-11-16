# Київ Радар — release acceptance and product launch

**Target release:** v1.5.0. **Current live version:** v1.4.0 until independently deployed.
The changes in this branch are not evidence of a successful production rollout.

## Product principles

1. Source is explicit: imported listings are labelled **Імпортовано / Джерело: OLX або DOM.RIA**. Do not describe them as owner-verified.
2. Truth before conversion: commission, ownership, contact verification, availability and autonomous utilities are *different* claims.
3. No fabricated reviews, ratings, property attributes, “verified” dates or savings calculations.
4. Essential paths: find listing → view photos → see uncertainty → request contact in Telegram; submit apartment → upload photos → moderation → publish.
5. User-facing language is natural Ukrainian, calm typography and spacing, no aggressive icons or fake scarcity.

## Security / operational acceptance

### Known unresolved risks

- **Bot token:** an earlier value appeared in public Git history. The owner explicitly requested no rotation yet. This risk remains OPEN; never represent it as resolved. Never paste it into issues, docs or logs.
- **Historical phone numbers:** the current catalog is masked, but earlier public commits may still be readable; current branch cannot undo already copied data.
- **Imported content:** source validity, use/republication rights, phone consent and listing actuality are not established merely by scraping a public page.
- **Public serving:** upload routes are protected by signed Telegram initData; do not expose upload directories as Caddy static files. Approved images are served only via `/api/media/{photo_id}`.
- **Proxy body limits:** verify the running Caddy version before using `request_body` (v2.10+); cap upload request bodies to 33 MB at reverse proxy when supported. Do not deploy an untested Caddyfile.
- **Image processing:** monitor disk, memory and the Pillow security release track; re-encoded WebP is safer but not a universal malware guarantee.

### Before deployment

1. Record running `main` SHA, app version, service status and Caddy version.
2. Back up SQLite including WAL using the SQLite backup API, rather than copying a running DB file, plus the catalog, media directory, protected contacts vault and service config. Check that the backup is readable.
3. Run the isolated Python/Playwright suite in PR CI; no external production writes.
4. Check compatibility of all new DB columns and `landlord_uploads` with the existing production database on a disposable copy. Confirm free space.
5. Install dependencies declared in `server/requirements.txt` including Pillow and python-multipart in the app virtual environment.
6. Schedule a controlled deploy with a rollback plan; do not touch `kyivpulse`, Vudstoria Monitor or other independent services.

### After deployment

- `GET /api/health` returns version `1.5.0`; `GET /api/deals` has no raw `phone` values.
- `GET /api/media/<nonexistent_id>` and `GET /api/media/<pending_id>` both return 404; only approved media returns `200 image/webp`.
- One trusted Telegram account uploads a photo with EXIF → sees preview → submits a listing → moderator receives its real private photos → approves → photo becomes accessible in the listing.
- Another Telegram user cannot attach the first user's upload or reuse an already submitted ID.
- Tapping the main **Отримати контакт** button delivers contact to the user's Telegram private chat. Unauthorized requests are rejected; missing contact does not produce a fictional number.
- Check CORS, no public `/uploads/` route, logging without secrets, rate limits under simultaneous requests.
- Manual smoke in iOS Telegram WebView, Android Telegram WebView, iPad/tablet and keyboard/mouse desktop.
- If a check fails: stop the pilot, inspect errors, use a controlled rollback. Schema/data rollback must be reconciled with any submissions accepted after deployment.

## Human QA checklist

| Scenario | Acceptance |
|---|---|
| Swipe gallery on phone/tablet | Left/right advances, vertical sheet scroll works, image counter accurate |
| Desktop navigation | Accessible left/right controls and keyboard arrows; proper focus |
| No-photo listing | No broken images or fictional photos |
| Internet unavailable | Clear actionable error, no fake contact success |
| Unverified imported listing | No claim of ownership, zero commission or independently confirmed utilities |
| Owner uploads files | Helpful max-size/type error; pending photos inaccessible publicly |
| Screen readers | Logical button labels; changing photo count announced |
| Slow connection | Prevent duplicate submits, show progress and recoverable error |

## Pilot (no fake endorsements)

**Audience:** 10–20 invited testers and 3–5 actual landlords who have explicitly agreed to participate. Invite privately first. No bulk or unsolicited messages.

**Metrics:** contact-delivery success, number of legitimate owner listings, moderator time-to-review, percentage of stale/reported listings, mobile loading stability, and return visits. Testers should know the catalog includes unverified imports.

**Suggested neutral invitation (Ukrainian):**

> Тестуємо «Київ Радар» — мапу оренди квартир у Києві. Є оголошення з відкритих джерел; їхня актуальність і комісія можуть бути не підтверджені. Шукаємо кількох учасників, які перевірять зручність пошуку, фото, фільтрів і отримання контактів у Telegram. Якщо помітите застаріле оголошення, повідомте через «Поскаржитися». Участь безкоштовна.

**Launch gate:** only after a successful real Telegram contact-delivery test and written review of the remaining security/token risk. No paid ads or mass campaign without separate owner approval.

## Design language

- Neutral dark surfaces, readable system typography, blue for navigation/action, green **only for facts confirmed by moderators**, orange for warnings.
- Minimum touch targets ~44px; clear contrast and focus states. Respect reduced-motion preferences.
- One primary CTA per screen; all labels describe what actually happens.
- No “AI-generated” boilerplate or claims of human authorship. Quality must come from real editorial review, truthful content and device testing.

## Sources

- OWASP File Upload Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html
- OWASP API Security Top 10: https://owasp.org/projects/api-security-project/
- W3C WAI carousels: https://www.w3.org/WAI/tutorials/carousels/
