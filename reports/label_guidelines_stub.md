# Label guidelines stub — SOMA gate (SPEAK / SILENT)

Draft only. **Not applied** in this data-prep pass. Gold `label_gold` stays empty.
The gate answers one token: `SPEAK` or `SILENT`. Default is SILENT.

A frozen writer LLM will draft a sentence **only if** the gate says SPEAK.
You are labelling the **decision point after the last line** of a 12-message window.

## Ten rules

1. **SILENT** if the last line is clearly addressed to another human (`Nick:`) who is present in the window and can reasonably answer (they have been talking in that thread).
2. **SILENT** if the last line is thanks / acknowledgement / “works now” / “fixed” / “solved” — the problem is closed.
3. **SPEAK** if the last line is a **group-facing help question** (no clear addressee, or “anyone”, “how do I…”) **and** nobody in the window is already helping that thread.
4. **SILENT** if two (or more) threads are mixed in the window **and** the last question is already owned (someone is answering it, or `thread_overlap_count` shows the last line is tied to an active helper).
5. **SILENT** on JOIN / PART / QUIT / nick-change context that leaked through, pastes, banlists, or off-topic social chat with no Ubuntu-support ask.
6. **SPEAK** if a user is stuck after an unanswered question that is still open in the last 1–3 lines (install / driver / apt / boot / wifi / display) and the room has not offered a next step.
7. **SILENT** if the last speaker is a known helper / bot-like nick already giving the answer (e.g. long how-to, pastebin request already made) — do not pile on.
8. **SILENT** if the last line is directed at the group but is not a request for help (jokes, “lol”, status, “brb”, OT).
9. **SPEAK** if the last line is a follow-up clarification on an **unanswered** support question (“I tried that, still broken — what next?”) and no one in-window has replied to it.
10. When unsure, **SILENT**. The writer is expensive; false SPEAK is worse than a missed turn. Use `notes` for edge cases (multiple questions, language mix, the addressee just left).

## What `guideline_hint` is

An automatic, non-gold hint such as `question + no clear addressee` / `addressed to human` / `thanks`. Ignore it when it conflicts with the rules above.

## What you are not labelling

- The wording of a reply (the writer model does that later).
- Thread disentanglement as a graph (Kummerfeld `connections` are a feature only).
- Dyadic Lowe Ubuntu Dialogue Corpus items (not in this dataset).
