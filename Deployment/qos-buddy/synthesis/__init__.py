"""QOS-Buddy synthesis agent.

Subscribes to qos.metrics.raw and publishes:
  • qos.alerts        — threshold/behavioral/forecast alerts
  • qos.diagnosis     — pattern + similar-incident matches
  • qos.insight       — Qwen2.5-generated NOC briefs
  • qos.action.proposed — playbook + safety checks + counterfactual
  • qos.jira.outbox   — populated ticket when verdict=DEFERRED
"""
