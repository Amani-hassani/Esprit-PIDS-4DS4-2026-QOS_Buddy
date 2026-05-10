# QOS-Buddy — Qosmic NOC Command Center

Unified deployment shell for the 6 QOS-Buddy agents (monitoring, detection, prediction, diagnostic, optimization, reporting).

## Layout

```
qos-buddy/
├── contracts/         Pydantic v2 schemas + AsyncAPI spec — single source of truth
├── bus/               RedisStreamsBus + monitoring → Redis bridge (real data, no mocks)
├── gateway/           FastAPI + Socket.IO + RBAC + OIDC
├── shell/             Next.js 14 unified dashboard (Tailwind + shadcn + Lucide)
├── infra/             docker volumes, Keycloak realm export
└── docker-compose.yml Single-laptop tuned stack
```

The 6 agent folders sit at the project root and stay where they are. This folder
sits beside them and integrates them.

## Quickstart (local)

```bash
docker compose up -d redis postgres
docker compose up monitoring-bridge gateway shell
```

## Roles

- **NOC Executive** — light theme default, approve/reject actions, autonomy sliders, no jargon
- **AI Engineer** — dark theme default, raw artifacts, model controls, technical view

## Hardware target

Single Windows laptop, 16 GB RAM recommended. LLM calls use the host's local Ollama service with `qwen2.5:latest`.

## Data is always real

The monitoring agent's `network_stream.jsonl` (60+ live fields per sample) is bridged
into Redis Streams as the source of truth. No fixtures, no mocks, no demo seeds in the
default boot path.
