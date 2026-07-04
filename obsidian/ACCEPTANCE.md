# Acceptance tests — ChatGPT → Obsidian exporter

Run these after configuring `~/Obsidian/ChatGPTVault` (or paths in `chatgpt_exporter/config.yaml`) and completing at least one bulk or bookmarklet export.

## Bulk export acceptance

1. **Monthly markdown files**  
   - Under `~/Obsidian/ChatGPTVault/markdown/`, **exactly eight** files exist for the configured campaign window:  
     - `2025-08.md`, `2025-09.md`, `2025-10.md`, `2025-11.md`, `2025-12.md`, `2026-01.md`, `2026-02.md`, `2026-03.md`

2. **Raw JSON folders**  
   - Under `~/Obsidian/ChatGPTVault/raw_json/`, a folder `YYYY-MM/` exists for each of the same eight months (may be empty until conversations exist in that month).

3. **Coverage**  
   - At least one exported conversation originated from the **normal** sidebar/history (non-project).  
   - At least one exported conversation originated from a **personal Project** (URL or metadata indicates project context).

4. **No mixed months**  
   - Open each `YYYY-MM.md`: every `conversation_date` metadata line in that file is a `YYYY-MM-DD` date within that file’s calendar month.

5. **Correspondence**  
   - For a sampled conversation: the `conversation_id` / `source_url` in markdown matches a file under `raw_json/YYYY-MM/` for the same month.

6. **Unresolved handling**  
   - If any conversation lacks a resolved date, it appears in `unresolved_dates.log` and raw JSON under `raw_json/_unresolved/` — **not** as a falsely dated entry in a monthly `.md` file.

## Ongoing export acceptance (bookmarklet + receiver)

1. **Regular chat**  
   - With `python3 capture_receiver.py` running, run the bookmarklet on a standard `/c/…` chat.  
   - A raw JSON file appears under the correct `raw_json/YYYY-MM/` for the resolved `conversation_date`, and the matching `markdown/YYYY-MM.md` is updated.

2. **Project chat**  
   - Repeat on a Project chat (`/g/…` in path). Payload and files reflect `is_project_chat: true` when the page exposes project context.

3. **Duplicate**  
   - Run the bookmarklet twice on the same conversation without changes. Second run does **not** duplicate the markdown block or raw JSON (receiver reports skip / duplicate semantics).

4. **New conversation**  
   - Export a different conversation; it **appends** (or merges) into the correct month file without removing prior blocks.

5. **Sorting**  
   - Within a month file, `## Conversation:` blocks are ordered ascending by `conversation_date`.  
   - Within a conversation, message headings reflect ascending timestamps when `time[datetime]` was present in the DOM; otherwise DOM order is preserved.
