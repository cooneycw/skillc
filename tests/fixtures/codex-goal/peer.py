"""Scripted app-server 0.165.0 peer. No network, client binary or model."""

import json
import sys

MODE = sys.argv[1]
THREAD = "scripted-thread"
goal = None
initialized = False
ready = False
started = False


def send(value):
    print(json.dumps(value), flush=True)


def note(method, **params):
    send({"method": method, "params": params})


for line in sys.stdin:
    msg = json.loads(line)
    method, params = msg["method"], msg["params"]
    if method == "initialize":
        assert params["capabilities"]["experimentalApi"] is True
        initialized = True
        result = {"userAgent": "scripted-goal-peer/0.165.0"}
    elif method == "initialized":
        assert initialized
        ready = True
        continue
    else:
        assert ready
        if method == "thread/start":
            assert params["allowProviderModelFallback"] is False
            assert params["model"] == "scripted-model"
            assert params["config"]["features"] == {"goals": True, "step_model_switching": False}
            result = {"thread": {"id": THREAD}, "model": "scripted-model"}
            if MODE == "startup-model-change":
                result["model"] = "other-model"
        else:
            assert params["threadId"] == THREAD
            if method == "thread/goal/set":
                assert params["tokenBudget"] is None
                assert params["origin"] == "user"
                goal = {"threadId": THREAD, "objective": params.get("objective", goal["objective"] if goal else "").strip(),
                        "status": params["status"], "tokensUsed": 0, "timeUsedSeconds": 0,
                        "tokenBudget": None, "createdAt": 1, "updatedAt": 1}
                note("thread/goal/updated", threadId=THREAD, goal=goal)
                result = {"goal": goal}
            elif method == "thread/goal/clear":
                goal = None
                note("thread/goal/cleared", threadId=THREAD)
                result = {"cleared": True}
            elif method == "thread/goal/get":
                result = {"goal": goal}
            else:
                raise AssertionError(method)
    if MODE == "rpc-error" and method == "thread/goal/set":
        send({"id": msg["id"], "error": {"code": -1, "message": "scripted refusal"}})
    else:
        send({"id": msg["id"], "result": result})
    if method == "thread/goal/set" and not started and MODE != "rpc-error":
        started = True
        if MODE == "model-change":
            note("model/rerouted", threadId=THREAD, turnId="turn-1", fromModel="scripted-model",
                 toModel="other-model", reason="highRiskCyberActivity")
        if MODE == "foreign-thread":
            note("thread/goal/updated", threadId="foreign-thread", goal=goal)
        if MODE == "unsolicited-response":
            send({"id": 999, "result": {}})
        if MODE == "ordinary-turn":
            note("turn/completed", threadId=THREAD, turn={"id": "turn-1", "status": "completed"})
            continue
        goal["status"] = "usageLimited" if MODE == "usage-limit" else "complete"
        goal["tokensUsed"] = 5000
        goal["timeUsedSeconds"] = 2
        goal["updatedAt"] = 3
        if MODE == "enforced-budget":
            goal["tokenBudget"] = 100
        note("thread/goal/updated", threadId=THREAD, goal=goal)
