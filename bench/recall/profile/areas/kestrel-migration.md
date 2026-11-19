---
name: kestrel-migration
description: Kestrel, the big project at work, moving rate quotes out of the monolith into their own service
---
- [stated] Kestrel is the rewrite of the rate-quote service, out of the Python monolith and into a standalone Go service
- [stated] Wren is tech lead; work started in June 2026 and the target cutover is 9 March 2027
- [stated] Storage moves from MySQL 5.7 to Postgres 16; the dual-write phase began in October 2026
- [stated] p99 latency target is 120 ms; the old code path sits around 410 ms
- [stated] The cutover feature flag is named quote_router_v2
- [stated] Design doc was reviewed by Tomasz; his main worry was cache invalidation when fuel surcharges update
- [stated] Shadow traffic showed a 0.3% mismatch rate, traced to rounding: the old code used banker's rounding and the new code rounded half up (2026-10-27)
- [stated] Cache is Valkey, replacing an old Memcached cluster
- [stated] Rollback plan is to flip the flag off and replay from the Kafka topic quotes.requested
