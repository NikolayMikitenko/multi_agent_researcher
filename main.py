from __future__ import annotations

import asyncio
import json
from typing import Any

from langgraph.types import Command

from config import Settings
from supervisor import supervisor


settings = Settings()

STAGE_LABELS = {
    "plan": "Planner",
    "research": "Researcher",
    "critique": "Critic",
    "save_report": "save_report",
}


def short_args(args: dict[str, Any]) -> str:
    if "request" in args:
        return repr(args["request"])
    if "query" in args:
        return repr(args["query"])
    if "url" in args:
        return repr(args["url"])
    if "filename" in args and "content" in args:
        preview = args["content"][:80].replace("\n", " ")
        if len(args["content"]) > 80:
            preview += "..."
        return f'filename={args["filename"]!r}, content={preview!r}'
    return json.dumps(args, ensure_ascii=False)


def summarize_tool_result(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    first_line = text.splitlines()[0].strip()
    if len(first_line) > 160:
        first_line = first_line[:160] + "..."
    return first_line


def format_structured(name: str, data: dict[str, Any]) -> str:
    if name == "ResearchPlan":
        parts = [
            "ResearchPlan(",
            f'  goal={data.get("goal")!r},',
            f'  search_queries={data.get("search_queries", [])!r},',
            f'  sources_to_check={data.get("sources_to_check", [])!r},',
            f'  output_format={data.get("output_format")!r}',
            ")",
        ]
        return "\n".join(parts)

    if name == "CritiqueResult":
        parts = [
            "CritiqueResult(",
            f'  verdict={data.get("verdict")!r},',
            f'  is_fresh={data.get("is_fresh")!r},',
            f'  is_complete={data.get("is_complete")!r},',
            f'  is_well_structured={data.get("is_well_structured")!r},',
            f'  strengths={data.get("strengths", [])!r},',
            f'  gaps={data.get("gaps", [])!r},',
            f'  revision_requests={data.get("revision_requests", [])!r}',
            ")",
        ]
        return "\n".join(parts)

    return json.dumps(data, ensure_ascii=False, indent=2)


class ConsoleState:
    def __init__(self) -> None:
        self.current_stage: str | None = None
        self.research_round = 0
        self.seen_stage_payloads: set[tuple[str, ...]] = set()

    def stage_header(self, stage: str) -> str:
        if stage == "Researcher":
            self.research_round += 1
            return f"[Supervisor → {stage}]  (round {self.research_round})"
        return f"[Supervisor → {stage}]"


STATE = ConsoleState()


def show_interrupt(interrupt_value: dict) -> dict:
    requests = interrupt_value.get("action_requests", [])

    print("\n" + "=" * 60)
    print("⏸️  ACTION REQUIRES APPROVAL")
    print("=" * 60)

    first_request = {}
    for request in requests:
        first_request = request
        action_name = request.get("action") or request.get("name") or "N/A"
        args = request.get("args") or request.get("arguments") or {}
        print(f"  Tool:  {action_name}")
        print(f"  Args:  {json.dumps(args, indent=2, ensure_ascii=False)}")

        if action_name == "save_report":
            content = args.get("content", "")
            preview = content[:1000]
            if len(content) > 1000:
                preview += "\n...[truncated preview]..."
            print("\n  Preview:")
            print(preview)

    print()
    return first_request


def build_resume_command(decision_type: str, interrupt_request: dict) -> Command:
    if decision_type == "approve":
        return Command(resume={"decisions": [{"type": "approve"}]})

    if decision_type == "edit":
        original_name = interrupt_request.get("action") or interrupt_request.get("name")
        original_args = (interrupt_request.get("args") or interrupt_request.get("arguments") or {}).copy()

        print("Leave fields empty to keep original values.")
        new_filename = input("📝 New filename (optional): ").strip()
        if new_filename:
            original_args["filename"] = new_filename

        print("📝 Paste replacement report content. Finish with a single line: :::end")
        lines = []
        while True:
            line = input()
            if line.strip() == ":::end":
                break
            lines.append(line)

        edited_content = "\n".join(lines).strip()
        if edited_content:
            original_args["content"] = edited_content

        return Command(
            resume={
                "decisions": [
                    {
                        "type": "edit",
                        "edited_action": {
                            "name": original_name,
                            "args": original_args,
                        },
                    }
                ]
            }
        )

    return Command(
        resume={
            "decisions": [
                {
                    "type": "reject",
                    "message": "User rejected this action.",
                }
            ]
        }
    )


def parse_json_maybe(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def print_nested_model_update(stage: str, messages: list[Any]) -> None:
    if not messages:
        return

    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None)
    if tool_calls:
        for call in tool_calls:
            print(f"  🔧 {call['name']}({short_args(call['args'])})")
        return

    content = getattr(last, "content", None)
    if not content:
        return

    text = content if isinstance(content, str) else str(content)
    text = text.strip()
    if not text:
        return

    if stage == "Planner":
        obj = parse_json_maybe(text)
        if obj:
            key = ("Planner", json.dumps(obj, ensure_ascii=False, sort_keys=True))
            if key not in STATE.seen_stage_payloads:
                STATE.seen_stage_payloads.add(key)
                print("  📎 " + format_structured("ResearchPlan", obj).replace("\n", "\n  "))
        return

    if stage == "Critic":
        obj = parse_json_maybe(text)
        if obj:
            key = ("Critic", json.dumps(obj, ensure_ascii=False, sort_keys=True))
            if key not in STATE.seen_stage_payloads:
                STATE.seen_stage_payloads.add(key)
                print("  📎 " + format_structured("CritiqueResult", obj).replace("\n", "\n  "))
        return

    if stage == "Researcher":
        summary = summarize_tool_result(text)
        if summary:
            key = ("Researcher", summary)
            if key not in STATE.seen_stage_payloads:
                STATE.seen_stage_payloads.add(key)
                print(f"  📎 {summary}")


def print_nested_tool_update(stage: str, messages: list[Any]) -> None:
    if not messages:
        return

    last = messages[-1]
    content = getattr(last, "content", None)
    if isinstance(content, list):
        content = " ".join(str(x) for x in content)
    if not content:
        return

    summary = summarize_tool_result(str(content))
    if not summary:
        return

    key = (stage, "tool_result", summary)
    if key in STATE.seen_stage_payloads:
        return

    STATE.seen_stage_payloads.add(key)
    print(f"  📎 {summary}")


def handle_top_level_model(messages: list[Any]) -> None:
    if not messages:
        return

    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None)

    if tool_calls:
        for call in tool_calls:
            name = call["name"]
            args = call["args"]
            stage = STAGE_LABELS.get(name)

            if stage:
                STATE.current_stage = stage
                print("\n" + STATE.stage_header(stage))
                print(f"🔧 {name}({short_args(args)})")
            else:
                print("\n[Supervisor]")
                print(f"🔧 {name}({short_args(args)})")
        return

    content = getattr(last, "content", None)
    if content:
        text = content if isinstance(content, str) else str(content)
        text = text.strip()
        if text:
            print("\n[Supervisor]")
            print(f"📎 {text}")


async def handle_update_chunk(chunk: dict[str, Any], config: dict) -> bool:
    data = chunk["data"]
    ns = chunk.get("ns", ())

    if "__interrupt__" in data:
        interrupt = data["__interrupt__"][0]
        interrupt_value = getattr(interrupt, "value", interrupt)
        request = show_interrupt(interrupt_value)

        decision = input("👉 approve / edit / reject: ").strip().lower()
        if decision == "approve":
            print("\n✅ Approved! Resuming...\n")
        elif decision == "edit":
            print("\n✏️  Editing tool call...\n")
        else:
            print("\n❌ Rejected.\n")

        cmd = build_resume_command(
            decision if decision in {"approve", "edit"} else "reject",
            request,
        )
        await stream_graph(cmd, config)
        return True

    if not ns:
        for step_name, update in data.items():
            if update is None:
                continue

            messages = update.get("messages", [])
            if not messages:
                continue

            if step_name == "model":
                handle_top_level_model(messages)
            elif step_name == "tools":
                # suppress duplicate raw wrapper outputs
                continue

        return False

    stage = STATE.current_stage or "Subagent"

    for step_name, update in data.items():
        messages = update.get("messages", [])
        if not messages:
            continue

        if step_name == "model":
            print_nested_model_update(stage, messages)
        elif step_name == "tools":
            print_nested_tool_update(stage, messages)

    return False


async def stream_graph(payload, config: dict) -> None:
    async for chunk in supervisor.astream(
        payload,
        config=config,
        stream_mode="updates",
        version="v2",
        subgraphs=True,
    ):
        if chunk["type"] != "updates":
            continue

        should_stop = await handle_update_chunk(chunk, config)
        if should_stop:
            return


async def amain():
    print("Multi-Agent Research System - modern async v2 stream (clean) (type 'exit' to quit)")
    config = {"configurable": {"thread_id": 'async_research'}}

    while True:
        query = input("\nYou: ").strip()
        if query.lower() in {"exit", "quit"}:
            break
        if not query:
            continue

        STATE.current_stage = None
        STATE.research_round = 0
        STATE.seen_stage_payloads.clear()

        await stream_graph(
            {"messages": [{"role": "user", "content": query}]},
            config,
        )
        print()


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()