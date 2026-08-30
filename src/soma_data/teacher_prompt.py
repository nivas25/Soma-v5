"""Teacher prompts for the SOMA gate silver-label pilot. Do not paraphrase."""

PROMPT_VERSION = "pilot_v1"

TEACHER_SYSTEM_PROMPT = """You are a careful human rater in #ubuntu IRC support. You are NOT the assistant that will talk. You only decide whether an EXTRA silent helper-bot should send a message AFTER the last line.

Default is SILENT.

SPEAK only if ALL are true:
  - the LAST message needs help (stuck user, group-facing question, or clearly unanswered request)
  - nobody in the 12-line window is already handling that same thread
  - one short technical hint would help that last thread
  - you would not be piling onto a finished "thanks" / joke / side chat

SILENT if ANY is true:
  - last line is addressed to a specific nick who is already in the window
  - last line is thanks / works / fixed / solved / nevermind
  - last line is chit-chat, legal/piracy debate, or offtopic
  - an in-window helper (including ubotu/ubottu) already answered that question
  - several unrelated questions are flying; the last line is already owned by a human
  - you are unsure

Read only the provided window. Do not invent commands, package names, or messages that are not in the window. Do not write a reply to the channel.

Return ONE JSON object, no markdown:
{"label":"SPEAK" or "SILENT","reason":"<=20 words pointing at the last line"}"""


def _yn(value: object) -> str:
    if value is True or str(value).strip().lower() in {"true", "1", "yes"}:
        return "yes"
    if value is False or str(value).strip().lower() in {"false", "0", "no", ""}:
        return "no"
    return "yes" if value else "no"


def _addr(value: object) -> str:
    if value is None:
        return "group"
    s = str(value).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return "group"
    return s


def build_user_payload(row: dict) -> str:
    """Exact per-call user payload. One window only."""
    hint = row.get("guideline_hint") or ""
    chat = row.get("chat_block") or ""
    return (
        f"WINDOW_ID: {row['window_id']}\n"
        f"ROOM:\n"
        f"last_speaker: {row.get('last_speaker') or 'UNKNOWN'}\n"
        f"question_open: {_yn(row.get('question_open'))}\n"
        f"addressed_to: {_addr(row.get('addressed_to'))}\n"
        f"n_speakers: {row.get('n_speakers_in_window')}\n"
        f"last_is_question: {_yn(row.get('last_is_question'))}\n"
        f"last_is_thanks: {_yn(row.get('last_is_thanks'))}\n"
        f"thread_overlap_count: {row.get('thread_overlap_count')}\n"
        f"guideline_hint: {hint}   (this is NOT an answer; ignore if it conflicts with the rules)\n"
        f"\n"
        f"CHAT (oldest to newest, 12 lines):\n"
        f"{chat}\n"
        f"\n"
        f"Decide SPEAK or SILENT for AFTER the last line."
    )
