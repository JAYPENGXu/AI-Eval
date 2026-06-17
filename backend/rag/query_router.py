from __future__ import annotations

import re
from dataclasses import dataclass


WEB_REQUIRED_PATTERN = re.compile(
    r"(今天|昨日|昨天|明天|现在|当前|实时|最新|近期|最近|刚刚|新闻|热搜|天气|气温|"
    r"股价|股票|汇率|币价|价格|航班|火车|赛事|比分|搜索|联网|网上|互联网|网页|官网|"
    r"today|latest|current|real[- ]?time|news|weather|stock|price|search|web)",
    re.IGNORECASE,
)

UNSUPPORTED_PATTERN = re.compile(
    r"^(你好|您好|hi|hello|在吗|谢谢|讲个笑话|写首诗|唱首歌|翻译|润色|帮我写|生成一段|"
    r"随便聊聊|你是谁|介绍一下你|hello|hi)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryRouteDecision:
    query_intent: str
    route_decision: str
    route_reason: str
    confidence: float

    def as_dict(self) -> dict:
        return {
            "query_intent": self.query_intent,
            "route_decision": self.route_decision,
            "route_reason": self.route_reason,
            "confidence": self.confidence,
        }


def classify_query_route(original_query: str, standalone_query: str | None = None) -> QueryRouteDecision:
    text = " ".join(part.strip() for part in [original_query or "", standalone_query or ""] if part and part.strip())
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return QueryRouteDecision(
            query_intent="unsupported",
            route_decision="reject",
            route_reason="问题为空，无法判断是否属于知识库问答。",
            confidence=1.0,
        )

    if WEB_REQUIRED_PATTERN.search(text):
        return QueryRouteDecision(
            query_intent="web_required",
            route_decision="reject_without_web_tool",
            route_reason="问题包含实时、最新、天气、新闻、价格、搜索等联网信息特征，需要外部搜索工具。",
            confidence=0.86,
        )

    if UNSUPPORTED_PATTERN.search(compact) or len(compact) <= 2:
        return QueryRouteDecision(
            query_intent="unsupported",
            route_decision="reject",
            route_reason="问题不属于内部知识库问答，也没有触发联网信息需求。",
            confidence=0.72,
        )

    return QueryRouteDecision(
        query_intent="internal_knowledge",
        route_decision="rag",
        route_reason="未命中联网实时信息特征，按内部知识库问题进入 RAG 检索。",
        confidence=0.68,
    )


def blocked_route_answer(decision: QueryRouteDecision) -> str:
    if decision.query_intent == "web_required":
        return (
            "这个问题需要联网或实时搜索才能可靠回答。"
            "当前系统暂未接入 Web Search 工具，因此无法回答。"
            "你可以上传相关资料到知识库后再提问，或等待后续接入联网搜索能力。"
        )
    return (
        "当前系统只支持回答已上传知识库中的问题。"
        "这个问题没有被识别为内部知识库问题，也不属于已接入的联网搜索能力范围，因此无法回答。"
    )
