"""
Tests for ARGO Computer Vision, File System Agent, and Task Planner.
"""

import os
import sys
import json
import tempfile
import shutil
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

# ── Ensure project root is on sys.path ────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.intent_parser import RuleBasedIntentParser, IntentType
from tools.vision import (
    parse_vision_command, _encode_image_base64,
    capture_screenshot, describe_screen, read_screen_error,
    analyze_screen_with_question, analyze_image,
)
from tools.filesystem import (
    search_files, search_by_extension, find_large_files, find_recent_files,
    get_file_info, get_directory_size, parse_filesystem_command,
    format_file_list_for_speech, format_file_info_for_speech,
    _human_size, CATEGORY_EXTENSIONS,
)
from tools.task_planner import (
    generate_plan_rules, generate_plan_with_llm, execute_plan,
    format_plan_for_speech, format_plan_preview_for_speech,
    is_multi_step_request, TaskPlan, PlanStep,
)


# ====================================================================
# Intent Parser Tests — Vision, File System, Task Planner
# ====================================================================

class TestVisionIntents:
    """Test vision-related intent detection."""

    def setup_method(self):
        self.parser = RuleBasedIntentParser()

    def test_describe_screen(self):
        r = self.parser.parse("what's on my screen")
        assert r.intent_type == IntentType.VISION_DESCRIBE

    def test_describe_display(self):
        r = self.parser.parse("describe what you see on my display")
        assert r.intent_type == IntentType.VISION_DESCRIBE

    def test_take_screenshot(self):
        r = self.parser.parse("take a screenshot")
        assert r.intent_type == IntentType.VISION_DESCRIBE

    def test_grab_screenshot(self):
        r = self.parser.parse("grab a screenshot for me")
        assert r.intent_type == IntentType.VISION_DESCRIBE

    def test_look_at_screen(self):
        r = self.parser.parse("look at my screen")
        assert r.intent_type == IntentType.VISION_DESCRIBE

    def test_read_error(self):
        r = self.parser.parse("read the error on my screen")
        assert r.intent_type == IntentType.VISION_READ_ERROR

    def test_what_error(self):
        r = self.parser.parse("what error is on the screen")
        assert r.intent_type == IntentType.VISION_READ_ERROR

    def test_read_warning(self):
        r = self.parser.parse("read that warning message")
        assert r.intent_type == IntentType.VISION_READ_ERROR

    def test_error_meaning(self):
        r = self.parser.parse("what does this exception mean")
        assert r.intent_type == IntentType.VISION_READ_ERROR

    def test_capture_screen_snap(self):
        r = self.parser.parse("capture a screen snap")
        assert r.intent_type == IntentType.VISION_DESCRIBE


class TestFileSystemIntents:
    """Test file system intent detection."""

    def setup_method(self):
        self.parser = RuleBasedIntentParser()

    def test_find_files(self):
        r = self.parser.parse("find my tax documents on D drive")
        assert r.intent_type == IntentType.FILE_SEARCH

    def test_search_pdf(self):
        r = self.parser.parse("search for PDF files")
        assert r.intent_type == IntentType.FILE_SEARCH

    def test_locate_photos(self):
        r = self.parser.parse("locate my photos on E drive")
        assert r.intent_type == IntentType.FILE_SEARCH

    def test_where_are_files(self):
        r = self.parser.parse("where are my video files")
        assert r.intent_type == IntentType.FILE_SEARCH

    def test_large_files(self):
        r = self.parser.parse("find large files on C drive")
        assert r.intent_type == IntentType.FILE_LARGE

    def test_biggest_files(self):
        r = self.parser.parse("show me the biggest files")
        assert r.intent_type == IntentType.FILE_LARGE

    def test_huge_files(self):
        r = self.parser.parse("what huge files are taking space")
        assert r.intent_type == IntentType.FILE_LARGE

    def test_recent_downloads(self):
        r = self.parser.parse("what did I download today")
        assert r.intent_type == IntentType.FILE_RECENT

    def test_recent_files(self):
        r = self.parser.parse("show me recent files")
        assert r.intent_type == IntentType.FILE_RECENT

    def test_latest_downloads(self):
        r = self.parser.parse("latest downloads")
        assert r.intent_type == IntentType.FILE_RECENT

    def test_find_on_e_drive(self):
        r = self.parser.parse("find my images on E drive")
        assert r.intent_type == IntentType.FILE_SEARCH


class TestTaskPlannerIntents:
    """Test multi-step task planner intent detection."""

    def setup_method(self):
        self.parser = RuleBasedIntentParser()

    def test_research_and_email(self):
        r = self.parser.parse("research quantum computing and then email the summary to Sarah")
        assert r.intent_type == IntentType.TASK_PLAN

    def test_search_and_remind(self):
        r = self.parser.parse("find my PDF files and then remind me to review them tomorrow")
        assert r.intent_type == IntentType.TASK_PLAN

    def test_screenshot_and_note(self):
        r = self.parser.parse("look at my screen and then email what you see to Sarah")
        assert r.intent_type == IntentType.TASK_PLAN

    def test_simple_not_multistep(self):
        """Single-domain request should NOT match task planner."""
        r = self.parser.parse("set a reminder for 3pm")
        assert r.intent_type != IntentType.TASK_PLAN

    def test_remind_and_calendar(self):
        r = self.parser.parse("remind me about the dentist and also schedule it on my calendar")
        assert r.intent_type == IntentType.TASK_PLAN


# ====================================================================
# Vision Module Tests
# ====================================================================

class TestVisionParser:
    """Test vision command parsing."""

    def test_parse_describe(self):
        result = parse_vision_command("what's on my screen")
        assert result["action"] == "describe"

    def test_parse_error(self):
        result = parse_vision_command("read the error on my screen")
        assert result["action"] == "read_error"

    def test_parse_screenshot(self):
        result = parse_vision_command("take a screenshot")
        assert result["action"] == "describe"

    def test_parse_exception(self):
        result = parse_vision_command("what does this exception mean")
        assert result["action"] == "read_error"

    def test_parse_question(self):
        result = parse_vision_command("how many tabs do I have open")
        assert result["action"] == "question"
        assert "tabs" in result["question"]


class TestVisionEncoding:
    """Test image encoding."""

    def test_base64_encoding(self):
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        result = _encode_image_base64(fake_png)
        assert result.startswith("data:image/png;base64,")
        assert len(result) > 30

    def test_base64_roundtrip(self):
        import base64
        data = b"test image data"
        encoded = _encode_image_base64(data)
        # Extract the base64 portion
        b64_part = encoded.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        assert decoded == data


class TestVisionScreenCapture:
    """Test screenshot capture with mocked mss."""

    def test_capture_screenshot_success(self):
        mock_mss_instance = MagicMock()
        mock_mss_instance.monitors = [None, {"left": 0, "top": 0, "width": 1920, "height": 1080}]
        mock_img = MagicMock()
        mock_img.rgb = b"\x00" * 100
        mock_img.size = (1920, 1080)
        mock_mss_instance.grab.return_value = mock_img

        mock_mss_module = MagicMock()
        mock_mss_module.mss.return_value.__enter__ = MagicMock(return_value=mock_mss_instance)
        mock_mss_module.mss.return_value.__exit__ = MagicMock(return_value=False)
        mock_mss_module.tools.to_png.return_value = b"\x89PNG_FAKE"

        with patch.dict("sys.modules", {"mss": mock_mss_module}):
            # Reimport to pick up mocked module
            import importlib
            import tools.vision as tv
            importlib.reload(tv)
            result = tv.capture_screenshot()
            assert result == b"\x89PNG_FAKE"
            # Restore
            importlib.reload(tv)

    @patch("tools.vision.analyze_image", return_value="I see a desktop with icons.")
    @patch("tools.vision.capture_screenshot", return_value=b"fake_png")
    def test_describe_screen(self, mock_cap, mock_analyze):
        result = describe_screen()
        assert "desktop" in result.lower()
        mock_cap.assert_called_once()
        mock_analyze.assert_called_once()

    @patch("tools.vision.capture_screenshot", return_value=None)
    def test_describe_screen_no_capture(self, mock_cap):
        result = describe_screen()
        assert "couldn't capture" in result.lower()

    @patch("tools.vision.analyze_image", return_value="Error: FileNotFoundError — suggest checking path.")
    @patch("tools.vision.capture_screenshot", return_value=b"fake_png")
    def test_read_screen_error(self, mock_cap, mock_analyze):
        result = read_screen_error()
        assert "error" in result.lower()

    @patch("tools.vision.analyze_image", return_value="You have 5 Chrome tabs open.")
    @patch("tools.vision.capture_screenshot", return_value=b"fake_png")
    def test_analyze_with_question(self, mock_cap, mock_analyze):
        result = analyze_screen_with_question("how many tabs are open")
        assert "5" in result


class TestVisionAnalyzeImage:
    """Test GPT-4o vision API call."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": ""})
    def test_no_api_key(self):
        result = analyze_image(b"fake", "describe")
        assert "API key" in result

    def test_no_image_data(self):
        result = analyze_image(b"", "describe")
        assert "No image data" in result

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_successful_analysis(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "I see a code editor."
        mock_client.chat.completions.create.return_value = mock_response

        mock_openai_module = MagicMock()
        mock_openai_module.OpenAI.return_value = mock_client

        with patch.dict("sys.modules", {"openai": mock_openai_module}):
            import importlib
            import tools.vision as tv
            importlib.reload(tv)
            result = tv.analyze_image(b"\x89PNG_FAKE", "what's on screen")
            assert "code editor" in result.lower()
            mock_client.chat.completions.create.assert_called_once()
            importlib.reload(tv)


# ====================================================================
# File System Module Tests
# ====================================================================

class TestFilesystemParser:
    """Test filesystem command parsing."""

    def test_parse_search(self):
        result = parse_filesystem_command("find my tax documents")
        assert result["action"] == "search"
        assert "tax" in result["query"]

    def test_parse_large_files(self):
        result = parse_filesystem_command("find large files on D drive")
        assert result["action"] == "large_files"
        assert result["drive"] == "D:\\"
        assert result["min_size_mb"] > 0

    def test_parse_recent(self):
        result = parse_filesystem_command("what did I download today")
        assert result["action"] == "recent"
        assert result["hours"] == 24

    def test_parse_recent_week(self):
        result = parse_filesystem_command("recent downloads this week")
        assert result["action"] == "recent"
        assert result["hours"] == 168

    def test_parse_extension_pdf(self):
        result = parse_filesystem_command("find pdf files")
        assert result["extensions"] == {".pdf"}

    def test_parse_category_image(self):
        result = parse_filesystem_command("find image files")
        assert result["extensions"] == CATEGORY_EXTENSIONS["image"]

    def test_parse_category_video(self):
        result = parse_filesystem_command("search for video files")
        assert result["extensions"] == CATEGORY_EXTENSIONS["video"]

    def test_parse_drive_letter(self):
        result = parse_filesystem_command("search E drive for documents")
        assert result["drive"] == "E:\\"

    def test_parse_large_with_size(self):
        result = parse_filesystem_command("find files larger than 500mb")
        assert result["action"] == "large_files"
        assert result["min_size_mb"] == 500.0

    def test_parse_large_gb(self):
        result = parse_filesystem_command("find files bigger than 2 gig")
        assert result["action"] == "large_files"
        assert result["min_size_mb"] == 2048.0


class TestFilesystemSearch:
    """Test actual file search with temp directory."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create test files
        self._create_file("report.pdf", 1024)
        self._create_file("notes.txt", 512)
        self._create_file("photo.jpg", 2048)
        os.makedirs(os.path.join(self.tmpdir, "subdir"), exist_ok=True)
        self._create_file("subdir/deep_report.pdf", 768)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _create_file(self, name, size):
        path = os.path.join(self.tmpdir, name)
        with open(path, "wb") as f:
            f.write(b"\x00" * size)

    def test_search_by_name(self):
        results = search_files("report", roots=[self.tmpdir])
        assert len(results) == 2
        names = {r["name"] for r in results}
        assert "report.pdf" in names
        assert "deep_report.pdf" in names

    def test_search_by_name_with_ext(self):
        results = search_files("report", roots=[self.tmpdir], extensions={".pdf"})
        assert len(results) == 2

    def test_search_no_match(self):
        results = search_files("nonexistent_xyz", roots=[self.tmpdir])
        assert len(results) == 0

    def test_search_by_extension(self):
        results = search_by_extension({".jpg"}, roots=[self.tmpdir])
        assert len(results) == 1
        assert results[0]["name"] == "photo.jpg"

    def test_search_max_results(self):
        results = search_files("", roots=[self.tmpdir], max_results=2)
        assert len(results) <= 2


class TestFilesystemLargeFiles:
    """Test large file finder."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create files of various sizes
        for name, size_kb in [("small.txt", 1), ("medium.dat", 50), ("big.bin", 200)]:
            path = os.path.join(self.tmpdir, name)
            with open(path, "wb") as f:
                f.write(b"\x00" * (size_kb * 1024))

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_find_large(self):
        # min_size_mb=0.1 = 100KB threshold
        results = find_large_files(self.tmpdir, min_size_mb=0.1)
        assert len(results) == 1
        assert results[0]["name"] == "big.bin"

    def test_find_none_above_threshold(self):
        results = find_large_files(self.tmpdir, min_size_mb=1.0)  # 1MB
        assert len(results) == 0

    def test_sorted_by_size(self):
        results = find_large_files(self.tmpdir, min_size_mb=0.001)
        # Should be sorted largest first
        sizes = [r["size"] for r in results]
        assert sizes == sorted(sizes, reverse=True)


class TestFilesystemRecentFiles:
    """Test recent file finder."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create a recent file
        path = os.path.join(self.tmpdir, "recent.txt")
        with open(path, "w") as f:
            f.write("hello")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_find_recent(self):
        results = find_recent_files(directory=self.tmpdir, hours=1)
        assert len(results) == 1
        assert results[0]["name"] == "recent.txt"

    def test_find_recent_empty_dir(self):
        empty = tempfile.mkdtemp()
        results = find_recent_files(directory=empty, hours=1)
        assert len(results) == 0
        shutil.rmtree(empty, ignore_errors=True)


class TestFilesystemInfo:
    """Test file info retrieval."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.filepath = os.path.join(self.tmpdir, "test.txt")
        with open(self.filepath, "w") as f:
            f.write("test content")
        os.makedirs(os.path.join(self.tmpdir, "subdir"), exist_ok=True)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_file_info(self):
        info = get_file_info(self.filepath)
        assert info["name"] == "test.txt"
        assert info["is_directory"] is False
        assert info["size"] > 0

    def test_dir_info(self):
        info = get_file_info(self.tmpdir)
        assert info["is_directory"] is True
        assert info["file_count"] >= 1

    def test_nonexistent(self):
        info = get_file_info("/nonexistent/path/abc")
        assert "error" in info

    def test_directory_size(self):
        result = get_directory_size(self.tmpdir)
        assert result["size"] > 0
        assert result["file_count"] >= 1
        assert result["truncated"] is False


class TestFilesystemFormatting:
    """Test formatting helpers."""

    def test_human_size_bytes(self):
        assert "B" in _human_size(500)

    def test_human_size_kb(self):
        assert "KB" in _human_size(5000)

    def test_human_size_mb(self):
        assert "MB" in _human_size(5_000_000)

    def test_human_size_gb(self):
        assert "GB" in _human_size(5_000_000_000)

    def test_format_empty(self):
        result = format_file_list_for_speech([], label="files")
        assert "No files found" in result

    def test_format_list(self):
        files = [{"name": "test.pdf", "size": 1024}]
        result = format_file_list_for_speech(files)
        assert "test.pdf" in result

    def test_format_file_info(self):
        info = {"name": "test.txt", "is_directory": False, "size": 1024, "modified": "2025-01-01"}
        result = format_file_info_for_speech(info)
        assert "test.txt" in result

    def test_format_dir_info(self):
        info = {"name": "docs", "is_directory": True, "file_count": 5, "folder_count": 2}
        result = format_file_info_for_speech(info)
        assert "folder" in result.lower()
        assert "5 files" in result


# ====================================================================
# Task Planner Tests
# ====================================================================

class TestTaskPlannerRules:
    """Test rule-based plan generation."""

    def test_research_and_email(self):
        plan = generate_plan_rules("research quantum computing and email it to Sarah")
        assert plan is not None
        assert len(plan.steps) == 2
        assert plan.steps[0].action == "llm_generate"
        assert plan.steps[1].action == "draft_email"

    def test_find_and_tell(self):
        plan = generate_plan_rules("find my PDF files and tell me about them")
        assert plan is not None
        assert len(plan.steps) == 2
        assert plan.steps[0].action == "search_files"
        assert plan.steps[1].action == "summarize"

    def test_screen_and_email(self):
        plan = generate_plan_rules("look at my screen and then email what you see")
        assert plan is not None
        assert len(plan.steps) == 2
        assert plan.steps[0].action == "describe_screen"
        assert plan.steps[1].action == "draft_email"

    def test_screen_and_note(self):
        plan = generate_plan_rules("check my screen and then save a note about it")
        assert plan is not None
        assert plan.steps[1].action == "save_note"

    def test_remind_and_calendar(self):
        plan = generate_plan_rules("remind me to call the doctor and also add it to my calendar")
        assert plan is not None
        assert len(plan.steps) == 2
        assert plan.steps[0].action == "set_reminder"
        assert plan.steps[1].action == "add_calendar_event"

    def test_no_match(self):
        plan = generate_plan_rules("what time is it")
        assert plan is None


class TestTaskPlannerLLM:
    """Test LLM-based plan generation."""

    def test_llm_plan_success(self):
        mock_response = json.dumps([
            {"action": "llm_generate", "params": {"text": "research AI"}, "description": "Research AI"},
            {"action": "save_note", "params": {"use_previous": True}, "description": "Save research as note"},
        ])
        plan = generate_plan_with_llm("research AI and save a note", llm_call=lambda p: mock_response)
        assert plan is not None
        assert len(plan.steps) == 2
        assert plan.steps[0].action == "llm_generate"
        assert plan.steps[1].action == "save_note"

    def test_llm_plan_with_markdown_fences(self):
        mock_response = '```json\n[{"action": "search_files", "params": {"query": "report"}, "description": "Find report"}]\n```'
        plan = generate_plan_with_llm("find my report", llm_call=lambda p: mock_response)
        assert plan is not None
        assert len(plan.steps) == 1

    def test_llm_plan_invalid_json(self):
        plan = generate_plan_with_llm("do something", llm_call=lambda p: "not json at all")
        assert plan is None

    def test_llm_plan_unknown_action_fallback(self):
        mock_response = json.dumps([
            {"action": "fly_to_moon", "params": {}, "description": "Impossible"},
        ])
        plan = generate_plan_with_llm("fly me to the moon", llm_call=lambda p: mock_response)
        assert plan is not None
        assert plan.steps[0].action == "llm_generate"  # Fell back to llm_generate


class TestTaskPlanExecution:
    """Test plan execution engine."""

    def test_execute_all_success(self):
        steps = [
            PlanStep("step_a", {}, "Step A"),
            PlanStep("step_b", {"use_previous": True}, "Step B"),
        ]
        plan = TaskPlan("test goal", steps)

        executor = {
            "step_a": lambda params, prev: "result_a",
            "step_b": lambda params, prev: f"got {prev}",
        }
        result = execute_plan(plan, executor)
        assert result.status == "done"
        assert result.steps[0].result == "result_a"
        assert result.steps[1].result == "got result_a"

    def test_execute_partial_failure(self):
        steps = [
            PlanStep("good", {}, "Good step"),
            PlanStep("bad", {}, "Bad step"),
        ]
        plan = TaskPlan("test", steps)

        def fail_fn(params, prev):
            raise ValueError("oops")

        executor = {
            "good": lambda params, prev: "ok",
            "bad": fail_fn,
        }
        result = execute_plan(plan, executor)
        assert result.status == "partial"
        assert result.steps[0].status == "done"
        assert result.steps[1].status == "failed"

    def test_execute_unknown_action(self):
        steps = [PlanStep("nonexistent", {}, "Unknown")]
        plan = TaskPlan("test", steps)
        result = execute_plan(plan, {})
        assert result.steps[0].status == "failed"
        assert "Unknown action" in result.steps[0].result

    def test_execute_all_failed(self):
        steps = [PlanStep("bad", {}, "Fail")]
        plan = TaskPlan("test", steps)

        def fail_fn(params, prev):
            raise RuntimeError("boom")

        result = execute_plan(plan, {"bad": fail_fn})
        assert result.status == "failed"

    def test_previous_result_chaining(self):
        steps = [
            PlanStep("a", {}, "First"),
            PlanStep("b", {"use_previous": True}, "Second"),
            PlanStep("c", {"use_previous": True}, "Third"),
        ]
        plan = TaskPlan("chain test", steps)

        executor = {
            "a": lambda p, prev: "alpha",
            "b": lambda p, prev: f"{prev}+beta",
            "c": lambda p, prev: f"{prev}+gamma",
        }
        result = execute_plan(plan, executor)
        assert result.status == "done"
        assert result.steps[2].result == "alpha+beta+gamma"


class TestTaskPlanFormatting:
    """Test plan formatting for speech."""

    def test_format_done(self):
        steps = [PlanStep("a", {}, "Step A")]
        steps[0].status = "done"
        steps[0].result = "Everything worked."
        plan = TaskPlan("test", steps)
        plan.status = "done"
        result = format_plan_for_speech(plan)
        assert "Done" in result
        assert "Everything worked" in result

    def test_format_failed(self):
        steps = [PlanStep("a", {}, "Step A")]
        steps[0].status = "failed"
        plan = TaskPlan("do something", steps)
        plan.status = "failed"
        result = format_plan_for_speech(plan)
        assert "failed" in result.lower()

    def test_format_partial(self):
        steps = [
            PlanStep("a", {}, "Step A"),
            PlanStep("b", {}, "Step B"),
        ]
        steps[0].status = "done"
        steps[0].result = "ok"
        steps[1].status = "failed"
        plan = TaskPlan("test", steps)
        plan.status = "partial"
        result = format_plan_for_speech(plan)
        assert "1 of 2" in result

    def test_format_preview(self):
        steps = [
            PlanStep("a", {}, "Research topic"),
            PlanStep("b", {}, "Draft email"),
        ]
        plan = TaskPlan("test", steps)
        result = format_plan_preview_for_speech(plan)
        assert "2 steps" in result
        assert "Research topic" in result


class TestMultiStepDetection:
    """Test is_multi_step_request detection."""

    def test_two_domains(self):
        assert is_multi_step_request("search my files and then email the results")

    def test_single_domain(self):
        assert not is_multi_step_request("search for my tax documents")

    def test_no_connector(self):
        assert not is_multi_step_request("search files email results")

    def test_connector_but_single_domain(self):
        assert not is_multi_step_request("write an email and then send it")


class TestPlanStep:
    """Test PlanStep data class."""

    def test_to_dict(self):
        step = PlanStep("search_files", {"query": "test"}, "Search for test")
        d = step.to_dict()
        assert d["action"] == "search_files"
        assert d["status"] == "pending"
        assert d["description"] == "Search for test"

    def test_result_truncated(self):
        step = PlanStep("a", {}, "test")
        step.result = "x" * 300
        d = step.to_dict()
        assert len(d["result"]) == 200


class TestTaskPlanDict:
    """Test TaskPlan serialization."""

    def test_to_dict(self):
        steps = [PlanStep("a", {}, "Step A")]
        plan = TaskPlan("my goal", steps)
        d = plan.to_dict()
        assert d["goal"] == "my goal"
        assert d["status"] == "pending"
        assert len(d["steps"]) == 1
