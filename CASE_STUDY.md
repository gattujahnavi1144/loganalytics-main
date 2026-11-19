# Case study: The four-hour ShopSphere outage

## Your role
You are the newly hired SRE investigating a production incident. Senior leadership wants a data-backed assessment within one simulated incident review.

## Business context
ShopSphere operates an API-based online store in AWS us-east-1, eu-west-1, and ap-south-1. Services include API Gateway, Authentication, Catalog, Cart, Inventory, Orders, Payments, and Notifications. Requests can cross several dependencies and some events are processed asynchronously.

## Customer complaints
- At around 10:50 UTC, some customers begin reporting checkout timeouts.
- Several customers cannot reserve products despite seeing inventory in stock.
- Support notices a wave of login failures.
- At around noon UTC, order pages are intermittently unavailable.
- Customers with completed orders report delayed confirmation emails.
- A recently deployed application version is suspected, but teams disagree about whether it caused the entire incident.

## Investigation challenges
A naive count of `ERROR` lines gives misleading incidence estimates: one request can produce an ERROR in a service and another in the gateway. HTTP `401` and `409` need different treatment from 5xx. A `200` checkout response can still have a delayed notification afterward. Different regions and versions can exhibit different failure rates; deploy comparison should control for time and route.

## Required analyses
### Part A — Data validation
1. Validate missing timestamps, invalid statuses, duplicated `trace_id` values in the request-level dataset, and unusual outliers.
2. Calculate request-level status distribution and 5xx failure rate.
3. Find the 10 slowest requests and print their full distributed traces.

### Part B — Observability
4. Generate 5-minute charts: request volume, 5xx rate, p95 latency, and failures per endpoint.
5. Create service x error-code summary, and compare regional rates.
6. Match service errors to requests by `trace_id`; contrast log-event counts with affected unique requests.

### Part C — Incident diagnosis
7. Locate the suspected external payment degradation window and show evidence from payment spans and provider metric.
8. Explain inventory deadlocks, database-pool depletion, and how they compete with or mask payment failures.
9. Identify the high-frequency malicious login IP and decide on containment options, mindful of false positives.
10. Assess the post-rollout exception spike with version stratification, and propose rollback criteria.
11. Analyze worker queue lag and explain why it may not reflect customer-facing checkout errors.

### Part D — Engineering response
12. Produce a timeline with UTC timestamps and confidence levels.
13. Define remediation: circuit breakers/retries, connection pool controls, deadlock avoidance, auth rate limiting, rollback/feature flagging, and queue autoscaling.
14. Build six alert definitions (metric, threshold, window, severity, owner) and justify their noise controls.
15. Provide an executive summary with customer impact, caveats, and follow-up verification plan.

## Stretch goals
- Design a trace waterfall visual and a causal dependency map.
- Use anomaly detection such as rolling z-score, seasonal baselines or change-point detection.
- Calculate SLO error-budget burn with a *stated* SLO target, using only gateway 5xx events.
- Demonstrate Simpson's paradox risk from version/region/endpoint traffic differences.
- Write regression tests that verify the parsing and investigation scripts.
