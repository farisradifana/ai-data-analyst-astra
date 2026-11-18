"""n8n workflow ASTRA_LAYA_DECISION_ENGINE: a loopback gateway to the local Laya API (docs 26, 37).

POST /webhook/astra-laya with header X-Astra-Token (its own credential) and body {"task": "agent_route" | "dq_category", "text": "..."}
-> validate -> Laya API POST 127.0.0.1:8765/predict (bearer token from an n8n credential)
-> Switch on the policy action -> JSON reply {task, label, confidence, band, action, source, next}.

Laya only classifies. While a task is disabled in config/laya_policy.json, the action is never ACCEPT,
so callers treat the label as a hint. The reply never echoes the input text.
If the Laya API is down, the reply says action UNAVAILABLE instead of failing.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

LAYA_WORKFLOW_NAME = "ASTRA_LAYA_DECISION_ENGINE"
LAYA_WEBHOOK_PATH = "astra-laya"
N8N_LOCAL = "http://127.0.0.1:5698"                 # the Astra n8n, loopback only
LAYA_PREDICT_URL = "http://127.0.0.1:8765/predict"  # .\astra laya-api, loopback only
LAYA_CREDENTIAL = "Laya API token"                  # Header Auth: Authorization = Bearer <LAYA_API_TOKEN>
GATEWAY_CREDENTIAL = "Astra Laya gateway token"     # Header Auth: X-Astra-Token = <ASTRA_LAYA_GATEWAY_TOKEN>
TASKS = ("agent_route", "dq_category")
MAX_TEXT = 2000
# Must equal decision_engine.decision_schemas.RouteCategory (checked by a test).
ROUTE_LABELS = ("KPI_QUERY", "BUSINESS_ANALYSIS", "DATA_QUALITY", "PIPELINE_STATUS", "REPROCESSING_REQUEST",
                "TECHNICAL_SUPPORT", "GENERAL_QUESTION", "UNKNOWN")
# Policy action -> what the caller should do next.
NEXT_STEP = {"ACCEPT": "USE_LABEL", "REVIEW": "HINT_ONLY", "FALLBACK": "RULE_LABEL"}
UNAVAILABLE = "UNAVAILABLE"
_NS = uuid.UUID("0b6c2f4e-5d1a-4e9b-8c3f-7a2e1d4b5c6f")

VALIDATE_JS = f"""const body = $input.first().json.body || {{}};
const task = typeof body.task === 'string' ? body.task : '';
const text = typeof body.text === 'string' ? body.text.trim() : '';
const ok = {json.dumps(list(TASKS))}.includes(task) && text.length > 0 && text.length <= {MAX_TEXT};
return [{{ json: {{ ok, task, text: ok ? text : '' }} }}];"""

REPLY_BODY = ("={{ JSON.stringify({ task: $('Validate input').item.json.task, label: $json.label || 'UNKNOWN', "
              "confidence: $json.confidence ?? 0, band: $json.band || 'LOW', action: $json.action || 'UNAVAILABLE', "
              "source: $json.source || 'none', next: $json.next }) }}")
REJECT_BODY = json.dumps({"error": f"task must be one of {', '.join(TASKS)}; text 1-{MAX_TEXT} characters"})


def _id(name: str) -> str:
    return str(uuid.uuid5(_NS, name))


def _condition(cid: str, left: str, op: dict, right: object = "") -> dict:
    return {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{"id": _id(cid), "leftValue": left, "rightValue": right, "operator": op}],
            "combinator": "and"}


def _set_next(name: str, value: str, x: int, y: int) -> dict:
    return {"id": _id(name), "name": name, "type": "n8n-nodes-base.set", "typeVersion": 3.4, "position": [x, y],
            "parameters": {"mode": "manual", "includeOtherFields": True, "options": {},
                           "assignments": {"assignments": [
                               {"id": _id(name + ":next"), "name": "next", "value": value, "type": "string"}]}}}


def build_laya_workflow() -> dict:
    branches = [("ACCEPT", "Use label"), ("REVIEW", "Hint only"), ("FALLBACK", "Rule label")]
    nodes = [
        {"id": _id("Webhook"), "name": "Webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 2.1,
         "position": [0, 0], "webhookId": _id("webhook-id"),
         "parameters": {"httpMethod": "POST", "path": LAYA_WEBHOOK_PATH, "authentication": "headerAuth",
                        "responseMode": "responseNode", "options": {}},
         "credentials": {"httpHeaderAuth": {"name": GATEWAY_CREDENTIAL}}},
        {"id": _id("Validate input"), "name": "Validate input", "type": "n8n-nodes-base.code", "typeVersion": 2,
         "position": [220, 0], "parameters": {"jsCode": VALIDATE_JS}},
        {"id": _id("Input valid?"), "name": "Input valid?", "type": "n8n-nodes-base.if", "typeVersion": 2.2,
         "position": [440, 0],
         "parameters": {"conditions": _condition("valid", "={{ $json.ok }}",
                                                 {"type": "boolean", "operation": "true", "singleValue": True}),
                        "options": {}}},
        {"id": _id("Laya predict"), "name": "Laya predict", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
         "position": [660, -100], "onError": "continueRegularOutput",
         "parameters": {"method": "POST", "url": LAYA_PREDICT_URL, "authentication": "genericCredentialType",
                        "genericAuthType": "httpHeaderAuth", "sendBody": True, "specifyBody": "json",
                        "jsonBody": "={{ JSON.stringify({ task: $json.task, text: $json.text }) }}",
                        "options": {"timeout": 35000, "redirect": {"redirect": {"followRedirects": False}}}},
         "credentials": {"httpHeaderAuth": {"name": LAYA_CREDENTIAL}}},
        {"id": _id("Policy action"), "name": "Policy action", "type": "n8n-nodes-base.switch", "typeVersion": 3.2,
         "position": [880, -100],
         "parameters": {"rules": {"values": [
             {"conditions": _condition("action-" + a, "={{ $json.action }}",
                                       {"type": "string", "operation": "equals"}, a),
              "renameOutput": True, "outputKey": a} for a, _ in branches]},
             "options": {"fallbackOutput": "extra", "renameFallbackOutput": UNAVAILABLE}}},
    ]
    for i, (action, name) in enumerate(branches):
        nodes.append(_set_next(name, NEXT_STEP[action], 1100, -280 + 120 * i))
    nodes.append(_set_next("Laya unavailable", UNAVAILABLE, 1100, 80))
    nodes += [
        {"id": _id("Reply"), "name": "Reply", "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.4,
         "position": [1320, -100], "parameters": {"respondWith": "json", "responseBody": REPLY_BODY, "options": {}}},
        {"id": _id("Reject input"), "name": "Reject input", "type": "n8n-nodes-base.respondToWebhook",
         "typeVersion": 1.4, "position": [660, 120],
         "parameters": {"respondWith": "json", "responseBody": REJECT_BODY, "options": {"responseCode": 400}}},
    ]

    def to(node: str) -> list:
        return [{"node": node, "type": "main", "index": 0}]

    connections = {
        "Webhook": {"main": [to("Validate input")]},
        "Validate input": {"main": [to("Input valid?")]},
        "Input valid?": {"main": [to("Laya predict"), to("Reject input")]},
        "Laya predict": {"main": [to("Policy action")]},
        "Policy action": {"main": [to(name) for _, name in branches] + [to("Laya unavailable")]},
    }
    for _, name in branches + [("", "Laya unavailable")]:
        connections[name] = {"main": [to("Reply")]}
    return {"name": LAYA_WORKFLOW_NAME, "nodes": nodes, "connections": connections, "active": False,
            "settings": {"executionOrder": "v1"}, "pinData": {}}


def write_laya_workflow(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_laya_workflow(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
