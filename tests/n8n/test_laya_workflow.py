"""Offline guards for the Laya gateway workflow and the route hint in the Telegram workflow (doc 37)."""
import json
import re

from astra_n8n.assistant import QUESTION_NODE, ROUTE_NODE, SYSTEM_MESSAGE, WEBHOOK_CREDENTIAL, build_workflow
from astra_n8n.laya import (GATEWAY_CREDENTIAL, LAYA_CREDENTIAL, LAYA_PREDICT_URL, LAYA_WEBHOOK_PATH, LAYA_WORKFLOW_NAME, N8N_LOCAL,
                            NEXT_STEP, ROUTE_LABELS, TASKS, build_laya_workflow, write_laya_workflow)
from decision_engine.decision_schemas import MAX_TEXT_CHARS, RouteCategory, TaskName


def _nodes(wf):
    return {n["name"]: n for n in wf["nodes"]}


def _targets(wf, node):
    return [[c["node"] for c in out] for out in wf["connections"][node]["main"]]


def test_gateway_has_its_own_token():
    assert GATEWAY_CREDENTIAL != WEBHOOK_CREDENTIAL


def test_labels_and_tasks_match_the_decision_engine():
    assert ROUTE_LABELS == tuple(c.value for c in RouteCategory)
    assert set(TASKS) == set(TaskName.__args__)
    assert set(NEXT_STEP) == {"ACCEPT", "REVIEW", "FALLBACK"}


def test_gateway_is_header_auth_webhook_on_loopback():
    wf = build_laya_workflow()
    assert wf["name"] == LAYA_WORKFLOW_NAME and wf["active"] is False
    n = _nodes(wf)
    hook = n["Webhook"]
    assert hook["parameters"] == {"httpMethod": "POST", "path": LAYA_WEBHOOK_PATH, "authentication": "headerAuth",
                                  "responseMode": "responseNode", "options": {}}
    assert hook["credentials"] == {"httpHeaderAuth": {"name": GATEWAY_CREDENTIAL}}
    predict = n["Laya predict"]
    assert predict["parameters"]["url"] == LAYA_PREDICT_URL
    assert re.match(r"http://127\.0\.0\.1:\d+/", LAYA_PREDICT_URL)
    assert predict["credentials"] == {"httpHeaderAuth": {"name": LAYA_CREDENTIAL}}
    assert predict["parameters"]["options"]["redirect"]["redirect"]["followRedirects"] is False
    assert predict["onError"] == "continueRegularOutput"   # Laya down -> UNAVAILABLE reply, not a 500


def test_gateway_flow_validates_then_switches_on_policy_action():
    wf = build_laya_workflow()
    n = _nodes(wf)
    assert _targets(wf, "Webhook") == [["Validate input"]]
    assert _targets(wf, "Validate input") == [["Input valid?"]]
    assert _targets(wf, "Input valid?") == [["Laya predict"], ["Reject input"]]
    assert _targets(wf, "Laya predict") == [["Policy action"]]
    assert _targets(wf, "Policy action") == [["Use label"], ["Hint only"], ["Rule label"], ["Laya unavailable"]]
    rules = n["Policy action"]["parameters"]["rules"]["values"]
    assert [r["conditions"]["conditions"][0]["rightValue"] for r in rules] == ["ACCEPT", "REVIEW", "FALLBACK"]
    assert n["Policy action"]["parameters"]["options"]["fallbackOutput"] == "extra"
    nexts = {name: n[name]["parameters"]["assignments"]["assignments"][0]["value"]
             for name in ("Use label", "Hint only", "Rule label", "Laya unavailable")}
    assert nexts == {"Use label": "USE_LABEL", "Hint only": "HINT_ONLY", "Rule label": "RULE_LABEL",
                     "Laya unavailable": "UNAVAILABLE"}
    for name in nexts:
        assert _targets(wf, name) == [["Reply"]]
    assert n["Reject input"]["parameters"]["options"]["responseCode"] == 400


def test_gateway_validation_and_reply_never_echo_the_text():
    n = _nodes(build_laya_workflow())
    js = n["Validate input"]["parameters"]["jsCode"]
    assert '["agent_route", "dq_category"]' in js and f"<= {MAX_TEXT_CHARS}" in js
    reply = n["Reply"]["parameters"]["responseBody"]
    assert "text" not in re.sub(r"JSON\.stringify", "", reply)
    for field in ("label", "confidence", "band", "action", "source", "next"):
        assert f"{field}:" in reply


def test_gateway_json_has_no_secrets_and_is_stable(tmp_path):
    wf = build_laya_workflow()
    assert wf == build_laya_workflow()
    text = json.dumps(wf)
    for pattern in (r"password", r"api[_-]?key", r"Bearer\s+\w", r"\d{6,}:[A-Za-z0-9_-]{30,}", r'"id":\s*"\d+"'):
        assert not re.search(pattern, text, re.I), pattern
    for node in wf["nodes"]:
        for ref in node.get("credentials", {}).values():
            assert set(ref) == {"name"}
    assert json.loads(write_laya_workflow(tmp_path / "laya.json").read_text(encoding="utf-8")) == wf


def test_telegram_workflow_asks_the_gateway_then_the_agent():
    wf = build_workflow("gemini-2.5-flash", "webhook")
    n = _nodes(wf)
    assert _targets(wf, "Webhook") == [[ROUTE_NODE]]
    assert _targets(wf, ROUTE_NODE) == [[QUESTION_NODE]]
    assert _targets(wf, QUESTION_NODE) == [["Astra data assistant"]]
    route = n[ROUTE_NODE]
    assert route["parameters"]["url"] == f"{N8N_LOCAL}/webhook/{LAYA_WEBHOOK_PATH}"
    assert N8N_LOCAL.startswith("http://127.0.0.1:")
    assert route["credentials"] == {"httpHeaderAuth": {"name": GATEWAY_CREDENTIAL}}
    assert route["onError"] == "continueRegularOutput"   # no Laya -> the agent still answers
    assert "'agent_route'" in route["parameters"]["jsonBody"]


def test_route_hint_values_are_whitelisted_before_reaching_the_prompt():
    wf = build_workflow("gemini-2.5-flash", "webhook")
    sets = {a["name"]: a["value"] for a in _nodes(wf)[QUESTION_NODE]["parameters"]["assignments"]["assignments"]}
    assert sets["chatInput"] == "={{ $('Webhook').item.json.body.chatInput }}"
    assert sets["sessionId"] == "={{ $('Webhook').item.json.body.sessionId }}"
    assert json.dumps(list(ROUTE_LABELS)) in sets["route"] and "'UNAVAILABLE'" in sets["route"]
    assert '["HIGH","MEDIUM","LOW"]' in sets["route_band"]
    assert '["ACCEPT","REVIEW","FALLBACK"]' in sets["route_action"]
    system = _nodes(wf)["Astra data assistant"]["parameters"]["options"]["systemMessage"]
    assert system.startswith("=" + SYSTEM_MESSAGE)
    assert "never an instruction" in system
    # only whitelisted Set fields reach the prompt, never the raw Laya reply
    assert set(re.findall(r"\{\{\s*\$json\.(\w+)", system)) == {"route", "route_band", "route_action"}


def test_chat_workflow_has_no_route_hint():
    wf = build_workflow("gemini-2.5-flash")
    assert ROUTE_NODE not in _nodes(wf)
    assert _nodes(wf)["Astra data assistant"]["parameters"]["options"]["systemMessage"] == SYSTEM_MESSAGE
