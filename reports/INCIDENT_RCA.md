# ShopSphere Incident RCA

**Incident window analyzed:** 2026-11-18 09:00-13:00 UTC  
**Environment:** Synthetic production simulation  
**Status:** Retrospective; causal attribution is limited to the evidence below.

## Executive Summary

Across 12,000 request records, 1,147 returned 5xx responses, a request-level rate of **9.5583%**. The first 5xx in the data is an isolated `TRANSIENT_FAILURE` at 09:02:32.440Z. The analyzer's sustained-elevation rule identifies **10:45 UTC** as the start of the sustained increase: 30 of 250 requests failed with 5xx (12.0%) in that five-minute interval, above the first-hour baseline of 1.6667% and the computed 4.5594% threshold. The worst interval was **12:00-12:05 UTC**, when 94 of 250 requests failed with 5xx (37.6%).

The records establish several concrete failure mechanisms, not one universal cause: a `PayBridge` payment-provider timeout in `us-east-1`, inventory reservation deadlocks, order-service database-pool exhaustion, and a `NULL_CUSTOMER_CONTEXT` exception associated with the `new-checkout-context` feature flag after `v2.8.0` first appears. Database-pool and context errors were also logged in the gateway as HTTP responses; those are propagated records, not additional unique failed requests.

The `v2.8.0` context exception is strong evidence of a version-related defect in that code path, but the available reports do not provide version-by-route-by-region error denominators. The rollout is also entangled with time and region. Therefore, the size of the version's overall regression is **not quantified**, and the release should not be treated as the sole cause of the incident.

## Customer Impact

- **12,000** request records across `us-east-1`, `eu-west-1`, and `ap-south-1` between 09:00:00.294Z and 12:59:58.468Z.
- **1,147 5xx requests (9.5583%)**. Distribution: 657 HTTP 500, 311 HTTP 503, and 179 HTTP 504.
- **588 4xx requests**: 201 HTTP 401 credential failures and 387 HTTP 409 inventory deadlocks. These are not 5xx server failures, though the 409s represent real checkout/cart conflicts.
- Endpoint latency p95 was **3,661.05 ms** for checkout overall and **4,179.2 ms** for checkout in `us-east-1`. Overall request p95/p99 were **1,921.05/4,115.01 ms**.
- The 12:00-12:05 peak affected all three regions: `us-east-1` 75/174 5xx (43.1%), `eu-west-1` 13/43 (30.2%), and `ap-south-1` 6/33 (18.2%).
- These are request counts, not counts of distinct people or completed/abandoned orders. The dataset does not establish a unique customer count or revenue impact.

## Incident Timeline

| UTC time | Finding | Evidence |
|---|---|---|
| 09:02:32.440 | First isolated 5xx in the request data. | `TRANSIENT_FAILURE`, `GET /api/v1/orders`, HTTP 500, 703 ms, `eu-west-1`, v2.7.3; trace `1de86a4d0a84c18238da2d843cc54515`. |
| 09:55:02-10:25:45 | Burst of failed login attempts and brute-force indicators. | 201 `auth.login.failed` / `AUTH_INVALID_CREDENTIALS` traces and 201 `security.brute_force_indicator` records across regions. The details/gateway client address is `198.51.100.77`; user agent is `python-requests/2.32`. |
| 10:45-10:50 | Sustained 5xx elevation begins; payment-provider timeouts dominate the initial `us-east-1` spike. | At 10:45, `us-east-1` has 30/157 5xx (19.1083%); other regions have zero 5xx in that bucket. Provider p95 is 4,529 ms in `us-east-1`, versus 97 ms in `eu-west-1` and 240 ms in `ap-south-1`. |
| 10:45:12.872 | Payment service reports the earliest failure in the sample checkout trace. | Trace `41f4a967518b03f200b3b941c8dda779`: `payment-service` logs `PAYMENT_PROVIDER_TIMEOUT`, HTTP 504, provider `PayBridge`, retry count 4, timeout 2,500 ms. Auth, cart, inventory, and order had logged success earlier in the same trace; gateway records the 504 at 10:45:17.578Z. |
| 11:05:09.470 | Inventory deadlock causes a 409 checkout response. | Trace `6b9e60b66c1e9473819d159144799ad4`: auth and cart log success, then `inventory-service` logs `INVENTORY_DEADLOCK` (`inventory-db`, lock wait 919 ms); gateway returns 409 at 11:05:10.393Z. |
| 11:25:00-11:30 | Database-pool exhaustion becomes a clear order-service failure mode, particularly in `us-east-1`. | At 11:25, order DB pool active connections are 30 in `us-east-1`, compared with 8 in `eu-west-1` and 19 in `ap-south-1`. In trace `857e4cedd63fdc92adcb140612736285`, order-service reports active/max 30/30 and 3,875 ms wait before gateway returns 503. |
| 11:45:01 | First `v2.8.0` request found in the request data, in `us-east-1`. | The version rollout overlaps the ongoing incident; first observed row is a successful order read, not itself a failure. |
| 11:45:17.800 | `NULL_CUSTOMER_CONTEXT` exception appears on the new context path. | Trace `724198908c1f0229b9ed1e1d7c15023b`: `auth-service` logs HTTP 500 and `CheckoutContextResolver.resolve:118`, with `feature_flag=new-checkout-context`; gateway returns the matching 500. The request is `v2.8.0`. |
| 12:00-12:05 | Highest overall 5xx interval. | 94/250 requests fail (37.6%); request p95 is 3,604.25 ms. Queue lag has fallen to 19/75/96 messages across US/EU/AP, while US gateway heap is 55.8%. |
| 12:45-12:50 | Request error rates have returned near baseline, while US gateway heap is high. | At 12:45, overall 5xx rate is 1.6%; `us-east-1` heap is 96%. This weakens heap utilization as an explanation for the earlier peak. |

The time-series chart is [error_timeline.png](../charts/error_timeline.png); it shows request-level rates, baseline, threshold, onset marker, and p95 latency. The ranked peak intervals are in [worst_intervals.csv](worst_intervals.csv).

## Affected Services

| Service | ERROR log entries | Unique error traces | Interpretation |
|---|---:|---:|---|
| api-gateway | 1,147 | 1,147 | Final HTTP error responses; often mirrors the originating service error. Do not count as a second request failure. |
| auth-service | 510 | 510 | Includes 460 `NULL_CUSTOMER_CONTEXT` ERROR traces. Failed-login events are separate WARN-level records (201 request traces). |
| inventory-service | 418 | 418 | Inventory deadlocks; 387 request-level 409s. |
| order-service | 332 | 332 | Database-pool failures; 311 request-level 503s. |
| payment-service | 192 | 192 | Payment-provider timeouts; 179 request-level 504s. |

Service-level counts overlap across traces. For example, an order-service 503 and its gateway 503 share a trace; summing service ERROR rows would overstate failed requests. The service/region breakdown is in [service_region_errors.csv](service_region_errors.csv), and the heatmap is [service_region_error_heatmap.png](../charts/service_region_error_heatmap.png).

## Confirmed Findings

1. **Payment path timeout (high confidence for the affected requests).** At 10:45, US provider p95 is 4,529 ms while the other region samples remain under 250 ms. The `PAYMENT_PROVIDER_TIMEOUT` trace records the downstream payment-service timeout and a later gateway 504. The logs identify PayBridge as the provider. They do not prove the external provider's underlying infrastructure cause.
2. **Inventory reservation deadlocks (high confidence for the affected 409 requests).** `INVENTORY_DEADLOCK` is recorded by `inventory-service` with the `inventory-db` lock wait and then appears in the gateway response. There are 387 request-level 409s across the incident.
3. **Order DB pool exhaustion (high confidence for the affected 503 requests).** The order service reports no available connection, a full 30/30 pool, and wait time; request data records 311 `DB_POOL_EXHAUSTED` 503s. The peak pool reading and clearest paired trace are in `us-east-1`. The underlying reason the pool filled (leak, long-held connections, concurrency, or capacity) is not established by these files.
4. **Context-resolution exception on v2.8.0 (high confidence as a failure mechanism; medium confidence as a deployment regression).** The exception stack and feature-flag name are explicit in the auth log and match the request/gateway trace. The code path is therefore implicated; the deployment's contribution to total incident impact is not isolated by the available version-stratified report.
5. **Gateway errors are largely propagated responses.** Gateway ERROR rows use `event=http.response`; the paired traces above show the downstream error first and the matching status/code at the gateway later.

## Contributing Factors and Hypotheses

- **Notification backlog:** metrics show queue lag in the thousands at 10:45-11:45, for example 6,256 messages in `us-east-1`, 3,361 in `eu-west-1`, and 3,343 in `ap-south-1` at 10:45. By 12:00 these readings are 19/75/96. This supports delayed asynchronous notifications as a parallel customer impact, not as the cause of synchronous 5xx responses. No per-order email delivery evidence is included here.
- **Authentication abuse:** 201 failed credential requests and 201 brute-force indicator logs are recorded from the same synthetic source address across all three regions. The address `198.51.100.77` is in a documentation-reserved range; do not treat it as a real-world block target. The logs support a simulated brute-force pattern, not a successful account compromise.
- **Memory pressure as a primary cause:** not supported by the time alignment. US heap is 55.8% at the 12:00 5xx peak and 96% at 12:45 when 5xx rates are near baseline. Heap may still warrant investigation, but these data do not establish it as the cause.
- **Single-cause outage:** not supported. Payment, inventory, DB pool, and context-resolution signatures differ by service, status, region, and time.
- **v2.8.0 overall regression magnitude:** not quantified. The reports do not include an error-rate table stratified jointly by version, endpoint, region, and time. Version rollout is entangled with `us-east-1` and the ongoing incident; the context exception is direct evidence for one defect, not proof that all later failures were caused by the release.

## Immediate Mitigation

- For payment: enable a bounded circuit breaker for PayBridge, cap retries with backoff/jitter, use idempotency keys, and route to an approved fallback payment path if available. Reconcile payment/order state before retrying customer transactions.
- For database pools: shed non-critical concurrency before pool saturation, inspect connection hold times/leaks, and raise pool capacity only after validating database capacity. Keep graceful, fast failure instead of long request waits.
- For inventory: limit/retry deadlock victims safely with idempotent reservation operations; avoid unbounded client retries that amplify lock contention.
- For context failures: disable the `new-checkout-context` flag or roll back the affected v2.8.0 path in the impacted region, then verify matched route-level error rates before wider redeployment.
- For authentication: apply rate limits across both source IP and account, add progressive challenges, and review affected accounts. Confirm the real client identity at the trusted edge before any IP block.
- For notifications: scale workers/consumers and drain backlog without making notification delivery synchronous with checkout.

## Permanent Fixes and Monitoring

- Add payment circuit breakers, retry budgets, provider-specific timeout histograms, and synthetic payment probes. Alert on provider p95 and request-level 504s by region/route.
- Instrument DB pool active/max, wait duration, checkout concurrency, and connection lifecycle; alert before saturation and test overload behavior.
- Fix inventory lock ordering/transaction scope; add deadlock stress tests and observable retry limits.
- Add regression tests for missing customer context, rollout canaries by region, a feature-flag kill switch, and automated rollback criteria based on version/route/region error-rate deltas.
- Keep request-level SLOs separate from log-event counts. Alert separately on gateway 5xx, 401/409 business/security outcomes, notification queue age/lag, and downstream dependency errors. Join traces to metrics on UTC five-minute bucket plus region for investigation, but use trace-level evidence for causal ordering.
- Populate real span and parent-span IDs: current data has zeroed span IDs, so the trace reconstruction here is timestamp-ordered rather than a reliable parent-child waterfall.

## Data Quality and Confidence

The request validation report found no missing/invalid timestamps, duplicate request trace IDs, invalid statuses, or invalid latencies/metric values. Request-level counts are the denominator; service logs can contain multiple entries per failed request. The source documentation describes the data as synthetic and spans as approximate. Quantitative impact is therefore limited to this four-hour simulation. No unique-customer, revenue, successful-payment reconciliation, or external provider health data is present.

Generated evidence reviewed: [summary.json](summary.json), [http_status.csv](http_status.csv), [error_codes.csv](error_codes.csv), [latency.csv](latency.csv), [time_windows.csv](time_windows.csv), [worst_intervals.csv](worst_intervals.csv), [onset_evidence.csv](onset_evidence.csv), [services.csv](services.csv), [log_error_codes.csv](log_error_codes.csv), [log_dimensions.csv](log_dimensions.csv), [service_region_errors.csv](service_region_errors.csv), and [validation.csv](validation.csv).