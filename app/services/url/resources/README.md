# Offline root-TLD reference

`iana_tlds.txt` is an exact copy of IANA's
[alphabetical TLD list](https://data.iana.org/TLD/tlds-alpha-by-domain.txt),
version `2026111600`, retrieved on 17 November 2026 in Asia/Ho_Chi_Minh
(`2026-11-16T17:07:37Z`). It contains 1,436 entries. Its SHA-256 is
`0e880d2f2a359fa5e404dac1551c4cf9d68dbc5acd62d7c697e956140119f1f6`.
The [IANA Root Zone Database](https://www.iana.org/domains/root/db) provides the
registry context. Preserve the original header, case, ordering, and newlines.

The intake policy uses this snapshot only as a cue for recognizing a bare
domain inside text. A matching suffix does not establish that a host exists,
is registered, belongs to a particular organization, or is safe. This is not
the Public Suffix List and cannot identify registrable domain boundaries.
Private, reserved, newly delegated, and unsupported suffixes can be absent.
In particular, `.example`, `.test`, `.invalid`, and `.localhost` are not root
TLDs in this list. Do not add test-specific exceptions to the production list.

Requests read a locally cached, checksum-validated snapshot. They never fetch
the list, query DNS, or open a submitted URL. A missing or corrupt resource
raises a configuration error instead of silently relaxing the policy.

To update manually:

1. Download the list from the IANA source above outside request handling.
   Keep the retrieved bytes and retrieval metadata in a new evaluation folder.
2. Review the header, SHA-256, entry count, and additions/removals against the
   current snapshot. Investigate unexpected format or membership changes.
3. Replace `iana_tlds.txt` with the exact bytes. Update the header, version,
   checksum and count pins in `domain_reference.py`, this note, and the explicit
   snapshot-identity assertions in `tests/url/test_domain_reference.py` together.
4. Review changes to extraction decisions, run the domain-reference and intake
   regression tests, and register a new evaluation manifest before comparing
   results. Preserve earlier source/resource snapshots and evaluation runs.
5. Deploy the reviewed code and resource together and restart the application
   so the in-process cache uses the new pin. Never edit an old evaluation
   manifest or switch to a live update during an experiment.
