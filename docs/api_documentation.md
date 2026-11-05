# API reference

Interactive OpenAPI is available at `/api/docs`; JSON schema at `/api/openapi.json`.

All operational endpoints require `Authorization: Bearer <JWT>`. Health and authentication endpoints are public. Write operations check roles. Demo mode grants write access to synthetic records.

| Method | Route | Behavior |
|---|---|---|
| GET | /api/health | Database connectivity, storage type, orchestration status |
| POST | /api/auth/demo | Expiring shared-demo token if enabled |
| POST | /api/auth/register | Register a read-only Analyst |
| POST | /api/auth/login | Verify Argon2 credentials and issue JWT |
| GET | /api/auth/me | Authenticated identity |
| GET | /api/state | Operational records, trends, KPIs, events, agent runs |
| POST | /api/orders | Validate and create order with line items; run intake/inventory/scoring |
| GET | /api/orders/{id} | Items, progress, score, tracking and audit timeline |
| PATCH | /api/orders/{id} | Edit deadline and shipping |
| DELETE | /api/orders/{id} | Soft cancel before picked; release reservations |
| POST | /api/orders/{id}/advance | Explicit physical confirmation through fulfillment stages |
| POST | /api/orders/{id}/assign | Reassign an active picking task with conflict checks |
| POST | /api/orders/{id}/priority | Supervisor score override with recorded reason |
| POST | /api/agents/{name}/run | Execute named agent or `workflow`, with strategy |
| POST | /api/products | Add product |
| PATCH | /api/products/{id} | Edit inventory without invalidating reservations |
| DELETE | /api/products/{id} | Remove unused product; retain records with history |
| POST | /api/products/{id}/adjust | Signed adjustment and movement audit |
| GET | /api/products/{id}/movements | Product stock history |
| POST | /api/workers | Create worker |
| PATCH | /api/workers/{id} | Update name/role/skills/shift availability |
| PATCH | /api/recommendations/{id} | Acknowledge, dismiss or request replenishment |
| GET | /api/reports/orders.csv | CSV export with optional ISO `start` and `end` dates |

Order input example:

```json
{"customer_id":1,"shipping":"Express","deadline":"2027-01-01T12:00:00Z","items":[{"product_id":2,"quantity":3}]}
```

`advance` accepts `confirm_pick`, `start_pack`, `verify_pack`, `dispatch`, `ship`, `deliver`. Picking/packing confirmations require `quantities` exactly matching product IDs and requested counts. Invalid transitions return 409. Validation errors return 422; role failures 403; missing/invalid sessions 401. Shipment tracking is generated only when the ship transition succeeds.
