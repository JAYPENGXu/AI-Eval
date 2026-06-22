from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, TypedDict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
try:
    from langgraph.graph import END, StateGraph
    from langgraph.types import Command, interrupt
except ImportError:
    END = "__end__"
    StateGraph = None
    Command = None

    def interrupt(value):  # type: ignore[misc]
        return value

from rag.agent.actions import execute_agent_action
from rag.model_usage import elapsed_ms, extract_usage, record_model_call
from rag.experiments import create_experiment_action, create_experiment_plan
from rag.access_control import filter_knowledge_bases_for_user, filter_traces_for_user, require_capability
from rag.models import KnowledgeBase, RagAgentAction, RagEvalCaseResult, RagEvalRun, RagTrace
from rag.services import get_openai_client

from .checkpointing import get_agent_checkpointer
from .tools import TOOL_REGISTRY

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    user_id: int
    kb_id: int | None
    trace_id: int | None
    eval_run_id: int | None
    compare_eval_run_id: int | None
    message: str
    thread_id: str
    thread_business_key: str
    thread_metadata: dict
    plan: list[dict]
    tool_calls: list[dict]
    tool_results: list[dict]
    action_cards: list[dict]
    human_decisions: list[dict]
    human_response: dict
    execution_results: list[dict]
    diagnosis: dict
    experiment_plan: dict | None
    workflow_intent: str
    answer: str
    status: str


AVAILABLE_TOOLS = [
    {
        "name": "get_trace_detail",
        "description": "读取一条 RAG Trace 的问题、改写、检索、重排、压缩、答案和 Prompt 摘要。",
        "args": {"trace_id": "int"},
    },
    {
        "name": "compare_eval_runs",
        "description": "对比两个 RAG 评测 Run 的指标、参数和 case 正确性变化。",
        "args": {"left_run_id": "int", "right_run_id": "int"},
    },
    {
        "name": "get_model_usage_summary",
        "description": "读取当前知识库或单条 Trace 的模型调用次数、token、成本、慢请求和失败请求。",
        "args": {"kb_id": "int|null", "trace_id": "int|null"},
    },
]


def graph_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def get_thread_snapshot(graph, thread_id: str):
    if not thread_id:
        return None
    try:
        return graph.get_state(graph_config(thread_id))
    except Exception:
        logger.exception("failed to read agent thread snapshot thread_id=%s", thread_id)
        return None


def is_thread_interrupted(snapshot) -> bool:
    return bool(snapshot and snapshot.next)


def assert_thread_owner(snapshot, user) -> None:
    values = snapshot.values if snapshot else {}
    metadata = (values or {}).get("thread_metadata") or {}
    owner_id = metadata.get("user_id")
    if owner_id is not None and owner_id != user.id:
        raise PermissionError("Agent thread does not belong to the current user.")


def serialize_agent_result(state: AgentState, *, thread_id: str, thread_business_key: str, snapshot=None) -> dict:
    interrupted = is_thread_interrupted(snapshot)
    status = "interrupted" if interrupted else "completed"
    answer = state.get("answer", "")
    if interrupted and not answer:
        answer = build_pre_hitl_summary(state)
    return {
        "status": status,
        "awaiting_human": interrupted or bool(state.get("awaiting_human")),
        "answer": answer,
        "plan": state.get("plan", []),
        "tool_calls": state.get("tool_calls", []),
        "tool_results": state.get("tool_results", []),
        "action_cards": state.get("action_cards", []),
        "human_response": state.get("human_response") or {},
        "execution_results": state.get("execution_results") or [],
        "diagnosis": state.get("diagnosis", {}),
        "experiment_plan": state.get("experiment_plan"),
        "workflow_intent": state.get("workflow_intent", ""),
        "thread_id": state.get("thread_id", thread_id),
        "thread_business_key": state.get("thread_business_key", thread_business_key),
    }


def authorize_agent_context(user, values: dict) -> None:
    kb_id = values.get("kb_id")
    trace_id = values.get("trace_id")
    eval_run_id = values.get("eval_run_id")
    compare_id = values.get("compare_eval_run_id")
    allowed_kbs = filter_knowledge_bases_for_user(user, capability="use_agent")
    if kb_id:
        kb = allowed_kbs.filter(id=kb_id).first()
        if not kb:
            raise PermissionError("Agent knowledge base access denied.")
        require_capability(user, "use_agent", kb=kb)
    if trace_id and not filter_traces_for_user(user, RagTrace.objects.filter(id=trace_id)).exists():
        raise PermissionError("Agent Trace access denied.")
    for run_id in (eval_run_id, compare_id):
        if run_id and not RagEvalRun.objects.filter(id=run_id, kb_id__in=allowed_kbs.values("id")).exists():
            raise PermissionError("Agent Eval Run access denied.")


def run_ragops_agent(
    *,
    user,
    message: str,
    kb_id: int | None = None,
    trace_id: int | None = None,
    eval_run_id: int | None = None,
    compare_eval_run_id: int | None = None,
    thread_id: str = "",
    thread_business_key: str = "",
) -> dict:
    if not thread_id:
        raise ValueError("thread_id is required for RAGOps Agent runs.")
    authorize_agent_context(user, {"kb_id": kb_id, "trace_id": trace_id, "eval_run_id": eval_run_id, "compare_eval_run_id": compare_eval_run_id})

    graph = build_graph()
    config = graph_config(thread_id)
    snapshot = get_thread_snapshot(graph, thread_id)
    if snapshot and snapshot.values:
        assert_thread_owner(snapshot, user)
        if is_thread_interrupted(snapshot):
            return serialize_agent_result(snapshot.values, thread_id=thread_id, thread_business_key=thread_business_key, snapshot=snapshot)

    thread_metadata = {
        "thread_id": thread_id,
        "business_key": thread_business_key,
        "user_id": user.id,
        "kb_id": kb_id,
        "trace_id": trace_id,
        "eval_run_id": eval_run_id,
        "compare_eval_run_id": compare_eval_run_id,
    }
    initial_state: AgentState = {
        "user_id": user.id,
        "message": message,
        "kb_id": kb_id,
        "trace_id": trace_id,
        "eval_run_id": eval_run_id,
        "compare_eval_run_id": compare_eval_run_id,
        "workflow_intent": "",
        "plan": [],
        "tool_calls": [],
        "tool_results": [],
        "human_decisions": [],
        "human_response": {},
        "execution_results": [],
        "action_cards": [],
        "thread_id": thread_id,
        "thread_business_key": thread_business_key,
        "thread_metadata": thread_metadata,
        "status": "running",
        "awaiting_human": False,
    }
    state = graph.invoke(initial_state, config=config)
    snapshot = get_thread_snapshot(graph, thread_id)
    return serialize_agent_result(state, thread_id=thread_id, thread_business_key=thread_business_key, snapshot=snapshot)


def get_ragops_agent_state(*, user, thread_id: str) -> dict | None:
    if not thread_id:
        return None
    graph = build_graph()
    snapshot = get_thread_snapshot(graph, thread_id)
    if not snapshot or not snapshot.values:
        return None
    assert_thread_owner(snapshot, user)
    authorize_agent_context(user, snapshot.values)
    business_key = (snapshot.values.get("thread_business_key") or "")
    return serialize_agent_result(snapshot.values, thread_id=thread_id, thread_business_key=business_key, snapshot=snapshot)


def resume_ragops_agent(*, user, thread_id: str, resume_payload: dict) -> dict:
    if not thread_id:
        raise ValueError("thread_id is required.")
    if Command is None:
        raise RuntimeError("LangGraph resume is unavailable in this environment.")

    graph = build_graph()
    config = graph_config(thread_id)
    snapshot = get_thread_snapshot(graph, thread_id)
    if not snapshot or not snapshot.values:
        raise ValueError("Agent thread not found.")
    assert_thread_owner(snapshot, user)
    authorize_agent_context(user, snapshot.values)
    if not is_thread_interrupted(snapshot):
        raise ValueError("Agent thread is not awaiting human decision.")

    state = graph.invoke(Command(resume=resume_payload), config=config)
    snapshot = get_thread_snapshot(graph, thread_id)
    business_key = state.get("thread_business_key") or snapshot.values.get("thread_business_key") or ""
    return serialize_agent_result(state, thread_id=thread_id, thread_business_key=business_key, snapshot=snapshot)

def build_graph():
    if StateGraph is None:
        return SequentialAgentGraph()
    workflow = StateGraph(AgentState)
    workflow.add_node("planner", planner_node)
    workflow.add_node("tool_executor", tool_executor_node)
    workflow.add_node("diagnostician", diagnostician_node)
    workflow.add_node("proposal", proposal_node)
    workflow.add_node("human_decision", human_decision_node)
    workflow.add_node("action_executor", action_executor_node)
    workflow.add_node("responder", responder_node)
    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "tool_executor")
    workflow.add_edge("tool_executor", "diagnostician")
    workflow.add_edge("diagnostician", "proposal")
    workflow.add_edge("proposal", "human_decision")
    workflow.add_edge("human_decision", "action_executor")
    workflow.add_edge("action_executor", "responder")
    workflow.add_edge("responder", END)
    checkpointer = get_agent_checkpointer()
    if checkpointer:
        return workflow.compile(checkpointer=checkpointer)
    return workflow.compile()


class SequentialAgentGraph:
    def invoke(self, state: AgentState, config: dict | None = None) -> AgentState:
        if Command is not None and isinstance(state, Command):
            raise RuntimeError("LangGraph Command resume requires a compiled LangGraph checkpointer.")
        state = planner_node(state)
        state = tool_executor_node(state)
        state = diagnostician_node(state)
        state = proposal_node(state)
        state = human_decision_node(state)
        state = action_executor_node(state)
        state = responder_node(state)
        return {**state, "status": "completed", "awaiting_human": False}

    def get_state(self, config: dict | None = None):
        return None


def state_user(state: AgentState):
    return get_user_model().objects.get(id=state["user_id"])


def thread_payload(state: AgentState) -> dict:
    return {
        "thread_id": state.get("thread_id"),
        "thread_business_key": state.get("thread_business_key"),
        "thread_metadata": state.get("thread_metadata") or {},
    }


def planner_node(state: AgentState) -> AgentState:
    if is_experiment_goal(state.get("message", "")) and state.get("kb_id") and state.get("eval_run_id"):
        return {
            **state,
            "workflow_intent": "experiment_optimization",
            "plan": [
                {"step": "读取 Baseline 失败 Case", "reason": "从 baseline 的 case_results 中识别失败阶段。"},
                {"step": "生成参数实验方案", "reason": "围绕召回、改写、上下文保真生成 2-3 套候选参数。"},
                {"step": "请求人类确认", "reason": "批量运行评测属于写操作，必须通过 human_decision_tool 征求人类决策。"},
            ],
            "tool_calls": [],
        }

    fallback = build_fallback_plan(state)
    prompt = (
        "你是 AIAssistant 的 RAGOps Agent Planner。\n"
        "你的任务是根据用户目标和当前上下文，选择需要调用的只读工具。\n"
        "只允许使用给定工具，不要发明工具。最多调用 3 个工具。\n"
        "输出严格 JSON，不要 Markdown。格式：\n"
        "{\"plan\":[{\"step\":\"...\",\"reason\":\"...\"}],"
        "\"tool_calls\":[{\"tool\":\"get_trace_detail\",\"args\":{\"trace_id\":1}}]}\n\n"
        f"当前上下文：{json.dumps(context_payload(state), ensure_ascii=False)}\n"
        f"可用工具：{json.dumps(AVAILABLE_TOOLS, ensure_ascii=False)}\n"
        f"用户目标：{state.get('message')}"
    )
    try:
        response = call_agent_llm(prompt, phase="planner", state=state, max_tokens=700)
        parsed = parse_json_object(response)
        plan = parsed.get("plan") or fallback["plan"]
        tool_calls = sanitize_tool_calls(parsed.get("tool_calls") or fallback["tool_calls"], state)
    except Exception as exc:
        logger.warning("ragops planner fallback: %s", exc)
        plan = fallback["plan"]
        tool_calls = fallback["tool_calls"]
    return {**state, "workflow_intent": "diagnosis", "plan": plan, "tool_calls": tool_calls}


def tool_executor_node(state: AgentState) -> AgentState:
    results = []
    for call in state.get("tool_calls", []):
        name = call.get("tool")
        args = call.get("args") or {}
        tool = TOOL_REGISTRY.get(name)
        if not tool:
            results.append({"tool": name, "ok": False, "error": "Unknown tool."})
            continue
        try:
            result = tool(user=state_user(state), **args)
            results.append({"tool": name, "args": args, "result": result})
        except Exception as exc:
            logger.exception("ragops tool failed tool=%s", name)
            results.append({"tool": name, "args": args, "result": {"ok": False, "error": str(exc)}})
    return {**state, "tool_results": results}


def diagnostician_node(state: AgentState) -> AgentState:
    if state.get("workflow_intent") == "experiment_optimization":
        try:
            result = create_experiment_plan(
                user=state_user(state),
                kb_id=int(state["kb_id"]),
                baseline_run_id=int(state["eval_run_id"]),
                goal=state.get("message", ""),
            )
            plan = result.plan
            diagnosis = {
                "summary": f"已发现 {len(plan.failure_cases)} 个 baseline 失败 case，主要失败阶段：{plan.failure_summary.get('primary_stage', 'unknown')}。",
                "severity": "medium" if plan.failure_cases else "info",
                "failure_signals": [],
                "recommendations": [],
                "recommended_actions": [
                    {
                        "type": "run_experiment_plan",
                        "label": "运行参数实验计划",
                        "reason": "通过批量评测验证参数变更是否优于 baseline。",
                    }
                ],
                "evidence_sources": [{"type": "eval_run", "id": state.get("eval_run_id")}],
            }
            return {
                **state,
                "diagnosis": diagnosis,
                "experiment_plan": serialize_experiment_plan(plan),
            }
        except Exception as exc:
            logger.exception("failed to create experiment plan")
            return {
                **state,
                "diagnosis": {"summary": str(exc), "severity": "high"},
                "experiment_plan": None,
                "human_decisions": [],
            }
    return {**state, "diagnosis": build_diagnosis(state)}


def proposal_node(state: AgentState) -> AgentState:
    decisions: list[dict] = []
    if state.get("workflow_intent") == "experiment_optimization" and state.get("experiment_plan"):
        plan = state["experiment_plan"]
        decisions.append(
            {
                "decision_type": "run_experiment_plan",
                "title": "运行参数实验计划",
                "description": f"Agent 已基于 Baseline Run #{plan.get('baseline_run')} 生成 {len(plan.get('variants') or [])} 套参数实验方案。确认后会批量创建 Eval Run。",
                "confirm_label": "确认运行实验",
                "risk_level": "medium",
                "payload": {
                    "experiment_plan": plan.get("id"),
                    "baseline_run": plan.get("baseline_run"),
                    "variant_count": len(plan.get("variants") or []),
                },
                "source": "experiment_plan",
                "action_type": "run_experiment_plan",
            }
        )
    else:
        decisions.extend(propose_regression_decisions(state, state.get("diagnosis") or {}))
    return {**state, "human_decisions": decisions}


def human_decision_node(state: AgentState) -> AgentState:
    cards = state.get("action_cards")
    if cards is None:
        cards = []
        for decision in state.get("human_decisions", []):
            card = human_decision_tool(state, decision)
            if card:
                cards.append(card)
        state = {**state, "action_cards": cards}

    if not cards:
        return {**state, "awaiting_human": False}

    resume_payload = interrupt(
        {
            "action_cards": cards,
            "awaiting_human": True,
            **thread_payload(state),
        }
    )
    return {**state, "human_response": resume_payload or {}, "awaiting_human": False}


def action_executor_node(state: AgentState) -> AgentState:
    response = state.get("human_response") or {}
    action_id = response.get("action_id")
    decision = str(response.get("decision") or "").lower()
    if not action_id or not decision:
        return state

    user = state_user(state)
    action = RagAgentAction.objects.filter(id=int(action_id), owner=user).first()
    results = list(state.get("execution_results") or [])
    if not action:
        results.append({"action_id": action_id, "ok": False, "error": "Action not found."})
        return {**state, "execution_results": results}

    if decision == "rejected":
        if action.status not in {"completed", "rejected"}:
            action.status = "rejected"
            action.rejected_reason = str(response.get("reason") or "")
            action.completed_at = timezone.now()
            action.save(update_fields=["status", "rejected_reason", "completed_at", "updated_at"])
        results.append({"action_id": action.id, "decision": "rejected", "status": action.status})
        return {**state, "execution_results": results}

    if decision != "confirmed":
        results.append({"action_id": action.id, "ok": False, "error": f"Unsupported decision: {decision}"})
        return {**state, "execution_results": results}

    try:
        result = execute_agent_action(user=user, action=action)
        action.refresh_from_db()
        results.append(
            {
                "action_id": action.id,
                "decision": "confirmed",
                "status": action.status,
                "result": result,
                "created_case_id": getattr(action.created_case, "case_id", None),
            }
        )
    except Exception as exc:
        logger.exception("ragops action execution failed action_id=%s", action_id)
        action.refresh_from_db()
        results.append(
            {
                "action_id": action.id,
                "decision": "confirmed",
                "ok": False,
                "status": action.status,
                "error": str(exc),
            }
        )
    return {**state, "execution_results": results}


def responder_node(state: AgentState) -> AgentState:
    diagnosis = state.get("diagnosis") or build_diagnosis(state)
    action_cards = state.get("action_cards", [])
    execution_results = state.get("execution_results") or []
    human_response = state.get("human_response") or {}
    if execution_results:
        for item in execution_results:
            action_id = item.get("action_id")
            if not action_id:
                continue
            for card in action_cards:
                if card.get("action_id") == action_id:
                    card["status"] = item.get("status") or card.get("status")
                    if item.get("result"):
                        card["result"] = item["result"]
                    if item.get("created_case_id"):
                        card["created_case_id"] = item["created_case_id"]
                    if item.get("error"):
                        card["error_message"] = item["error"]
    if state.get("workflow_intent") == "experiment_optimization":
        plan = state.get("experiment_plan") or {}
        if execution_results:
            answer = build_post_action_answer(state, action_cards, execution_results, human_response)
        else:
            answer = (
                f"已基于 Baseline Run #{plan.get('baseline_run')} 生成参数实验计划 #{plan.get('id')}。"
                "我已经通过 human_decision_tool 向你请求确认；确认后会批量运行实验 Eval Run，并在计划详情中推荐 Winner。"
            )
        return {**state, "answer": answer, "action_cards": action_cards, "diagnosis": diagnosis}

    if execution_results:
        answer = build_post_action_answer(state, action_cards, execution_results, human_response)
        return {**state, "answer": answer, "action_cards": action_cards, "diagnosis": diagnosis}

    prompt = (
        "你是 AIAssistant 的 RAGOps Agent。请基于工具结果，用中文输出一份工程化诊断报告。\n"
        "报告结构：1. 结论 2. 证据 3. 建议 4. 下一步。\n"
        "如果证据不足，明确说明还需要选择 Trace 或 Eval Run。\n"
        "不要声称已经执行写操作；写操作必须通过 human_decision_tool 请求人类确认。\n\n"
        f"用户目标：{state.get('message')}\n"
        f"计划：{json.dumps(state.get('plan', []), ensure_ascii=False)}\n"
        f"Human Decisions: {json.dumps(action_cards, ensure_ascii=False, default=str)}\n"
        f"工具结果：{json.dumps(state.get('tool_results', []), ensure_ascii=False, default=str)[:16000]}"
    )
    try:
        answer = call_agent_llm(prompt, phase="responder", state=state, max_tokens=1600)
    except Exception as exc:
        logger.warning("ragops responder fallback: %s", exc)
        answer = fallback_answer(state)
    return {**state, "answer": answer, "action_cards": action_cards, "diagnosis": diagnosis}


def build_fallback_plan(state: AgentState) -> dict:
    plan = []
    calls = []
    if state.get("trace_id"):
        plan.append({"step": "读取当前 Trace", "reason": "诊断单次 RAG 问答需要 Trace 全链路证据。"})
        calls.append({"tool": "get_trace_detail", "args": {"trace_id": state["trace_id"]}})
        calls.append({"tool": "get_model_usage_summary", "args": {"kb_id": state.get("kb_id"), "trace_id": state["trace_id"]}})
    if state.get("eval_run_id") and state.get("compare_eval_run_id"):
        plan.append({"step": "对比两个评测 Run", "reason": "用户提供了两个评测上下文，可分析指标与失败变化。"})
        calls.append(
            {
                "tool": "compare_eval_runs",
                "args": {"left_run_id": state["compare_eval_run_id"], "right_run_id": state["eval_run_id"]},
            }
        )
    if state.get("kb_id") and not calls:
        plan.append({"step": "读取模型成本概览", "reason": "缺少 Trace/Eval 上下文时，先分析知识库级模型调用。"})
        calls.append({"tool": "get_model_usage_summary", "args": {"kb_id": state["kb_id"], "trace_id": None}})
    return {"plan": plan, "tool_calls": calls[:3]}


def sanitize_tool_calls(tool_calls: list[dict], state: AgentState) -> list[dict]:
    sanitized = []
    for call in tool_calls[:3]:
        name = call.get("tool")
        args = dict(call.get("args") or {})
        if name not in TOOL_REGISTRY:
            continue
        if name == "get_trace_detail":
            trace_id = args.get("trace_id") or state.get("trace_id")
            if not trace_id:
                continue
            args = {"trace_id": int(trace_id)}
        elif name == "compare_eval_runs":
            left = args.get("left_run_id") or state.get("compare_eval_run_id")
            right = args.get("right_run_id") or state.get("eval_run_id")
            if not left or not right:
                continue
            args = {"left_run_id": int(left), "right_run_id": int(right)}
        elif name == "get_model_usage_summary":
            args = {
                "kb_id": int(args.get("kb_id") or state.get("kb_id")) if (args.get("kb_id") or state.get("kb_id")) else None,
                "trace_id": int(args.get("trace_id") or state.get("trace_id")) if (args.get("trace_id") or state.get("trace_id")) else None,
            }
        sanitized.append({"tool": name, "args": args})
    return sanitized or build_fallback_plan(state)["tool_calls"]


def context_payload(state: AgentState) -> dict:
    return {
        "kb_id": state.get("kb_id"),
        "trace_id": state.get("trace_id"),
        "eval_run_id": state.get("eval_run_id"),
        "compare_eval_run_id": state.get("compare_eval_run_id"),
    }


def call_agent_llm(prompt: str, *, phase: str, state: AgentState, max_tokens: int) -> str:
    client = get_openai_client()
    started_at = time.perf_counter()
    response = client.chat.completions.create(
        model=settings.CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=max_tokens,
    )
    record_model_call(
        call_type="chat",
        model=settings.CHAT_MODEL,
        provider="openai_compatible",
        usage=extract_usage(response),
        latency_ms=elapsed_ms(started_at),
        owner=state_user(state),
        metadata={"agent": "ragops", "phase": phase, **thread_payload(state)},
    )
    return (response.choices[0].message.content or "").strip()


def parse_json_object(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def build_pre_hitl_summary(state: AgentState) -> str:
    diagnosis = state.get("diagnosis") or {}
    cards = state.get("action_cards") or []
    summary = diagnosis.get("summary") or "Agent 已完成证据收集与结构化诊断。"
    if cards:
        summary += f"\n\n已生成 {len(cards)} 个待确认动作。请确认或拒绝后继续，LangGraph 将从 checkpoint 恢复并生成最终报告。"
    else:
        summary += "\n\n工作流正在等待人工决策。"
    return summary


def build_post_action_answer(
    state: AgentState,
    action_cards: list[dict],
    execution_results: list[dict],
    human_response: dict,
) -> str:
    decision = human_response.get("decision")
    if decision == "rejected":
        return "你已拒绝本次 Agent 写操作。当前诊断与证据仍然保留，可继续调整参数或重新运行工作流。"

    lines = ["已完成人工确认后的 Agent 写操作，摘要如下："]
    for item in execution_results:
        action_id = item.get("action_id")
        card = next((entry for entry in action_cards if entry.get("action_id") == action_id), {})
        title = card.get("title") or f"Action #{action_id}"
        status = item.get("status") or "unknown"
        if item.get("ok") is False or status == "failed":
            lines.append(f"- {title}：执行失败（{item.get('error') or '未知错误'}）")
            continue
        if status == "running":
            lines.append(f"- {title}：已开始后台执行，可在实验计划详情中跟踪进度。")
            continue
        created_case_id = item.get("created_case_id") or (item.get("result") or {}).get("case_id")
        if created_case_id:
            lines.append(f"- {title}：已完成，Regression Case `{created_case_id}` 已创建。")
            continue
        plan_id = (item.get("result") or {}).get("plan_id")
        if plan_id:
            lines.append(f"- {title}：实验计划 #{plan_id} 已开始运行。")
            continue
        lines.append(f"- {title}：状态 {status}。")

    if state.get("workflow_intent") == "experiment_optimization":
        plan = state.get("experiment_plan") or {}
        lines.append(f"\nBaseline Run #{plan.get('baseline_run')} 的参数实验计划 #{plan.get('id')} 已进入执行阶段。")
    else:
        lines.append("\n建议下一步：在 Regression Set 或实验计划结果中验证修复效果。")
    return "\n".join(lines)


def fallback_answer(state: AgentState) -> str:
    tools = ", ".join(item.get("tool", "") for item in state.get("tool_results", [])) or "无"
    return (
        "我已经完成了只读诊断工具调用，但生成自然语言报告时出现问题。\n\n"
        f"已调用工具：{tools}\n"
        "你可以查看工具结果，或稍后重新运行 Agent。"
    )




def build_diagnosis(state: AgentState) -> dict:
    trace_payload = trace_tool_payload(state)
    failure_signals: list[dict] = []
    evidence_sources: list[dict] = []
    recommendations: list[dict] = []
    recommended_actions: list[dict] = []

    if trace_payload:
        failure_signals = detect_trace_failure_signals(trace_payload)
        evidence_sources.append(
            {
                "type": "trace",
                "id": trace_payload.get("id"),
                "question": trace_payload.get("question") or "",
                "rewritten_query": trace_payload.get("rewritten_query") or "",
            }
        )
    else:
        changed_cases = changed_eval_cases(state)
        for case in changed_cases[:3]:
            failure_signals.append(
                {
                    "code": "eval_case_regressed",
                    "label": "评测 Case 回退",
                    "evidence": f"Case {case.get('case_id')} 在对比 Run 中表现变差或失败。",
                    "recommendation": "将失败 Case 沉淀到 Regression Set，作为后续调参的回归基线。",
                }
            )
        if changed_cases:
            evidence_sources.append({"type": "eval_run_compare", "changed_case_count": len(changed_cases)})

    recommendations = build_signal_recommendations(failure_signals)
    if failure_signals:
        recommended_actions.append(
            {
                "type": "create_regression_case",
                "label": "创建 Regression Case",
                "reason": "已检测到明确失败信号，适合沉淀为后续优化的回归样例。",
                "requires_confirmation": True,
            }
        )

    severity = diagnosis_severity(failure_signals)
    return {
        "summary": diagnosis_summary(failure_signals, trace_payload),
        "severity": severity,
        "failure_signals": failure_signals,
        "recommendations": recommendations,
        "recommended_actions": recommended_actions,
        "evidence_sources": evidence_sources,
    }


def diagnosis_summary(failure_signals: list[dict], trace_payload: dict | None) -> str:
    if not failure_signals:
        if trace_payload:
            return "未检测到足以自动建议沉淀的明确失败信号，可继续人工复核 Agent 报告。"
        return "当前上下文不足，请选择 Trace 或 Eval Run 后再运行诊断。"
    labels = "、".join(signal.get("label", signal.get("code", "")) for signal in failure_signals[:3])
    question = trace_payload.get("question") if trace_payload else ""
    prefix = f"Trace 问题“{question}”" if question else "当前诊断对象"
    return f"{prefix}检测到 {len(failure_signals)} 个明确失败信号：{labels}。"


def diagnosis_severity(failure_signals: list[dict]) -> str:
    codes = {signal.get("code") for signal in failure_signals}
    if {"retrieval_empty", "answer_insufficient"} & codes:
        return "high"
    if "query_rewrite_noise" in codes or len(failure_signals) >= 2:
        return "medium"
    if failure_signals:
        return "low"
    return "info"


def build_signal_recommendations(failure_signals: list[dict]) -> list[dict]:
    templates = {
        "query_rewrite_noise": (
            "调整 Query Rewrite",
            "暂时切到 none 或 llm 策略，并增加改写后查询的长度、重复率和字符级拆分校验。",
        ),
        "bm25_noise": (
            "降低 BM25 噪声影响",
            "检查 BM25 top_k 和 RRF_K，对字符级噪声词做过滤，必要时降低 BM25 候选权重。",
        ),
        "retrieval_empty": (
            "检查索引和检索配置",
            "确认文档已索引、Milvus/BM25 候选非空，并用 debug_retrieval 复现查询。",
        ),
        "rerank_observability_gap": (
            "补齐 Rerank 埋点",
            "记录 rerank_score、pre_rerank_rank 和 rerank top_n，否则难以判断重排是否真正生效。",
        ),
        "compression_observability_gap": (
            "补齐 Compression 埋点",
            "记录压缩前后 token、节省比和保留句子，便于判断信息是否丢失。",
        ),
        "answer_insufficient": (
            "回溯召回和答案合成",
            "检查目标 chunk 是否被召回，并将该问题加入 Regression Set 做回归验证。",
        ),
        "eval_case_failed": (
            "沉淀评测失败样例",
            "将失败 Case 纳入 Regression Set，用于验证后续策略是否真正修复问题。",
        ),
    }
    recommendations = []
    seen = set()
    for signal in failure_signals:
        code = signal.get("code")
        if code in seen or code not in templates:
            continue
        seen.add(code)
        title, detail = templates[code]
        recommendations.append({"code": code, "title": title, "detail": detail})
    return recommendations


def changed_eval_cases(state: AgentState) -> list[dict]:
    for item in state.get("tool_results", []):
        result = item.get("result") or {}
        cases = result.get("changed_cases") or []
        if cases:
            return cases
    return []


def propose_regression_decisions(state: AgentState, diagnosis: dict | None = None) -> list[dict]:
    decisions: list[dict] = []
    diagnosis = diagnosis or build_diagnosis(state)
    trace_payload = trace_tool_payload(state)
    if trace_payload:
        signals = diagnosis.get("failure_signals") or []
        if signals:
            trace_id = trace_payload["id"]
            trace = filter_traces_for_user(state_user(state), RagTrace.objects.filter(id=trace_id)).select_related("session__kb").first()
            if trace:
                signal_labels = " / ".join(signal["label"] for signal in signals[:3])
                decisions.append(
                    {
                        "decision_type": "create_regression_case",
                        "action_type": "create_regression_case",
                        "source": "trace",
                        "uid": f"trace-{trace_id}-to-regression",
                        "title": "创建 Regression Case",
                        "description": f"该 Trace 存在明确失败信号：{signal_labels}。确认后将加入 Regression Set。",
                        "confirm_label": "确认创建",
                        "risk_level": "low",
                        "payload": {"trace": trace_id, "failure_signals": signals, "diagnosis_snapshot": diagnosis},
                        "kb_id": trace.session.kb_id,
                        "trace_id": trace.id,
                    }
                )

    eval_run_id = state.get("eval_run_id")
    if eval_run_id:
        candidate = first_failed_eval_case_result_id(state)
        if candidate:
            eval_case = RagEvalCaseResult.objects.filter(id=candidate, run__kb_id__in=filter_knowledge_bases_for_user(state_user(state), capability="use_agent").values("id")).select_related("run__kb").first()
            if eval_case:
                decisions.append(
                    {
                        "decision_type": "create_regression_case",
                        "action_type": "create_regression_case",
                        "source": "eval_failure",
                        "uid": f"eval-case-{candidate}-to-regression",
                        "title": "从失败样例创建 Regression Case",
                        "description": "Agent 发现评测 Run 中存在失败样例，确认后将加入 Regression Set。",
                        "confirm_label": "确认创建",
                        "risk_level": "low",
                        "payload": {
                            "eval_case": candidate,
                            "diagnosis_snapshot": diagnosis,
                            "failure_signals": [
                                {
                                    "code": "eval_case_failed",
                                    "label": "评测 Case 失败",
                                    "evidence": f"评测 Case 结果 #{candidate} 失败或发生回退。",
                                }
                            ],
                        },
                        "kb_id": eval_case.run.kb_id,
                        "eval_run_id": eval_case.run_id,
                        "eval_case_result_id": eval_case.id,
                    }
                )
    return decisions


def human_decision_tool(state: AgentState, decision: dict) -> dict | None:
    """Create a persisted human decision request from inside the LangGraph workflow."""
    if decision.get("action_type") == "run_experiment_plan":
        plan_id = decision.get("payload", {}).get("experiment_plan")
        from rag.models import RagExperimentPlan

        plan = (
            RagExperimentPlan.objects.filter(id=plan_id, owner_id=state["user_id"])
            .select_related("kb", "baseline_run")
            .prefetch_related("variants")
            .first()
        )
        if not plan:
            return None
        action = create_experiment_action(user=state_user(state), plan=plan)
        payload = action.payload or {}
        payload["human_decision"] = {
            **(payload.get("human_decision") or {}),
            "risk_level": decision.get("risk_level", "medium"),
            **thread_payload(state),
        }
        payload["agent_thread"] = thread_payload(state)
        action.payload = payload
        action.save(update_fields=["payload", "updated_at"])
        return serialize_action_card(action, decision)

    return persist_action_card(
        state,
        uid=decision["uid"],
        source=decision["source"],
        title=decision["title"],
        description=decision["description"],
        confirm_label=decision.get("confirm_label", "确认"),
        payload={
            **(decision.get("payload") or {}),
            "human_decision": {"risk_level": decision.get("risk_level", "low"), **thread_payload(state)},
            "agent_thread": thread_payload(state),
        },
        kb_id=decision.get("kb_id"),
        trace_id=decision.get("trace_id"),
        eval_run_id=decision.get("eval_run_id"),
        eval_case_result_id=decision.get("eval_case_result_id"),
    )


def trace_tool_payload(state: AgentState) -> dict | None:
    for item in state.get("tool_results", []):
        if item.get("tool") != "get_trace_detail":
            continue
        result = item.get("result") or {}
        if result.get("ok") is False:
            return None
        trace = result.get("trace") or {}
        if trace.get("id"):
            return trace
    return None


def detect_trace_failure_signals(trace: dict) -> list[dict]:
    signals: list[dict] = []
    question = str(trace.get("question") or "")
    rewritten = str(trace.get("rewritten_query") or "")
    answer = str(trace.get("answer") or "")
    vector_results = trace.get("vector_results") or []
    bm25_results = trace.get("bm25_results") or []
    hybrid_results = trace.get("hybrid_results") or []
    rerank_results = trace.get("rerank_results") or []
    compression_results = trace.get("compression_results") or []
    compression_stats = trace.get("compression_stats") or {}
    settings = trace.get("settings") or {}

    if rewritten and rewritten != question and is_noisy_rewrite(question, rewritten):
        signals.append(
            {
                "code": "query_rewrite_noise",
                "label": "查询改写噪声",
                "evidence": f"改写后的查询存在重复或字符级拆分：{compact_signal_text(rewritten, 96)}",
            }
        )

    if not (vector_results or bm25_results or hybrid_results or rerank_results):
        signals.append(
            {
                "code": "retrieval_empty",
                "label": "检索结果为空",
                "evidence": "未记录到 Vector、BM25、Hybrid 或 Rerank 候选结果。",
            }
        )

    bm25_noise = bm25_top_result_noise(question, bm25_results, vector_results or hybrid_results)
    if bm25_noise:
        signals.append(bm25_noise)

    if rerank_results and all(item.get("rerank_score") in (None, "") for item in rerank_results):
        signals.append(
            {
                "code": "rerank_observability_gap",
                "label": "Rerank 可观测性缺失",
                "evidence": "存在 Rerank 结果，但所有 chunk 都缺少 rerank_score。",
            }
        )

    compression_strategy = str(settings.get("compression_strategy") or "").lower()
    compression_enabled = compression_strategy and compression_strategy not in {"none", "off", "false"}
    if compression_enabled and compression_results:
        missing_tokens = all(item.get("compressed_tokens") in (None, "") for item in compression_results)
        if missing_tokens or not compression_stats:
            signals.append(
                {
                    "code": "compression_observability_gap",
                    "label": "Compression 可观测性缺失",
                    "evidence": "压缩看起来已启用，但 token 或压缩统计不完整。",
                }
            )

    insufficient_markers = ["资料不足", "无法回答", "不知道", "没有足够", "not enough information"]
    if any(marker.lower() in answer.lower() for marker in insufficient_markers):
        signals.append(
            {
                "code": "answer_insufficient",
                "label": "回答资料不足",
                "evidence": "最终回答表明检索上下文不足以回答问题。",
            }
        )

    return signals[:5]


def is_noisy_rewrite(question: str, rewritten: str) -> bool:
    if re.search(r"([\u4e00-\u9fff]\s){2,}[\u4e00-\u9fff]", rewritten):
        return True
    question_terms = set(normalize_terms(question))
    rewrite_terms = normalize_terms(rewritten)
    if not rewrite_terms:
        return False
    duplicate_ratio = 1 - (len(set(rewrite_terms)) / max(len(rewrite_terms), 1))
    length_ratio = len(rewritten) / max(len(question), 1)
    single_cjk_count = len(re.findall(r"(?<![\u4e00-\u9fff])[\u4e00-\u9fff](?![\u4e00-\u9fff])", rewritten))
    overlap = len(question_terms & set(rewrite_terms))
    return (length_ratio >= 2.2 and duplicate_ratio >= 0.25) or single_cjk_count >= 4 or (length_ratio >= 2.8 and overlap <= 1)


def bm25_top_result_noise(question: str, bm25_results: list[dict], semantic_results: list[dict]) -> dict | None:
    if not bm25_results:
        return None
    question_terms = important_query_terms(question)
    if not question_terms:
        return None
    top_bm25 = bm25_results[0]
    bm25_overlap = term_overlap(question_terms, top_bm25.get("content") or "")
    semantic_overlap = max([term_overlap(question_terms, item.get("content") or "") for item in semantic_results[:3]] or [0])
    if bm25_overlap == 0 or (semantic_overlap - bm25_overlap >= 2):
        return {
            "code": "bm25_noise",
            "label": "BM25 噪声召回",
            "evidence": (
                f"BM25 Top chunk #{top_bm25.get('chunk_id')} 与关键查询词重合较弱 "
                f"({bm25_overlap}/{len(question_terms)})."
            ),
        }
    return None


def normalize_terms(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", text.lower())


def important_query_terms(question: str) -> list[str]:
    candidates = ["需求", "分析", "开发", "评审", "发布", "上线", "工具", "流程", "阶段", "使用"]
    terms = [term for term in candidates if term in question]
    terms.extend(term for term in normalize_terms(question) if len(term) >= 2 and term not in terms)
    return terms[:8]


def term_overlap(terms: list[str], text: str) -> int:
    return sum(1 for term in terms if term and term in text)


def compact_signal_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit] + "..."


def has_tool_result(state: AgentState, tool_name: str) -> bool:
    return any(item.get("tool") == tool_name and item.get("result", {}).get("ok") is not False for item in state.get("tool_results", []))


def first_failed_eval_case_result_id(state: AgentState) -> int | None:
    for item in state.get("tool_results", []):
        result = item.get("result") or {}
        cases = result.get("changed_cases") or result.get("case_changes") or result.get("cases") or []
        for case in cases:
            result_id = case.get("right_id") or case.get("id") or case.get("result_id")
            status = str(case.get("right_status") or case.get("status") or "").lower()
            right_correct = case.get("right_correct")
            if result_id and (status in {"failed", "fail", "error"} or right_correct is False):
                return int(result_id)
    return None



def serialize_action_card(action: RagAgentAction, decision: dict | None = None) -> dict:
    payload = action.payload or {}
    return {
        "id": f"action-{action.id}",
        "action_id": action.id,
        "action_type": action.action_type,
        "title": action.title,
        "description": action.description,
        "confirm_label": action.confirm_label,
        "status": action.status,
        "source": action.source,
        "payload": payload,
        "risk_level": (decision or {}).get("risk_level") or payload.get("human_decision", {}).get("risk_level"),
        "failure_signals": payload.get("failure_signals") or [],
    }


def persist_action_card(
    state: AgentState,
    *,
    uid: str,
    source: str,
    title: str,
    description: str,
    confirm_label: str,
    payload: dict,
    kb_id=None,
    trace_id=None,
    eval_run_id=None,
    eval_case_result_id=None,
) -> dict:
    user = state_user(state)
    allowed_kbs = filter_knowledge_bases_for_user(user, capability="use_agent")
    kb = allowed_kbs.filter(id=kb_id).first() if kb_id else None
    trace = filter_traces_for_user(user, RagTrace.objects.filter(id=trace_id)).first() if trace_id else None
    eval_run = RagEvalRun.objects.filter(id=eval_run_id, kb_id__in=allowed_kbs.values("id")).first() if eval_run_id else None
    eval_case_result = RagEvalCaseResult.objects.filter(id=eval_case_result_id, run__kb_id__in=allowed_kbs.values("id")).first() if eval_case_result_id else None
    if kb_id and not kb:
        raise PermissionError("Agent action resource access denied.")
    action, created = RagAgentAction.objects.get_or_create(
        owner=state_user(state),
        action_uid=uid,
        defaults={
            "kb": kb,
            "trace": trace,
            "eval_run": eval_run,
            "eval_case_result": eval_case_result,
            "action_type": "create_regression_case",
            "source": source,
            "title": title,
            "description": description,
            "confirm_label": confirm_label,
            "payload": payload,
            "status": "pending",
        },
    )
    if not created and action.status in {"pending", "failed"}:
        action.kb = kb
        action.trace = trace
        action.eval_run = eval_run
        action.eval_case_result = eval_case_result
        action.action_type = "create_regression_case"
        action.source = source
        action.title = title
        action.description = description
        action.confirm_label = confirm_label
        action.payload = payload
        action.status = "pending"
        action.result = {}
        action.error_message = ""
        action.rejected_reason = ""
        action.confirmed_at = None
        action.completed_at = None
        action.save(
            update_fields=[
                "kb",
                "trace",
                "eval_run",
                "eval_case_result",
                "action_type",
                "source",
                "title",
                "description",
                "confirm_label",
                "payload",
                "status",
                "result",
                "error_message",
                "rejected_reason",
                "confirmed_at",
                "completed_at",
                "updated_at",
            ]
        )
    return {
        "id": uid,
        "action_id": action.id,
        "type": action.action_type,
        "source": action.source,
        "title": action.title,
        "description": action.description,
        "confirm_label": action.confirm_label,
        "payload": action.payload,
        "failure_signals": action.payload.get("failure_signals") or [],
        "status": action.status,
        "created_at": action.created_at.isoformat(),
    }



def is_experiment_goal(message: str) -> bool:
    text = (message or "").lower()
    keywords = ["优化", "实验", "参数", "baseline", "winner", "召回", "回归评测"]
    return any(keyword in text for keyword in keywords)


def serialize_experiment_plan(plan) -> dict:
    plan.refresh_from_db()
    variants = list(plan.variants.all())
    return {
        "id": plan.id,
        "status": plan.status,
        "goal": plan.goal,
        "baseline_run": plan.baseline_run_id,
        "baseline_param_signature": getattr(plan.baseline_run, "param_signature", ""),
        "failure_cases": plan.failure_cases,
        "failure_summary": plan.failure_summary,
        "recommendation": plan.recommendation,
        "winner_variant": plan.winner_variant_id,
        "variants": [
            {
                "id": item.id,
                "name": item.name,
                "hypothesis": item.hypothesis,
                "rag_options": item.rag_options,
                "eval_run": item.eval_run_id,
                "eval_run_status": item.eval_run.status if item.eval_run else None,
                "eval_run_signature": item.eval_run.param_signature if item.eval_run else "",
                "result_summary": item.result_summary,
                "is_winner": item.is_winner,
            }
            for item in variants
        ],
    }
