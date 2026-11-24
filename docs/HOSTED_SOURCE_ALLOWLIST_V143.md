# v1.43: hosted catalog defense against old API responses

The public GitHub Pages frontend may outlive a VPS backend release. The
existing browser check rejected hardcoded OLX/DIM.RIA labels but accepted
**any other source** when it carried two `verified` booleans. A stale or
misconfigured API could therefore show unapproved third-party inventory,
including unwanted photos or contact details.

The new browser acceptance gate:
- allows only the exact first-party label `Київ Радар (Пряма заявка)` or
  syntactically valid `partner:<source_key>`;
- still requires `actualityConfirmed === true` **and**
  `reviewedByRadar === true`;
- denies synthetic/imported records and any raw phone/name fields;
- denies partner contact hints, media, non-HTTPS original URLs, and URL
  embedded credentials (no partner photo republication consent is assumed);
- denies owner photos from hosts other than the moderated Kyiv Radar
  `/api/media/{32-char-photo-id}` endpoint.

This is **defense in depth**, not evidence of contractual consent.
An untrusted backend can still forge source keys and booleans. Actual
publication requires server-side reviewer+rights checks, a private
publication receipt and current listing verification.

The browser tests model an old backend returning false-verification flags
and unsafe fields. They do not fetch, publish or copy provider data.

Before a VPS deployment, verify that the front-end base URL and the
backend's `KYIV_RADAR_PUBLIC_API_BASE` agree, and repeat owner-photos,
partner-without-photos, empty catalog and outage UI smoke tests. Never
restore the archived 150 listings as fallback.

No provider API calls, paid services, private keys or production changes.
