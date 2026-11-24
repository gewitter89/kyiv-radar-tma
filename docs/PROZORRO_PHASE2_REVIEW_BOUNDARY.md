# Phase 2: auction review boundary (issue #87)

- Existing index.html uses /api/deals for ordinary listings and telegram-shell.js for the Mini App. Those paths remain unchanged. Auctions are not ordinary property prices or comparables.
- Private pilot remains unchanged on VPS at release 065da97b. The new projection and preview are offline-only, not an endpoint.
- Gate defaults OFF. A trusted operator must establish source rights for the exact scope, record a private evidence ID and bounded validity interval, and separately approve each normalized content fingerprint. Changed price, VAT, deadline or link invalidates approval. Revocation, expiry, missing or stale data returns no item.
- The preview uses the exact gate and renders only whitelisted fields, without photos, contacts, provider documents, or raw data. It is responsive Ukrainian HTML, no scripts/network fetches. Source links are exact canonical HTTPS links. HTML is a snapshot, not safe for persistent public caching.
- The gate is a pure function, NOT a real rights/approval database, auth mechanism, or public publication authorization. Only trusted server code may supply inputs; never accept these maps or the enabled flag from a browser. No actual rights or approvals created by this PR.
- Next: operator-only authenticated approval storage with append-only revocation history; isolated transport of fresh approved metadata with server-enforced expiry and no public access to SQLite; verify rights for permitted display; integrate a disabled-by-default route/tab with existing navigation and test browser/Telegram flows. No public release until #86 scheduled tick and rollback confirmed and explicit release approval.
- Test data is synthetic; never publish it. No actual host changes or paid actions.
