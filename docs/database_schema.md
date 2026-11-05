# Database schema

| Table | Purpose and relationships |
|---|---|
| users | Unique email, Argon2 password hash, name, access role |
| customers | Customer identity, shipping address, priority score |
| products | Unique SKU, stock, reserved count, reorder threshold, unit price, category, zone/aisle/rack/shelf/bin, coordinates |
| workers | Identity, role, skills, shift availability, completed task count, position |
| orders | Customer FK, status, deadline, shipping, score, risk, worker FK, route JSON, reservation flag, value, tracking, completion timestamp |
| order_items | Order FK, product FK, requested quantity |
| stock_movements | Product FK, signed quantity, reason, timestamp |
| events | Audit kind, message, optional order reference, actor, timestamp |
| agent_runs | Agent name, structured input/output JSON, success/failure, duration, timestamp |
| recommendations | Unique evidence key, title, description, impact, severity, decision state, optional product reference |

Initial tables are created by SQLAlchemy `Base.metadata.create_all`. The seed exits when products exist, avoiding duplicated initial data. Current schema changes require an explicit migration plan before release; `create_all` does not alter existing columns. Production uses PostgreSQL row locks. SQLite fallback does not provide equivalent multi-process row-level concurrency guarantees.
