"""Wait for the next LLM sentence while the current sentence is playing."""
import queue


def prefetch_next(sentence_queue, tts, generation, stop, logger):
    while not stop.is_set() and not tts.is_cancelled(generation):
        try:
            sentence = sentence_queue.get(timeout=0.05)
        except queue.Empty:
            continue
        if sentence is None:
            return None
        if stop.is_set() or tts.is_cancelled(generation):
            return None
        try:
            pcm = tts.synthesize(sentence, generation)
        except Exception as exc:
            logger.warning("[TTS-STREAM] Pre-fetch failed: %s", exc)
            pcm = None  # Failed request has ended; streaming playback can retry once.
        if stop.is_set() or tts.is_cancelled(generation):
            return None
        return sentence, pcm
    return None
