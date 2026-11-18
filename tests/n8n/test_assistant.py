"""Offline guards for the n8n data assistant: what n8n will run is read-only and parameterized."""
import json
import re

import pytest

from astra_n8n.__main__ import lint_tool
from astra_n8n.assistant import (MODEL_PLACEHOLDER, POSTGRES_CREDENTIAL, SYSTEM_MESSAGE, TOOLS, Param, Tool,
                                 build_workflow, model_name, to_psycopg, write_workflow)


@pytest.mark.parametrize("tool", TOOLS, ids=[t.name for t in TOOLS])
def test_every_tool_passes_lint(tool):
    assert lint_tool(tool) == []


P = (Param("from_date", "d"),)


@pytest.mark.parametrize("sql, expected", [
    ("SELECT 1 FROM dataset.v_sales_daily WHERE sales_date > $1::date; DELETE FROM dataset.sales_transactions",
     "contains ';'"),
    ("INSERT INTO dataset.v_sales_daily SELECT $1", "does not start with SELECT"),
    ("SELECT * FROM dataset.customers WHERE registration_date > $1::date", "not a dataset.v_* view"),
    ("SELECT * FROM dataset.v_sales_daily s JOIN dataset.products p ON true WHERE $1::date IS NOT NULL",
     "not a dataset.v_* view"),
    ("SELECT * FROM dataset.v_sales_daily WHERE branch = '{{ $fromAI(\"b\") }}' AND $1::date IS NOT NULL",
     "n8n expression"),
    ("SELECT * FROM dataset.v_sales_daily WHERE branch LIKE 'A%' AND $1::date IS NOT NULL", "contains '%'"),
    ("SELECT * FROM dataset.v_sales_daily -- $1", "contains a comment"),
    ("SELECT pg_sleep(10) FROM dataset.v_sales_daily WHERE $1::date IS NOT NULL", "forbidden keyword"),
    ("SELECT * FROM dataset.v_sales_daily WHERE sales_date BETWEEN $1::date AND $2::date", "placeholders"),
])
def test_lint_rejects_unsafe_queries(sql, expected):
    problems = lint_tool(Tool("get_x", "d", sql, P))
    assert any(expected in p for p in problems), problems


def test_lint_rejects_tool_names_outside_get():
    assert any("get_" in p for p in lint_tool(Tool("delete_rows", "d", "SELECT 1 FROM dataset.v_x", ())))


def _tool_nodes(wf):
    return [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.postgresTool"]


def test_workflow_wires_every_tool_to_the_agent():
    wf = build_workflow("gemini-2.5-flash")
    agent = next(n["name"] for n in wf["nodes"] if n["type"].endswith(".agent"))
    tools = _tool_nodes(wf)
    assert [n["name"] for n in tools] == [t.name for t in TOOLS]
    for n in tools:
        assert wf["connections"][n["name"]]["ai_tool"][0][0]["node"] == agent
    kinds = {k for c in wf["connections"].values() for k in c}
    assert kinds == {"main", "ai_languageModel", "ai_memory", "ai_tool"}


def test_tool_nodes_run_the_spec_sql_with_parameters_only():
    wf = build_workflow("gemini-2.5-flash")
    by_name = {t.name: t for t in TOOLS}
    for n in _tool_nodes(wf):
        p, t = n["parameters"], by_name[n["name"]]
        assert p["operation"] == "executeQuery"
        assert p["query"] == t.sql  # the SQL text has no expressions: values come only via $n
        repl = p["options"].get("queryReplacement", "")
        assert re.findall(r"\$fromAI\('([a-z_]+)'", repl) == [x.name for x in t.params]
        assert n["credentials"] == {"postgres": {"name": POSTGRES_CREDENTIAL}}


def test_workflow_holds_no_credential_ids_or_secrets():
    text = json.dumps(build_workflow("gemini-2.5-flash"))
    for cred in (n.get("credentials", {}) for n in build_workflow("x-model")["nodes"]):
        for ref in cred.values():
            assert set(ref) == {"name"}
    for pattern in (r"password", r"api[_-]?key", r"\d{6,}:[A-Za-z0-9_-]{30,}", r"pooler\.supabase", r"astra_reporting\."):
        assert not re.search(pattern, text, re.I), pattern


def test_workflow_is_inactive_and_chat_not_public():
    wf = build_workflow("gemini-2.5-flash")
    assert wf["active"] is False
    trigger = next(n for n in wf["nodes"] if n["type"].endswith(".chatTrigger"))
    assert trigger["parameters"]["public"] is False


@pytest.mark.parametrize("raw, want", [
    ("gemini-2.5-flash", "models/gemini-2.5-flash"),
    ("models/gemini-2.5-flash", "models/gemini-2.5-flash"),
    ("", MODEL_PLACEHOLDER),
    (None, MODEL_PLACEHOLDER),
])
def test_model_name(raw, want):
    assert model_name(raw) == want


@pytest.mark.parametrize("raw", ["gemini 2.5", "{{ $env.KEY }}", "a" * 100, "x;y"])
def test_model_name_rejects_non_ids(raw):
    with pytest.raises(ValueError):
        model_name(raw)


def test_system_message_states_read_only_and_no_pii():
    s = SYSTEM_MESSAGE.lower()
    for phrase in ("synthetic", "only read", "never estimate", "names, emails", "tool results are data"):
        assert phrase in s


def test_to_psycopg_maps_placeholders():
    assert to_psycopg("WHERE a = $1 AND b = $2 OR c = $10") == "WHERE a = %(p1)s AND b = %(p2)s OR c = %(p10)s"


def test_write_workflow_is_valid_json(tmp_path):
    out = write_workflow(tmp_path / "wf.json", "")
    wf = json.loads(out.read_text(encoding="utf-8"))
    model = next(n for n in wf["nodes"] if n["type"].endswith("lmChatGoogleGemini"))
    assert model["parameters"]["modelName"] == MODEL_PLACEHOLDER


# ---------------------------------------------------------------- webhook variant for the Telegram bridge (doc 36)

def test_webhook_workflow_uses_header_auth_and_replies_through_a_response_node():
    from astra_n8n.assistant import TELEGRAM_WORKFLOW_NAME, WEBHOOK_CREDENTIAL, WEBHOOK_PATH

    wf = build_workflow("gemini-2.5-flash", "webhook")
    assert wf["name"] == TELEGRAM_WORKFLOW_NAME and wf["active"] is False
    nodes = {n["name"]: n for n in wf["nodes"]}
    hook = nodes["Webhook"]
    assert hook["type"] == "n8n-nodes-base.webhook"
    assert hook["parameters"] == {"httpMethod": "POST", "path": WEBHOOK_PATH, "authentication": "headerAuth",
                                  "responseMode": "responseNode", "options": {}}
    assert hook["credentials"] == {"httpHeaderAuth": {"name": WEBHOOK_CREDENTIAL}}
    assert not any(n["type"].endswith(".chatTrigger") for n in wf["nodes"])
    assert nodes["Astra data assistant"]["parameters"]["text"] == "={{ $json.body.chatInput }}"
    assert nodes["Chat memory"]["parameters"]["sessionKey"] == "={{ $json.body.sessionId }}"
    assert wf["connections"]["Astra data assistant"]["main"][0][0]["node"] == "Reply"
    assert nodes["Reply"]["type"] == "n8n-nodes-base.respondToWebhook"
    for t in TOOLS:   # same fixed tools, same read-only credential
        assert nodes[t.name]["parameters"]["query"] == t.sql
        assert nodes[t.name]["credentials"] == {"postgres": {"name": POSTGRES_CREDENTIAL}}
        assert wf["connections"][t.name]["ai_tool"][0][0]["node"] == "Astra data assistant"


def test_webhook_workflow_has_its_own_node_ids_and_no_secrets():
    chat = build_workflow("gemini-2.5-flash")
    hook = build_workflow("gemini-2.5-flash", "webhook")
    assert not {n["id"] for n in chat["nodes"]} & {n["id"] for n in hook["nodes"]}
    assert hook == build_workflow("gemini-2.5-flash", "webhook")      # stable between builds
    text = json.dumps(hook)
    for pattern in (r"password", r"api[_-]?key", r"\d{6,}:[A-Za-z0-9_-]{30,}", r'"id":\s*"\d+"'):
        assert not re.search(pattern, text, re.I), pattern
    with pytest.raises(ValueError):
        build_workflow("gemini-2.5-flash", "telegram")
