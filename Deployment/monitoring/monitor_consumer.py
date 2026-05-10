from __future__ import annotations
import argparse
import json
import logging

from monitoring_agent_jsonl import MonitoringAgent
from shared_jsonl_bus import JSONLBus
from workflow_engine import WorkflowEngine
from workflow_engine_gnn_v2 import WorkflowEngineGNNV2

logger = logging.getLogger("MonitorConsumer")


def main() -> None:
    parser = argparse.ArgumentParser(description="Consommateur monitoring depuis JSONL bus")
    parser.add_argument("--bus-file", default="network_stream.jsonl")
    parser.add_argument("--events-file", default="monitoring_events.jsonl")
    parser.add_argument("--actions-file", default="workflow_actions.jsonl")
    parser.add_argument(
        "--start-at-end",
        action="store_true",
        help="ignore l'historique et écoute seulement les nouveaux messages"
    )
    parser.add_argument("--window-size", type=int, default=5)
    parser.add_argument("--warning-escalation-count", type=int, default=3)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    bus = JSONLBus(args.bus_file)
    agent = MonitoringAgent(
        window_size=args.window_size,
        warning_escalation_count=args.warning_escalation_count,
    )

    engine = WorkflowEngine()
    engine_gnn = WorkflowEngineGNNV2()

    logger.info("Consommateur lancé. Lecture depuis %s", args.bus_file)

    for raw in bus.tail(start_at_end=args.start_at_end):
        try:
            event = agent.process_row(raw)

            action_v1 = engine.route_event(event)
            action_v2 = engine_gnn.route_event(event)

            with open(args.events_file, "a", encoding="utf-8") as f_evt:
                f_evt.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

            with open(args.actions_file, "a", encoding="utf-8") as f_act:
                f_act.write(
                    json.dumps(
                        {
                            "version": "v1",
                            "action": action_v1,
                        },
                        ensure_ascii=False,
                        default=str,
                    ) + "\n"
                )

                f_act.write(
                    json.dumps(
                        {
                            "version": "v2_gnn",
                            "action": action_v2,
                        },
                        ensure_ascii=False,
                        default=str,
                    ) + "\n"
                )

            print("\n=== EVENT ===")
            print(json.dumps(event, indent=2, ensure_ascii=False, default=str))

            print("=== ACTION V1 ===")
            print(json.dumps(action_v1, indent=2, ensure_ascii=False, default=str))

            print("=== ACTION V2 GNN ===")
            print(json.dumps(action_v2, indent=2, ensure_ascii=False, default=str))

        except KeyboardInterrupt:
            logger.info("Arrêt manuel du consommateur.")
            break
        except Exception as exc:
            logger.exception("Erreur consommateur: %s", exc)


if __name__ == "__main__":
    main()