# Native Aria deployment

Source: cai5232/murmur at 6ef1900c13c9ab90aeb6befce2dc1d908ee4b87b.
Original authors: fishisfish0614 (Fish 小鱼) and Keyan (克衍).
License: CC BY-NC-SA 4.0, preserved in LICENSE.

This deployment uses the complete, unmodified Aria example character configuration.
There is no Flask server, MCP server, legacy route adapter, ntfy loop, or old state import.

Added deployment changes:

- runtime.py secures the native API with the existing internal bearer token and
  existing dashboard Basic credentials. /health is the only unauthenticated endpoint.
  / redirects to FastAPI's own /docs, rather than the old Flask dashboard.
- Real outreach and presence signals are wired into the native unanswered mechanism.
  /emotion/outreach accepts the timestamp of a committed outgoing contact;
  /emotion/presence accepts an actual device-activity timestamp. Missing signals
  never count as the user ignoring a message.
- Native emotion updates accept an optional event_id. The last 10,000 IDs are
  persisted alongside state so retries do not double-apply a delta or moved spike.
- Fixed carry restoration after a graceful goodbye, and treating a running snapshot
  as interrupted on an unclean restart.
- History limits and session-end/source input values are validated.

## Runtime

Build using Dockerfile. Run exactly one worker, with a persistent volume at /app/data.
config.yaml is copied from config.example.yaml at build time. Container timezone is
America/New_York; absence time windows use that timezone. Keep the existing credentials
in the deployment platform; never commit them.

Lumi calls /emotion/* with its existing MURMUR_INTERNAL_TOKEN. It supplies deltas from
the selected chat model using the complete conversation context, refreshes presence
for actual user turns, and injects the engine's current inclinations before model calls.
Goodnight performs a graceful snapshot, keeps worry/upset at or above 0.3, restores
the next session, and enables the engine's goodnight mode. Service shutdown writes
an interrupted snapshot through the upstream lifespan handler.

The old volume must remain archived separately. It is not mounted as /app/data.
Do not point old clients at this API expecting drives/arc/regret/memory/activate.
Clients must use the native dimensions/state/vitals/history/session endpoints.

## Tests

In an isolated image with httpx installed:

    python -m unittest discover -s tests -v

Tests cover dynamics, real-time decay, absence, goodnight, unanswered signals,
session carry/reset, restart idempotency, moved/vitals, and authentication.
