from types import SimpleNamespace

import core.pipeline_task_planning as planning


class _Logger:
    def info(self, *args, **kwargs):
        pass


class _Pipeline(planning.PipelineTaskPlanningMixin):
    def __init__(self):
        self.logger = _Logger()
        self.deliveries = []
        self.llm_prompts = []

    def _deliver_canonical_response(self, message, *args, **kwargs):
        self.deliveries.append((message, args, kwargs))
        return True

    def _writing_llm_call(self, prompt, interaction_id):
        self.llm_prompts.append((prompt, interaction_id))
        return "generated"


def test_task_plan_prefers_rule_based_plan(monkeypatch):
    pipeline = _Pipeline()
    plan = SimpleNamespace(name="plan")
    executed = SimpleNamespace(name="executed")
    monkeypatch.setattr(planning, "generate_plan_rules", lambda text: plan)
    monkeypatch.setattr(
        planning,
        "generate_plan_with_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected LLM")),
    )
    monkeypatch.setattr(
        planning,
        "execute_plan",
        lambda value, executor: executed if value is plan and executor else None,
    )
    monkeypatch.setattr(planning, "format_plan_for_speech", lambda value: "plan complete")

    handled = pipeline._respond_with_task_plan(
        None, "find and summarize", "interaction-1", False, {}
    )

    assert handled is True
    assert pipeline.deliveries[0][0] == "plan complete"


def test_task_plan_reports_when_both_planners_decline(monkeypatch):
    pipeline = _Pipeline()
    monkeypatch.setattr(planning, "generate_plan_rules", lambda text: None)
    monkeypatch.setattr(planning, "generate_plan_with_llm", lambda *args, **kwargs: None)

    handled = pipeline._respond_with_task_plan(
        None, "unclear multi step", "interaction-1", False, {}
    )

    assert handled is True
    assert pipeline.deliveries[0][0].startswith("I couldn't break that into steps.")


def test_executor_exposes_expected_action_contract():
    pipeline = _Pipeline()

    executor = pipeline._build_plan_executor("interaction-1")

    assert set(executor) == {
        "search_files",
        "describe_screen",
        "read_screen_error",
        "draft_email",
        "send_email",
        "save_note",
        "set_reminder",
        "add_calendar_event",
        "list_reminders",
        "list_calendar",
        "smart_home",
        "llm_generate",
        "summarize",
        "web_search",
        "draft_blog",
    }


def test_executor_search_files_uses_previous_output_as_query(monkeypatch):
    pipeline = _Pipeline()
    queries = []
    monkeypatch.setattr(
        planning,
        "search_files",
        lambda query: queries.append(query) or ["result.txt"],
    )
    monkeypatch.setattr(
        planning,
        "format_file_list_for_speech",
        lambda files: "one result",
    )

    result = pipeline._build_plan_executor("interaction-1")["search_files"](
        {}, "prior query"
    )

    assert result == "one result"
    assert queries == ["prior query"]


def test_executor_summarize_uses_interaction_scoped_llm():
    pipeline = _Pipeline()

    result = pipeline._build_plan_executor("interaction-9")["summarize"](
        {"text": "long material"}, None
    )

    assert result == "generated"
    assert pipeline.llm_prompts == [
        ("Summarize this concisely:\n\nlong material", "interaction-9")
    ]
