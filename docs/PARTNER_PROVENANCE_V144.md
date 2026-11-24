# v1.44 — private-only provenance for partner listings (24.11.2026)

## Vulnerability
The API previously assembled a legacy JSON catalog and then filtered partner
items against a private rights database. If an operator accidentally included
a `partner:...` item in the legacy JSON, it could pass rights/reviewer checks
without being produced by the separate `publication_authorization` receipt
and private export path. A valid search/API key or source-level rights entry is
not permission for any arbitrary JSON row to be published.

## Fixed invariant
`load_trusted_deals()` now **discards all partner-marked rows from its
legacy JSON source before any reviewer step**. Partner marking includes
`partnerSourceKey`, `partnerExternalId`, or a `partner:` source label.
Non-dictionary entries are ignored. This also blocks disguised partner rows
whose public source label claims to be first-party.

Partner items are accepted only when BOTH private configuration paths exist
and `read_private_export(export_path, publication_authorization_path)`
returns them after its own rights/receipt/freshness/field-scope validation.
The existing read-time `enforce_partner_visibility()` must still succeed
for each item before the public API can return it.

A partner cannot reuse an already-present first-party listing ID.
No partner authorization is created by this change; an empty catalog is
valid and preferable to unlicensed content.

## Verification & release
Unit tests cover false `reviewed` claims in static JSON, forged source
markers, missing publication receipt, authorized staging and ID collisions.
Quality CI runs these tests. Production requires a separately reviewed VPS
release/backup and smoke tests on actual served API responses.

Do not move private contracts, tokens, reviewer evidence, user contacts or
full provider inventory into GitHub, Pages, CI fixtures or browser storage.
