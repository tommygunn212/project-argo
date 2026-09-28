import core.pipeline_inspection_responses as responses


class _Logger:
    def info(self, *args, **kwargs):
        pass


class _Pipeline(responses.PipelineInspectionResponseMixin):
    def __init__(self):
        self.logger = _Logger()
        self.deliveries = []

    def _deliver_canonical_response(self, message, *args, **kwargs):
        self.deliveries.append((message, args, kwargs))
        return True


def _call(pipeline, method, text):
    return getattr(pipeline, method)(None, text, "interaction-1", False, {})


def test_vision_describe_uses_fixed_grounding_prompt(monkeypatch):
    pipeline = _Pipeline()
    prompts = []
    monkeypatch.setattr(
        responses,
        "describe_screen",
        lambda user_prompt: prompts.append(user_prompt) or "screen description",
    )

    assert _call(pipeline, "_respond_with_vision_describe", "what is here") is True
    assert prompts == ["Describe what you see on my screen."]
    assert pipeline.deliveries[0][0] == "screen description"


def test_vision_question_passes_parsed_question(monkeypatch):
    pipeline = _Pipeline()
    questions = []
    monkeypatch.setattr(
        responses,
        "parse_vision_command",
        lambda text: {"question": "which button is selected?"},
    )
    monkeypatch.setattr(
        responses,
        "analyze_screen_with_question",
        lambda question: questions.append(question) or "the blue button",
    )

    assert _call(pipeline, "_respond_with_vision_question", "look at this") is True
    assert questions == ["which button is selected?"]
    assert pipeline.deliveries[0][0] == "the blue button"


def test_extension_search_preserves_drive_scope(monkeypatch):
    pipeline = _Pipeline()
    searches = []
    monkeypatch.setattr(
        responses,
        "parse_filesystem_command",
        lambda text: {"query": "", "drive": "D:\\", "extensions": [".pdf"]},
    )
    monkeypatch.setattr(
        responses,
        "search_by_extension",
        lambda extensions, roots=None: searches.append((extensions, roots)) or ["file.pdf"],
    )
    monkeypatch.setattr(
        responses,
        "format_file_list_for_speech",
        lambda files, label: f"{label}:{len(files)}",
    )

    assert _call(pipeline, "_respond_with_file_search", "find PDFs on D") is True
    assert searches == [([".pdf"], ["D:\\"])]
    assert pipeline.deliveries[0][0] == "matching files:1"


def test_file_info_rejects_missing_path_before_probe(monkeypatch):
    pipeline = _Pipeline()
    monkeypatch.setattr(
        responses,
        "parse_filesystem_command",
        lambda text: {"query": "Z:\\missing.txt"},
    )
    monkeypatch.setattr(responses.os.path, "exists", lambda path: False)
    monkeypatch.setattr(
        responses,
        "get_file_info",
        lambda path: (_ for _ in ()).throw(AssertionError("unexpected file probe")),
    )

    assert _call(pipeline, "_respond_with_file_info", "inspect missing") is True
    assert pipeline.deliveries[0][0].startswith("I couldn't find that path.")


def test_recent_files_preserves_parsed_time_window(monkeypatch):
    pipeline = _Pipeline()
    hours_seen = []
    monkeypatch.setattr(
        responses,
        "parse_filesystem_command",
        lambda text: {"hours": 6},
    )
    monkeypatch.setattr(
        responses,
        "find_recent_files",
        lambda hours: hours_seen.append(hours) or [],
    )
    monkeypatch.setattr(
        responses,
        "format_file_list_for_speech",
        lambda files, label: "none",
    )

    assert _call(pipeline, "_respond_with_file_recent", "recent files") is True
    assert hours_seen == [6]
    assert pipeline.deliveries[0][0] == "none"
