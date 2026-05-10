# QOS-Buddy — First-Boot Run-book

A single laptop, no mocks. The path is:

```
monitoring agent  →  network_stream.jsonl  →  monitoring-bridge  →  Redis Streams
                                                                         │
                                                                         ▼
                                                                     gateway
                                                                         │
                                                                         ▼
                                                                Next.js dashboard
```

## 1 · Start the live data source

Open a terminal in the project root and start the existing monitoring agent so
it begins writing real samples to `monitoring/network_stream.jsonl`.

```powershell
# from "PI-integration - Copy"
cd monitoring

# Quick start (host metrics, ping/iperf3 against a public target):
python qos_buddy_collector.py --duration 0 --interval 5

# With a router gateway (Huawei 4G/5G example):
python qos_buddy_collector.py --router-gateway 192.168.8.1 --duration 0
```

`--duration 0` means "run until interrupted". Leave this terminal open during
the demo. The bridge tails the JSONL file in real time.

## 2 · Bring up the stack

```powershell
cd qos-buddy
docker compose up -d
```

First boot pulls and builds Docker images. LLM calls use the host computer's
local Ollama service at `localhost:11434`, exposed to containers as
`host.docker.internal:11434`. Make sure `qwen2.5:latest` is installed locally.

Watch the live data flow:

```powershell
docker compose logs -f monitoring-bridge gateway
```

You should see lines like:

```
qos-monitoring-bridge | bridge starting jsonl=/data/network_stream.jsonl
qos-monitoring-bridge | redis bus connected url=redis://redis:6379/0
qos-gateway           | gateway up streams=6
```

## 3 · Open the dashboard

| Service           | URL                                                      |
| ----------------- | -------------------------------------------------------- |
| Dashboard         | http://localhost:3000                                    |
| Gateway health    | http://localhost:8080/healthz                            |
| Keycloak admin    | http://localhost:8081 (admin / admin)                    |
| Keycloak account  | http://localhost:8081/realms/qos-buddy/account            |

## 4 · Demo accounts

The Keycloak realm is imported on first boot from
`infra/keycloak/qos-buddy-realm.json`.

| Username    | Password | Role             | Default theme |
| ----------- | -------- | ---------------- | ------------- |
| `noc-exec`  | `demo`   | NOC Executive    | Light         |
| `engineer`  | `demo`   | AI Engineer      | Dark          |
| `admin-noc` | `demo`   | Site Admin       | Dark          |

Sign-in goes through Keycloak — the dashboard hands you off, you authenticate,
and you come back with a real token. The role badge in the topbar shows what
the gateway authorized.

## 5 · Verify the live path

Once you're signed in:

1. The connection pill in the topbar reads **Live**.
2. The four KPI tiles show real numbers from the monitoring agent (latency,
   delay variation, packet loss, throughput) and update every few seconds.
3. The chart fills with a rolling window of samples.
4. The pipeline diagram lights "Observe" because metrics are flowing.

If you see the empty state "Waiting for live samples…", the monitoring agent
isn't producing yet — go back to step 1 and confirm it's writing to
`monitoring/network_stream.jsonl`.

## 6 · Tearing down

```powershell
docker compose down              # keep volumes
docker compose down -v           # remove all Docker data (Keycloak users, DBs, traces, etc.)
```

## 7 · Common issues

| Symptom                                  | Fix                                                                                   |
| ---------------------------------------- | ------------------------------------------------------------------------------------- |
| LLM summaries are unavailable            | Start local Ollama on the host and confirm `ollama list` shows `qwen2.5:latest`.      |
| Keycloak shows error after login         | The redirect URI in `qos-buddy-realm.json` must match the dashboard origin.            |
| Dashboard shows "Sign in required" loop  | Browser blocked third-party cookies. Use the same hostname (localhost) for both apps.  |
| KPI tiles stay empty                     | Monitoring agent isn't running, or the bridge can't see `network_stream.jsonl`.        |

## 8 · What is not yet wired (W2 scope)

These pages currently show a "wired in the next iteration" stub. The data
backbone is live; the views are next:

- Detection & Forecast (live feature view + forecast chart)
- Diagnostic (similar-incident map + lesson library)
- Optimization (action queue + safety checks + autonomy sliders)
- Reporting (PDF + audio brief + embedded engineer view)
- Audit Log (hash-chained ledger)
- Scenario Lab (chaos injector)

The Command Center page is real and live.
