# Architecture

The browser renders a responsive Next.js workspace. Requests go to the same origin `/api/*`, routed to a Python FastAPI service on Vercel. SQLAlchemy manages PostgreSQL transactions; local development defaults to SQLite. Neon provides persistent production storage.

Each state refresh reads orders, products, workers, events and agent runs. All dashboard metrics are computed on the backend from these records. No external LLM is required. LangGraph compiles a directed execution graph of nine specialized services: intake, inventory, prioritization, allocation, picking, fulfillment, risk, replenishment and supervisor. Each service records structured inputs, outputs, duration and success/failure. A failure halts downstream graph execution.

The priority formula uses normalized 0–100 factors weighted 0.30 delivery urgency, 0.25 SLA risk, 0.15 customer priority, 0.10 age, 0.10 shipping and 0.10 readiness. Categories are Critical >=80, High >=60, Medium >=35 and Low otherwise. Each order stores the factors in its explanation. Overrides retain before/after values in events.

Allocation locks orders, inventory and workers within a transaction. A worker with an active picking/packing assignment is excluded. Stock reservation occurs only if all line quantities fit available-to-promise stock. Picking consumes stock and releases its reservations only after exact quantity verification. Cancellation releases reservations before closing an unpicked order.

The routing service deduplicates coordinates, computes a baseline, applies nearest-neighbor plus 2-opt, and never replaces the baseline with a longer route. Every unit is two meters. Estimated picking time assumes 70 meters/minute and 0.6 minutes/stop. It is an estimate, not a measured completion duration. Aisles are assumed open; physical obstacles are not modeled.

JWT sessions expire after one hour. Accounts store Argon2 hashes. Roles are enforced in the API. Demo tokens provide access to the shared synthetic workspace only while DEMO_MODE is enabled. Newly registered accounts are read-only Analysts. The admin bootstrap command creates a real privileged account with an interactively entered password. Warehouse Worker tokens cannot confirm shared-console fulfillment because identity-to-worker binding is not implemented; supervisor confirmation is required.
