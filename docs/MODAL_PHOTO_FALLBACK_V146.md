# v1.46 — photo failure is not a broken-image UI

## Evidence
Visual inspection of the **real CI synthetic screenshot** from Quality run
#45385569873 showed a black image panel and broken-image icon/alt text in the
390×844 property detail modal. This is a browser rendering defect, not
proof of actual source photo availability. Screenshots contain 150 explicitly
labeled TEST cards only, not live or approved property inventory.

## Fix
- On open or switch, show a consistent accessible, high-contrast loading
  fallback until the image reports positive natural width.
- On 404, aborted request, revoked owner photo URL, decode failure or
  missing image: hide the <img> element itself and show the readable text
  `Фото тимчасово недоступне` instead of the browser's broken-image icon.
- On a listing with zero authorized photos: show
  `Фотографій поки немає` and hide photo arrows/counter/dots.
- After the user switches to an available photo, restore it without
  retaining previous error overlays; stale load/error events cannot replace
  the newer photo.
- Keep navigation arrows/dots on individual failures to let people switch
  to any available photo. Maintain legible fallback in light theme.

The fallback does not make up or generate new photography, mask source
attribution or automatically show third-party unlicensed media.

## Validation
Isolated Playwright tests intercept synthetic image URLs, making one request
fail and another succeed, and cover recovery, switching back, light theme and
no-photo state. The broad Quality pipeline executes them; no network photo
downloads, provider requests, paid services or VPS deployments.
