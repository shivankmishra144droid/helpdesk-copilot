"""Generate every knowledge/benchmark data file for the demo from demo_content.py.

Deterministic: running it twice produces identical files. Run from the repo root:

    py -3 scripts/generate_demo_data.py

Then rebuild derived artefacts:

    py -3 scripts/build_domain_dictionary.py
    py -3 scripts/train_intent_classifier.py
    py -3 scripts/train_outlier.py
    py -3 scripts/train_ranker.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo_content as dc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = ROOT / "backend" / "knowledge"
BENCHMARKS = ROOT / "benchmarks"

CALLERS = {
    "seller": (dc.SELLER_CATEGORIES, dc.SELLER_BRANCHES, "Seller"),
    "buyer": (dc.BUYER_CATEGORIES, dc.BUYER_BRANCHES, "Buyer"),
}


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def iter_branches(caller: str):
    categories, branches, _label = CALLERS[caller]
    for cat_id, cat_name, team, role in categories:
        for spec in branches[cat_id]:
            yield (cat_id, cat_name, team, role, *spec)


def build_kb(caller: str) -> dict:
    _categories, _branches, label = CALLERS[caller]
    out = []
    for cat_id, cat_name, team, role, bid, name, keywords, script, steps, docs, _queries in iter_branches(caller):
        out.append(
            {
                "branch_id": bid,
                "branch_name": name,
                "trigger_keywords": keywords,
                "agent_script": script,
                "steps": steps,
                "documents": docs,
                "escalation": team,
                "escalation_person": role,
                "tagging": f"{label} → {cat_name} → {name}",
                "topic_category": cat_id,
                "description": script,
            }
        )
    return {
        "kb_id": f"{caller}-knowledge-001",
        "kb_name": f"{dc.PORTAL} {label} Knowledge Base",
        "problem_id": f"{caller.upper()}-001",
        "problem_name": f"{label} Support",
        "category": label,
        "caller_type": label,
        "description": f"Synthetic {caller} support knowledge for the {dc.PORTAL} demo.",
        "ingest_history": [],
        "synonym_groups": dc.SYNONYM_GROUPS[caller],
        "branches": out,
    }


def build_taxonomy() -> dict:
    taxonomy: dict = {
        "portal": dc.PORTAL,
        "categories": {},
        "inference_rules": {},
        "category_aliases": {},
        # Used when no inference rule matches a new branch.
        "fallback_category": {"seller": "profile_kyc", "buyer": "orders_delivery"},
    }
    for caller, (categories, branches, _label) in CALLERS.items():
        taxonomy["categories"][caller] = [{"id": c[0], "name": c[1]} for c in categories]
        rules = []
        for cat_id, *_rest in categories:
            phrases: list[str] = []
            for spec in branches[cat_id]:
                phrases.extend(spec[2][:3])
            rules.append([cat_id, list(dict.fromkeys(p.lower() for p in phrases))])
        taxonomy["inference_rules"][caller] = rules
        for cat_id, cat_name, *_rest in categories:
            # Lets LLM drafts / FAQ taxonomy use display names as well as ids.
            taxonomy["category_aliases"][cat_name.lower()] = cat_id
    return taxonomy


def build_resolution_examples() -> dict:
    entries = []
    for caller in CALLERS:
        for cat_id, cat_name, team, role, bid, name, keywords, script, steps, docs, _q in iter_branches(caller):
            entries.append(
                {
                    "issue_id": f"{caller[:1].upper()}-{len(entries) + 1:03d}",
                    "issue_name": name,
                    "category": cat_id,
                    "problem_statement": f"{caller.title()} reports: {name.lower()}.",
                    "policy": f"{dc.PORTAL} support guideline for {cat_name.lower()}: {script}",
                    "resolution_steps": steps,
                    "required_documents": docs,
                    "l1_team": team,
                    "l1_person": role,
                    "sources": ["synthetic"],
                }
            )
    return {
        "metadata": {
            "name": f"{dc.PORTAL} resolution examples",
            "description": "Synthetic few-shot examples used to draft supervisor resolutions.",
            "sources": ["synthetic"],
            "total_entries": len(entries),
        },
        "entries": entries,
    }


def build_faq() -> dict:
    entries = []
    for index, (user_type, category, question, short_answer, steps, phrases) in enumerate(dc.FAQ, start=1):
        entries.append(
            {
                "id": f"faq-{index:03d}",
                "sourceId": f"faq-{index:03d}",
                "userType": user_type,
                "audience": {"userType": user_type},
                "topic": question,
                "taxonomy": {"categoryL1": category, "topic": question},
                "content": {
                    "question": question,
                    "shortAnswer": short_answer,
                    "answer": short_answer + "\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1)),
                    "steps": steps,
                },
                "queryUnderstanding": {"searchPhrases": phrases},
                "tags": phrases,
                "metadata": {"moduleOwner": "Help Centre Content Team"},
            }
        )
    return {"version": "demo-1", "selection": "synthetic", "entries": entries}


def _typo(text: str, rng: random.Random) -> str:
    """Drop or swap one character in the longest word (realistic agent typo)."""
    words = text.split()
    index = max(range(len(words)), key=lambda i: len(words[i]))
    word = words[index]
    pos = rng.randrange(1, len(word) - 1)
    if rng.random() < 0.5:
        word = word[:pos] + word[pos + 1 :]
    else:
        word = word[: pos - 1] + word[pos] + word[pos - 1] + word[pos + 1 :]
    words[index] = word
    return " ".join(words)


def build_benchmark() -> dict:
    rng = random.Random(42)
    cases = []
    for caller in CALLERS:
        for cat_id, _cn, _t, _r, bid, name, _k, script, _s, _d, queries in iter_branches(caller):
            for style, query in [("paraphrase", queries[0]), ("paraphrase", queries[1]), ("typo", _typo(queries[0], rng))]:
                cases.append(
                    {
                        "id": f"case-{len(cases) + 1:03d}",
                        "query": query,
                        "caller_type": caller,
                        "expected_branch_id": bid,
                        "expected_branch_name": name,
                        "expected_category": cat_id,
                        "query_style": style,
                    }
                )
    return {
        "version": "demo-1",
        "description": "Hand-written caller phrasings (not branch names) plus one synthetic typo variant per branch.",
        "case_count": len(cases),
        "cases": cases,
    }


def main() -> None:
    for caller, (categories, _b, _l) in CALLERS.items():
        write_json(KNOWLEDGE / caller / "unified_knowledge.json", build_kb(caller))
        write_json(KNOWLEDGE / caller / "categories.json", {"categories": [{"id": c[0], "name": c[1]} for c in categories]})
        for sub in ("inbox", "processed"):
            folder = KNOWLEDGE / caller / sub
            folder.mkdir(parents=True, exist_ok=True)
        (KNOWLEDGE / caller / "inbox" / "DROP_TXT_OR_PDF_HERE.txt").write_text(
            "Drop .txt or .pdf support notes here; they are parsed into this knowledge base automatically.\n",
            encoding="utf-8",
            newline="\n",
        )
        (KNOWLEDGE / caller / "processed" / ".gitkeep").write_text("", encoding="utf-8")
    write_json(KNOWLEDGE / "taxonomy.json", build_taxonomy())
    write_json(KNOWLEDGE / "resolution_examples.json", build_resolution_examples())
    write_json(KNOWLEDGE / "lms" / "faq.json", build_faq())
    write_json(KNOWLEDGE / "query_abbreviations.json", {"abbreviations": {k: v for k, v in dc.ABBREVIATIONS.items() if k != v}})
    write_json(
        KNOWLEDGE / "query_typo_phrases.json",
        {
            "version": "1",
            "description": "Phrase-level typo corrections for demo query correction.",
            "phrases": dc.TYPO_PHRASES,
            "protected_phrases": dc.PROTECTED_PHRASES,
        },
    )
    write_json(BENCHMARKS / "benchmark_queries.json", build_benchmark())
    seller = sum(len(v) for v in dc.SELLER_BRANCHES.values())
    buyer = sum(len(v) for v in dc.BUYER_BRANCHES.values())
    print(f"Generated {seller} seller + {buyer} buyer branches, {len(dc.FAQ)} FAQ entries.")


if __name__ == "__main__":
    main()
