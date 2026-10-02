"""Parse uploaded text/PDF documents and merge into unified_knowledge.json."""

from __future__ import annotations

import io
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from concurrency import STORE_LOCK

DEFAULT_L1_TEAM = "TBD"
DEFAULT_L1_PERSON = "TBD"

TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}\s*[AP]M\b", re.I)
MAJOR_HEADING_RE = re.compile(
    r"^(how to|what to|when to|steps to|process to|wrong details)\b",
    re.I,
)
FIELD_LABELS = frozenset(
    {
        "user id",
        "first name",
        "surname",
        "email address",
        "mobile number",
        "job title",
        "official email id",
        "mandatory checks",
        "probing",
        "probing questions",
        "system navigation",
        "resolution",
        "tagging",
        "steps",
        "if not resolved",
        "details required",
        "required documents",
        "note",
        "old user details",
        "new user details",
    }
)
ACTION_WORDS = (
    "activation",
    "deactivation",
    "transfer",
    "creation",
    "deletion",
    "addition",
    "update",
)
PLACEHOLDER_MARKERS = (
    "drop buyer .txt or .pdf",
    "drop seller .txt or .pdf",
    "they are auto-ingested into unified_knowledge",
    "after ingest, files move to",
    "post http://localhost:8000/ingest/inbox",
)
JUNK_BRANCH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^imported section$", re.I),
    re.compile(r"^they are auto-ingested", re.I),
    re.compile(r"^after ingest, files move", re.I),
    re.compile(r"^or when you call post http", re.I),
    re.compile(r"^if yes$", re.I),
    re.compile(r"^if required$", re.I),
    re.compile(r"^follow the steps below", re.I),
    re.compile(r"^confirm the user", re.I),
    re.compile(r"^if the user is\b", re.I),
)


def extract_text_from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF ingest. Run: pip install pypdf") from exc

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:60] or "new_branch"


def is_timestamp_line(line: str) -> bool:
    return bool(TIMESTAMP_RE.match(line.strip()))


def is_section_label_line(line: str) -> bool:
    stripped = line.strip().rstrip(":").lower()
    if stripped in FIELD_LABELS:
        return True
    return stripped.startswith("buyer incident")


def is_placeholder_text(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in PLACEHOLDER_MARKERS)


def is_junk_branch_title(title: str) -> bool:
    stripped = title.strip().rstrip(":")
    if not stripped or len(stripped) < 4:
        return True
    if any(pattern.search(stripped) for pattern in JUNK_BRANCH_PATTERNS):
        return True

    lower = stripped.lower()
    if re.match(r"^if\s+(yes|no|required|not resolved|admin|the user)\b", lower):
        return True

    # Field labels and short form fragments (not help topics).
    if not stripped.endswith("?"):
        if re.match(
            r"^(required|details|email address|user id|mobile number|name of|"
            r"date of|postcode|job title|old user|new user)\b",
            lower,
        ):
            return True
        if len(stripped.split()) <= 6 and re.search(
            r"\b(from user|to collect)\b", lower
        ):
            return True

    if re.match(
        r"^(follow|check|confirm the|system navigation|"
        r"probing questions?|mandatory checks?)\b",
        lower,
    ):
        if not stripped.endswith("?"):
            return True

    return False


def is_valid_topic_title(title: str) -> bool:
    """Gate for timestamp-anchored section titles in chat-log style support documents."""
    stripped = title.strip().rstrip(":").strip()
    if not stripped or is_junk_branch_title(stripped):
        return False

    lower = stripped.lower()
    if stripped.endswith("?"):
        return True
    if re.search(r"\((buyer|seller|admin)\)", lower):
        return True
    if MAJOR_HEADING_RE.match(lower):
        return True
    if re.match(
        r"^(how to|wrong details|while .+ (unable|getting|error)|process to|"
        r"buyer account|admin account|sub user|new organisation|profile update|"
        r"update mobile|unable to)\b",
        lower,
    ):
        return True
    # Lowercase ticket-style issue lines (e.g. "admin account transfer email already exists")
    if len(stripped) >= 15 and stripped == lower and stripped[0].isalpha():
        return True
    words = stripped.split()
    if len(words) >= 4 and stripped[0].isupper():
        return True
    if len(words) >= 3 and re.match(
        r"^(admin account|buyer account|sub user|wrong details|new organisation)\b", lower
    ):
        return True
    return False


def _next_nonempty(lines: list[str], start: int) -> tuple[int, str]:
    index = start
    while index < len(lines):
        candidate = lines[index].strip()
        if candidate:
            return index, candidate
        index += 1
    return len(lines), ""


def _fallback_single_section(lines: list[str]) -> list[tuple[str, str]]:
    title: str | None = None
    body_start = 0
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or is_timestamp_line(stripped):
            continue
        if title is None:
            candidate = stripped.rstrip(":").strip()
            if not is_valid_topic_title(candidate) or is_section_label_line(candidate):
                continue
            if len(candidate) <= 80 and not candidate.endswith("."):
                title = candidate
                body_start = index + 1
                break
        else:
            break

    if title is None:
        return []

    body = "\n".join(lines[body_start:]).strip()
    if len(body) < 40:
        return []
    return [(title, body)]


def split_sections(text: str) -> list[tuple[str, str]]:
    if is_placeholder_text(text):
        return []

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    anchors: list[tuple[int, str, int]] = []

    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or is_timestamp_line(stripped):
            index += 1
            continue
        if is_section_label_line(stripped):
            index += 1
            continue

        next_index, next_line = _next_nonempty(lines, index + 1)
        if is_timestamp_line(next_line):
            title = stripped.rstrip(":").strip()
            after_title_index, after_title = _next_nonempty(lines, next_index + 1)
            body_start = next_index + 1
            if after_title and not is_timestamp_line(after_title):
                post_title = after_title.rstrip(":").strip()
                lower_post = post_title.lower()
                prefer_post = (
                    not lower_post.startswith("steps to ")
                    and is_valid_topic_title(post_title)
                    and (
                        post_title.endswith("?")
                        or similarity(title, post_title) >= 0.55
                    )
                )
                if prefer_post and not is_junk_branch_title(post_title):
                    title = post_title
                    body_start = after_title_index + 1
            if is_valid_topic_title(title):
                anchors.append((index, title, body_start))
            index = body_start
            continue

        index += 1

    if not anchors:
        return _fallback_single_section(lines)

    sections: list[tuple[str, str]] = []
    for anchor_idx, (start, title, body_start) in enumerate(anchors):
        end = anchors[anchor_idx + 1][0] if anchor_idx + 1 < len(anchors) else len(lines)
        body_lines: list[str] = []
        for line_index in range(body_start, end):
            line = lines[line_index]
            trimmed = line.strip()
            if is_timestamp_line(trimmed):
                continue
            if trimmed.rstrip(":").strip().lower() == title.lower():
                continue
            body_lines.append(line)

        body = "\n".join(body_lines).strip()
        if body:
            sections.append((title, body))

    return sections


def normalize_branch_title(title: str) -> str:
    stripped = title.strip()
    if stripped == stripped.lower() and len(stripped) >= 12:
        return stripped[0].upper() + stripped[1:]
    return stripped


def is_junk_step_line(line: str) -> bool:
    stripped = line.strip().rstrip(":")
    if not stripped or is_timestamp_line(stripped):
        return True
    if is_section_label_line(stripped):
        return True
    lower = stripped.lower()
    if lower in FIELD_LABELS:
        return True
    if re.match(r"^if\s+(yes|no)\s*:?\s*$", lower):
        return True
    if re.match(r"^(new and old|old user|new user)\b", lower):
        return True
    if len(stripped) < 6 and lower in {"user id", "note", "probing", "steps"}:
        return True
    if re.match(r"^\d+[\).]\s*$", stripped):
        return True
    return False


def _dedupe_steps(steps: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for step in steps:
        key = re.sub(r"\s+", " ", step.strip().lower())
        if not key or key in seen or is_junk_step_line(step):
            continue
        seen.add(key)
        result.append(step.strip())
    return result


def extract_chained_steps(body: str) -> list[str]:
    steps: list[str] = []
    for raw in body.splitlines():
        if not re.match(r"^steps:\s*", raw, re.I):
            continue
        chain = re.sub(r"^steps:\s*", "", raw.strip(), flags=re.I)
        parts = [part.strip() for part in re.split(r"\s*->\s*", chain) if part.strip()]
        steps.extend(parts)
    return steps


def extract_resolution_steps(body: str) -> list[str]:
    steps: list[str] = []
    in_resolution = False
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        lower = line.lower()
        if re.match(r"^resolution\b", lower):
            in_resolution = True
            inline = re.sub(r"^resolution:\s*", "", line, flags=re.I).strip()
            if inline and not is_junk_step_line(inline):
                steps.append(inline)
            continue
        if in_resolution:
            if is_section_label_line(line) or lower.startswith(
                ("tagging", "if not resolved", "mandatory", "probing", "system navigation", "request consent")
            ):
                break
            match = re.match(r"^(\d+[\).]|•|-)\s*(.+)$", line)
            if match:
                steps.append(match.group(2).strip())
                continue
            if re.match(r"^if (yes|no)\b", lower):
                next_idx = body.splitlines().index(raw) + 1
                follow = ""
                if next_idx < len(body.splitlines()):
                    follow = body.splitlines()[next_idx].strip()
                if follow and not is_junk_step_line(follow):
                    steps.append(f"{line.rstrip(':')}: {follow}")
                continue
            if len(line) >= 20 and not line.endswith(":"):
                steps.append(line)
    return steps


def extract_steps_block(body: str) -> list[str]:
    """Lines under an explicit Steps / Resolution steps header."""
    steps: list[str] = []
    in_block = False
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        lower = line.lower().rstrip(":")
        if re.match(r"^(steps|resolution steps|step[\s-]?by[\s-]?step|procedure)\b", lower):
            in_block = True
            inline = re.sub(
                r"^(steps|resolution steps|step[\s-]?by[\s-]?step|procedure):\s*",
                "",
                line,
                flags=re.I,
            ).strip()
            if inline and not is_junk_step_line(inline):
                steps.append(inline)
            continue
        if in_block:
            if is_section_label_line(line) or lower.startswith(
                ("tagging", "l1", "escalation", "assign to", "mandatory", "if not resolved")
            ):
                break
            match = re.match(r"^(\d+[\).]|•|-)\s*(.+)$", line)
            if match:
                steps.append(match.group(2).strip())
                continue
            if len(line) >= 12 and not line.endswith(":") and not is_junk_step_line(line):
                steps.append(line)
    return steps


def extract_steps(body: str) -> list[str]:
    steps: list[str] = []
    steps.extend(extract_steps_block(body))
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = re.match(r"^(\d+[\).]|•|-)\s*(.+)$", line)
        if match:
            steps.append(match.group(2).strip())
            continue
        lower = line.lower()
        if lower.startswith(
            (
                "go to ",
                "login ",
                "click ",
                "open ",
                "enter ",
                "select ",
                "verify ",
                "submit ",
                "navigate ",
                "scroll ",
                "confirm ",
                "guide ",
                "ask ",
                "assign ",
                "forward ",
                "mention ",
                "took ",
                "in-case ",
                "in case ",
            )
        ):
            steps.append(line)
    steps.extend(extract_chained_steps(body))
    steps.extend(extract_resolution_steps(body))
    return _dedupe_steps(steps)[:25]


def extract_tagging(body: str) -> str | None:
    match = re.search(r"Tagging:\s*(.+)", body, re.I)
    return match.group(1).strip() if match else None


def extract_explicit_escalation(body: str) -> tuple[str, str] | None:
    """Only return L1/escalation when the manual names it explicitly — not guessed."""
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        lower = line.lower()
        if not re.match(r"^(l1\b|escalation|assign to|if not resolved)\b", lower):
            continue
        cleaned = re.sub(
            r"^(l1\s*(?:team|person)?:?|escalation:?|assign to:?|if not resolved:?)\s*",
            "",
            line,
            flags=re.I,
        ).strip()
        if len(cleaned) < 3:
            continue
        if "|" in cleaned:
            team, _, person = cleaned.partition("|")
            return team.strip(), person.strip() or DEFAULT_L1_PERSON
        return cleaned, DEFAULT_L1_PERSON
    return None


def extract_escalation(body: str) -> tuple[str, str]:
    """L1/escalation is optional for manual ingest — default to TBD unless explicit."""
    explicit = extract_explicit_escalation(body)
    if explicit:
        return explicit
    return DEFAULT_L1_TEAM, DEFAULT_L1_PERSON


def extract_documents(body: str) -> list[str]:
    docs: list[str] = []
    in_docs = False
    for raw in body.splitlines():
        line = raw.strip()
        lower = line.lower()
        if lower.startswith(("required documents", "documents:", "details need to collect", "details needs to collect", "details to be collected")):
            in_docs = True
            continue
        if in_docs and lower.startswith(("tagging", "resolution", "mandatory", "if not")):
            break
        if in_docs:
            match = re.match(r"^(?:\d+[\).]|•|-)\s*(.+)$", line)
            if match:
                docs.append(match.group(1).strip())
            elif line and not line.endswith(":"):
                docs.append(line)
    return docs[:20]


def build_keywords(title: str, body: str) -> list[str]:
    words = re.findall(r"[a-z0-9]{3,}", f"{title} {body}".lower())
    stop = {
        "the", "and", "for", "with", "from", "that", "this", "will", "your",
        "user", "account", "below", "above", "case", "team", "click", "have",
        "when", "they", "them", "into", "same", "only", "also", "been", "were",
    }
    freq: dict[str, int] = {}
    for word in words:
        if word in stop:
            continue
        freq[word] = freq.get(word, 0) + 1
    ranked = sorted(freq, key=lambda w: (-freq[w], w))
    keywords = [w for w in ranked[:6]]
    title_parts = [
        p.lower().strip("()?,")
        for p in re.split(r"[/\s]+", title)
        if len(p.strip("()?,")) > 2
    ]
    merged: list[str] = []
    seen: set[str] = set()
    for item in title_parts + keywords:
        if item and item not in seen:
            seen.add(item)
            merged.append(item)
    return merged[:10]


def extract_agent_script(body: str, title: str) -> str:
    for raw in body.splitlines():
        line = raw.strip()
        if line.lower().startswith("sir,") or line.lower().startswith("we will inform"):
            return line[:500]
    return f"I'll walk you through the steps for {title}."


def parse_section_to_branch(title: str, body: str) -> dict[str, Any]:
    """Build a KB branch — issue name and resolution steps are the primary fields."""
    display_title = normalize_branch_title(title)
    steps = extract_steps(body)
    if not steps:
        steps = [
            line.strip()
            for line in body.splitlines()
            if line.strip() and len(line.strip()) < 200 and not is_junk_step_line(line)
        ][:10]
    escalation, person = extract_escalation(body)
    branch: dict[str, Any] = {
        "branch_id": slugify(display_title),
        "branch_name": display_title,
        "trigger_keywords": build_keywords(display_title, body),
        "agent_script": extract_agent_script(body, display_title),
        "steps": steps or ["Follow the guidance in the uploaded document."],
        "escalation": escalation,
        "escalation_person": person,
        "problem_statement": display_title,
        "escalation_explicit": extract_explicit_escalation(body) is not None,
    }
    tagging = extract_tagging(body)
    if tagging:
        branch["tagging"] = tagging
    documents = extract_documents(body)
    if documents:
        branch["documents"] = documents
    return branch


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _topic_action_tokens(text: str) -> set[str]:
    lower = text.lower()
    return {word for word in ACTION_WORDS if word in lower}


def find_matching_branch(title: str, branches: list[dict]) -> dict | None:
    title_lower = title.lower().strip()
    title_actions = _topic_action_tokens(title_lower)
    for branch in branches:
        name = branch.get("branch_name", "").lower().strip()
        if title_lower == name:
            return branch
    best: dict | None = None
    best_score = 0.92
    for branch in branches:
        name = branch.get("branch_name", "")
        name_lower = name.lower()
        name_actions = _topic_action_tokens(name_lower)
        if title_actions and name_actions and title_actions != name_actions:
            continue
        score = similarity(title_lower, name_lower)
        if score > best_score:
            best_score = score
            best = branch
    return best


def merge_branch(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)
    merged["branch_name"] = existing.get("branch_name")
    merged["branch_id"] = existing.get("branch_id")
    same_title = (
        incoming.get("branch_name", "").lower().strip()
        == existing.get("branch_name", "").lower().strip()
    )
    if same_title:
        for key in ("agent_script", "tagging", "problem_statement"):
            if incoming.get(key):
                merged[key] = incoming[key]
    if incoming.get("steps"):
        merged["steps"] = _dedupe_steps([*existing.get("steps", []), *incoming["steps"]])[:25]
    if incoming.get("documents"):
        old_docs = existing.get("documents", [])
        merged["documents"] = list(dict.fromkeys([*old_docs, *incoming["documents"]]))[:20]
    explicit = incoming.get("escalation_explicit")
    if explicit:
        merged["escalation"] = incoming.get("escalation", DEFAULT_L1_TEAM)
        merged["escalation_person"] = incoming.get("escalation_person", DEFAULT_L1_PERSON)
    old_kw = set(existing.get("trigger_keywords", []))
    new_kw = incoming.get("trigger_keywords", [])
    merged["trigger_keywords"] = list(old_kw | set(new_kw))[:10]
    merged["ingested_from"] = incoming.get("ingested_from")
    merged["source_title"] = incoming.get("source_title")
    return merged


def ingest_text_into_kb(kb: dict, text: str, source_name: str = "upload") -> dict[str, Any]:
    sections = split_sections(text)
    added: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []

    branches: list[dict] = list(kb.get("branches", []))

    for title, body in sections:
        if is_junk_branch_title(title):
            skipped.append(title)
            continue
        if len(body) < 40:
            skipped.append(title)
            continue

        incoming = parse_section_to_branch(title, body)
        incoming["ingested_from"] = source_name
        incoming["source_title"] = title

        match = find_matching_branch(title, branches)
        if match:
            idx = branches.index(match)
            branches[idx] = merge_branch(match, incoming)
            updated.append(match["branch_name"])
        else:
            # Avoid duplicate branch_id
            base_id = incoming["branch_id"]
            candidate = base_id
            suffix = 2
            existing_ids = {b.get("branch_id") for b in branches}
            while candidate in existing_ids:
                candidate = f"{base_id}_{suffix}"
                suffix += 1
            incoming["branch_id"] = candidate
            branches.append(incoming)
            added.append(incoming["branch_name"])

    kb["branches"] = branches
    kb.setdefault("ingest_history", [])
    kb["ingest_history"].append(
        {
            "source": source_name,
            "sections_found": len(sections),
            "added": added,
            "updated": updated,
            "skipped": skipped,
        }
    )
    kb["ingest_history"] = kb["ingest_history"][-20:]

    return {
        "sections_found": len(sections),
        "branches_added": added,
        "branches_updated": updated,
        "branches_skipped": skipped,
        "total_branches": len(branches),
    }


def prune_junk_branches(kb: dict) -> list[str]:
    removed: list[str] = []
    kept: list[dict] = []
    for branch in kb.get("branches", []):
        name = branch.get("branch_name", "")
        if is_junk_branch_title(name) or is_placeholder_text(name):
            removed.append(name)
        else:
            kept.append(branch)
    kb["branches"] = kept
    return removed


def clean_ingest_history(kb: dict) -> None:
    history = kb.get("ingest_history", [])
    cleaned: list[dict] = []
    for entry in history:
        source = str(entry.get("source", "")).upper()
        if source.startswith("DROP_") or source.startswith("README"):
            continue
        added = [name for name in entry.get("added", []) if not is_junk_branch_title(name)]
        if not added and not entry.get("updated"):
            continue
        cleaned.append({**entry, "added": added})
    kb["ingest_history"] = cleaned[-20:]


def load_kb(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_kb(path: Path, kb: dict) -> None:
    # Write-then-rename so a crash or concurrent reader never sees a half-written KB.
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)
        f.write("\n")
    temp.replace(path)


def ingest_file(path: Path, data: bytes, filename: str) -> dict[str, Any]:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        text = extract_text_from_pdf(data)
    elif lower.endswith((".txt", ".text", ".md")):
        text = data.decode("utf-8", errors="replace")
    else:
        raise ValueError("Unsupported file type. Upload .txt or .pdf")

    if not text.strip():
        raise ValueError("No text could be extracted from the file")

    with STORE_LOCK:
        kb = load_kb(path)
        stats = ingest_text_into_kb(kb, text, source_name=filename)
        save_kb(path, kb)
    return stats


INBOX_EXTENSIONS = {".txt", ".text", ".md", ".pdf"}
INBOX_DIRNAME = "inbox"
PROCESSED_DIRNAME = "processed"


def inbox_path(kb_json_path: Path) -> Path:
    return kb_json_path.parent / INBOX_DIRNAME


def processed_path(kb_json_path: Path) -> Path:
    return kb_json_path.parent / PROCESSED_DIRNAME


def ensure_inbox_dirs(kb_json_path: Path) -> tuple[Path, Path]:
    inbox = inbox_path(kb_json_path)
    processed = processed_path(kb_json_path)
    inbox.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    return inbox, processed


def _unique_processed_path(processed_dir: Path, filename: str) -> Path:
    candidate = processed_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while True:
        candidate = processed_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def scan_inbox(kb_json_path: Path) -> dict[str, Any]:
    """Ingest all .txt/.pdf files from knowledge/{type}/inbox/ into unified_knowledge.json."""
    inbox, processed = ensure_inbox_dirs(kb_json_path)
    files_ingested: list[dict[str, Any]] = []
    files_failed: list[dict[str, str]] = []
    files_skipped: list[str] = []

    for file_path in sorted(inbox.iterdir()):
        if not file_path.is_file():
            continue

        suffix = file_path.suffix.lower()
        if suffix not in INBOX_EXTENSIONS:
            files_skipped.append(file_path.name)
            continue

        stem_upper = file_path.stem.upper()
        if stem_upper.startswith("DROP_") or stem_upper.startswith("README"):
            files_skipped.append(file_path.name)
            continue

        try:
            data = file_path.read_bytes()
            if file_path.suffix.lower() in {".txt", ".text", ".md"}:
                preview = data.decode("utf-8", errors="replace")
                if is_placeholder_text(preview):
                    files_skipped.append(file_path.name)
                    continue
            stats = ingest_file(kb_json_path, data, file_path.name)
            dest = _unique_processed_path(processed, file_path.name)
            file_path.rename(dest)
            files_ingested.append(
                {
                    "file": file_path.name,
                    "moved_to": str(dest.relative_to(kb_json_path.parent)),
                    **stats,
                }
            )
        except Exception as exc:
            files_failed.append({"file": file_path.name, "error": str(exc)})

    with STORE_LOCK:
        kb = load_kb(kb_json_path)
        removed = prune_junk_branches(kb)
        if removed:
            clean_ingest_history(kb)
            save_kb(kb_json_path, kb)
    return {
        "inbox": str(inbox),
        "processed": str(processed),
        "files_ingested": files_ingested,
        "files_failed": files_failed,
        "files_skipped": files_skipped,
        "junk_removed": removed,
        "total_branches": len(kb.get("branches", [])),
    }


def scan_all_inboxes(kb_paths: dict[str, Path]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for caller_type, path in kb_paths.items():
        summary[caller_type] = scan_inbox(path)
    return summary
