"""Frontend text-input dispatch into the classic conversation pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.intent_parser import normalize_system_text


@dataclass(frozen=True)
class FrontendTextDependencies:
    logger: Any
    get_current_state: Callable[[], str]
    interrupt_current_response: Callable[..., Any]
    transition_state: Callable[..., Any]
    normalize_music_text: Callable[[str], str]
    broadcast: Callable[[str, Any], None]
    add_conversation_turn: Callable[[str, str], None]
    broadcast_turn_info: Callable[[], None]
    append_conversation_ledger: Callable[[str, str], None]
    handle_user_text: Callable[..., Any]
    read_next_overrides: Callable[[], dict[str, Any] | None]
    clear_next_overrides: Callable[[], None]
    log_event: Callable[..., Any]
    new_interaction_id: Callable[[], str]
    thread_factory: Callable[..., Any]


def dispatch_frontend_text(
    dependencies: FrontendTextDependencies,
    payload: dict[str, Any] | str,
) -> None:
    """Validate one frontend message and dispatch it on a worker thread."""
    if isinstance(payload, str):
        text = payload.strip()
        source = "frontend"
        mode = "conversation"
    else:
        text = (payload.get("text") or "").strip()
        source = payload.get("source", "frontend")
        mode = payload.get("mode", "conversation")

    if not text:
        dependencies.logger.info("[TEXT_INPUT] Empty text, ignoring")
        return

    dependencies.log_event(
        f'INPUT[source={source}][mode={mode}]: "{text}"', stage="ui"
    )
    if dependencies.get_current_state() == "SPEAKING":
        dependencies.logger.info("[TEXT_INPUT] Barge-in triggered via text input")
        try:
            dependencies.interrupt_current_response(
                "TEXT_BARGE_IN", target_state="LISTENING"
            )
        except Exception as exc:
            dependencies.logger.warning(f"[TEXT_INPUT] Barge-in error: {exc}")

    interaction_id = dependencies.new_interaction_id()
    try:
        dependencies.transition_state(
            "THINKING", interaction_id=interaction_id, source="text_input"
        )
    except Exception:
        pass

    def process_text() -> None:
        try:
            normalized_text = normalize_system_text(text)
            normalized_text = dependencies.normalize_music_text(normalized_text)
            dependencies.broadcast("log", f"User: {normalized_text}")
            dependencies.add_conversation_turn("User", normalized_text)
            dependencies.broadcast_turn_info()
            dependencies.append_conversation_ledger("user", normalized_text)
            dependencies.handle_user_text(
                user_text=normalized_text,
                confidence_hint=1.0,
                interaction_id=interaction_id,
                replay_mode=False,
                overrides=dependencies.read_next_overrides(),
                audio_data=None,
            )
        except Exception as exc:
            dependencies.logger.error(
                f"[TEXT_INPUT] Pipeline error: {exc}", exc_info=True
            )
            dependencies.broadcast("status", "ERROR")
        finally:
            dependencies.clear_next_overrides()

    worker = dependencies.thread_factory(
        target=process_text,
        daemon=True,
        name="ARGO.TextInput",
    )
    worker.start()
