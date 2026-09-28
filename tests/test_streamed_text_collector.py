from core.streamed_text_collector import StreamedTextCollector


def sentence_pop(buffer, allow_soft_split):
    if ". " in buffer:
        complete, remainder = buffer.split(". ", 1)
        return complete + ".", remainder
    return "", buffer


def collector(*, alive=True, maximum=3, sanitize=lambda text: text):
    queued = []
    value = StreamedTextCollector(
        pop_chunk=sentence_pop,
        sanitize=sanitize,
        enqueue=queued.append,
        tts_is_alive=lambda: alive,
        max_sentences=maximum,
    )
    return value, queued


def test_streamed_fragments_retain_full_text_and_queue_complete_sentences():
    value, queued = collector()

    value.accept("First sentence. Sec")
    value.accept("ond sentence. remainder")
    value.flush()

    assert value.full_response == "First sentence. Second sentence. remainder"
    assert queued == ["First sentence.", "Second sentence.", "remainder"]


def test_sentence_limit_truncates_tts_without_truncating_full_response():
    value, queued = collector(maximum=1)

    value.accept("First. Second. Third")
    value.accept(" still retained")
    value.flush()

    assert queued == ["First."]
    assert value.truncated is True
    assert value.full_response == "First. Second. Third still retained"


def test_inactive_tts_discards_chunks_but_keeps_display_response():
    value, queued = collector(alive=False)

    value.accept("Visible answer. remainder")
    value.flush()

    assert queued == []
    assert value.full_response == "Visible answer. remainder"


def test_empty_sanitized_chunk_is_not_counted_toward_limit():
    value, queued = collector(maximum=1, sanitize=lambda text: "" if text.startswith("skip") else text)

    value.accept("skip this. speak this. tail")

    assert queued == ["speak this."]
    assert value.queued_chunks == 1
    assert value.truncated is True
