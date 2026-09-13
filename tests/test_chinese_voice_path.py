import inspect

from core.conversation_buffer import ConversationBuffer
from core.pipeline import ArgoPipeline
from core.openai_tts import OpenAIRealtimeTTS


def test_chinese_lessons_receive_a_native_script_contract():
    pipeline = ArgoPipeline.__new__(ArgoPipeline)

    prompt = pipeline._build_llm_prompt(
        "Teach me how to say hello in Chinese.", "tommy_gunn", False
    )

    assert "MANDARIN CHINESE LESSON CONTRACT" in prompt
    assert "Chinese characters first" in prompt
    assert "pinyin with tone marks" in prompt


def test_cantonese_lessons_request_jyutping():
    pipeline = ArgoPipeline.__new__(ArgoPipeline)

    prompt = pipeline._build_llm_prompt(
        "How do I say hello in Cantonese?", "tommy_gunn", False
    )

    assert "CANTONESE LESSON CONTRACT" in prompt
    assert "Jyutping with tone numbers" in prompt


def test_tts_sanitizer_keeps_chinese_characters():
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline._tts_min_text_length = 1
    pipeline._tts_min_confidence = 0.35
    pipeline._current_stt_confidence = 1.0

    assert pipeline._sanitize_tts_text("你好, nǐ hǎo.") == "你好, nǐ hǎo."


def test_streaming_path_does_not_strip_non_ascii_text():
    source = inspect.getsource(ArgoPipeline._generate_and_speak_streamed)

    assert 're.sub(r"[^\\x00-\\x7F]+", "", complete)' not in source
    assert 're.sub(r"[^\\x00-\\x7F]+", "", remainder)' not in source
    assert 're.sub(r"[^\\x00-\\x7F]+", "", full_response or "")' not in source


def test_openai_tts_explicitly_pronounces_chinese_characters():
    tts = OpenAIRealtimeTTS.__new__(OpenAIRealtimeTTS)
    tts.model = "gpt-4o-mini-tts"
    tts.voice = "nova"
    tts.speed = 1.0
    tts._instructions = "Speak warmly."

    kwargs = tts._speech_kwargs("你好, nǐ hǎo. Hello.")

    assert "instructions" in kwargs
    assert "Do not skip" in kwargs["instructions"]


def test_conversation_buffer_keeps_twelve_recent_exchanges_by_default():
    buffer = ConversationBuffer(max_turns=24)
    for index in range(12):
        buffer.add("User", f"question {index}")
        buffer.add("Assistant", f"answer {index}")

    messages = buffer.as_messages()

    assert len(messages) == 24
    assert messages[0]["content"] == "question 0"
    assert messages[-1]["content"] == "answer 11"


def test_repeated_stt_prompt_echo_is_rejected_but_real_questions_are_not():
    assert ArgoPipeline._is_low_confidence_stt_prompt_echo(
        "argo tommy home assistant jellyfin", 0.35
    )
    assert not ArgoPipeline._is_low_confidence_stt_prompt_echo(
        "how do I connect Jellyfin to Home Assistant", 0.35
    )


def test_rag_is_reserved_for_explicit_project_or_technical_questions():
    assert not ArgoPipeline._should_use_rag_context("Tell me a joke about fishing.")
    assert ArgoPipeline._should_use_rag_context("Help me debug the ARGO server log.")


def test_spoken_chat_defaults_allow_a_substantive_answer():
    pipeline = ArgoPipeline.__new__(ArgoPipeline)
    pipeline.runtime_overrides = {}

    assert pipeline._get_spoken_response_controls() == {
        "temperature": 0.55,
        "max_tokens": 360,
        "max_sentences": 6,
        "verbosity": 3,
    }
