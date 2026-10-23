"""Graph builder: turns validated results into spider-network nodes and edges.

Every edge comes from a relationship that exists in the analysis - a keyword occurring in
a passage, a finding quoting a passage, a recommendation addressing a finding, two
findings that cite the same contradiction pair. Nothing is wired up for looks.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.analysis.types import FindingDraft, KeywordDraft, RecommendationDraft
from app.core.ids import new_id

# finding kind -> graph node type
NODE_TYPE_BY_KIND = {
    "subject": "topic", "purpose": "topic", "central_idea": "topic", "argument": "claim",
    "conclusion": "claim", "structure": "section", "strength": "evidence",
    "fact": "fact", "date": "fact", "person": "fact", "definition": "evidence",
    "statistic": "fact", "decision": "claim", "action_item": "claim", "critical_statement": "claim",
    "keyword_concept": "topic", "writing_issue": "writing_issue", "logic_gap": "contradiction",
    "unsupported_claim": "claim", "contradiction": "contradiction", "ambiguous_statement": "claim",
    "overreaching_conclusion": "claim", "recommendation": "recommendation", "clarifying_question": "question",
}

MAJOR_KINDS = {"contradiction", "unsupported_claim", "overreaching_conclusion", "logic_gap"}


def _node(node_type: str, label: str, **kwargs: Any) -> dict[str, Any]:
    return {
        "id": kwargs.pop("id", None) or new_id(),
        "node_type": node_type,
        "label": label[:280],
        "ref_id": kwargs.pop("ref_id", None),
        "passage_id": kwargs.pop("passage_id", None),
        "weight": kwargs.pop("weight", 1.0),
        "payload": kwargs.pop("payload", {}),
    }


def _edge(source: str, target: str, relation: str, label: str = "", strength: float = 1.0) -> dict[str, Any]:
    return {
        "id": new_id(), "source_node_id": source, "target_node_id": target,
        "relation": relation, "label": label[:160], "strength": strength,
    }


def build_graph(
    *,
    title: str,
    sections: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    keywords: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    passages_by_id: dict[str, Any],
    finding_key_map: dict[str, str],
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Event sequence lookup: which crawl step revealed a given draft key.
    seq_by_ref: dict[str, int] = {}
    first_investigation_seq = 0
    for event in events:
        for ref in event.get("finding_refs") or []:
            seq_by_ref[ref] = event["seq"]
        if event["stage"] == "investigation" and not first_investigation_seq:
            first_investigation_seq = event["seq"]
    keyword_seq = next((e["seq"] for e in events if e.get("keyword_count")), first_investigation_seq or 1)
    completion_seq = next((e["seq"] for e in events if e["stage"] == "completion"), events[-1]["seq"] if events else 1)

    spider = _node("spider", "SPIDER AI", payload={"note": "Central investigator node"})
    document = _node("document", title, payload={"reveal_seq": 1, "reveal_after": 1})
    nodes += [spider, document]
    edges.append(_edge(spider["id"], document["id"], "contains", "investigating", 2.0))

    # Sections become the first branches during initial exploration.
    for section in sections[:24]:
        node = _node("section", section["title"], passage_id=section.get("passage_id"),
                     payload={"reveal_after": 2, "level": section.get("level", 1), "index": section.get("index", 0)})
        nodes.append(node)
        edges.append(_edge(spider["id"], node["id"], "contains", "section", 1.0))

    # Findings -> nodes, wired to their evidence passages and to the spider.
    finding_node_by_id: dict[str, str] = {}
    passage_nodes: dict[str, str] = {}
    # A quotation becomes its own branch node only where it carries structural meaning:
    # a passage cited by two or more findings, or evidence under a claim/contradiction.
    # Otherwise the quotation travels inside the finding node, so the web stays readable.
    citation_counts: dict[str, int] = {}
    for finding in findings:
        for item in finding.get("evidence", []):
            citation_counts[item["passage_id"]] = citation_counts.get(item["passage_id"], 0) + 1

    def evidence_is_node(finding: dict[str, Any], passage_id: str) -> bool:
        return citation_counts.get(passage_id, 0) >= 2 or NODE_TYPE_BY_KIND.get(finding["kind"]) in (
            "claim", "contradiction",
        )

    for finding in findings:
        node_type = NODE_TYPE_BY_KIND.get(finding["kind"], "evidence")
        draft_key = (finding.get("extra") or {}).get("draft_key") or ""
        reveal_after = seq_by_ref.get(draft_key, first_investigation_seq or 1)
        weight = 1.6 if finding["severity"] == "major" else 1.2 if finding["severity"] == "minor" else 1.0
        node = _node(
            node_type, finding["title"], ref_id=finding["id"], passage_id=finding.get("primary_passage_id"),
            weight=weight,
            payload={
                "kind": finding["kind"], "category": finding.get("category"), "severity": finding["severity"],
                "body": finding.get("body", "")[:600], "reveal_after": reveal_after, "draft_key": draft_key,
            },
        )
        nodes.append(node)
        finding_node_by_id[finding["id"]] = node["id"]
        edges.append(_edge(spider["id"], node["id"], "derived_from", finding["kind"], weight))

        # Evidence passages get their own evidence nodes, connected to the claim they support.
        for item in finding.get("evidence", []):
            passage = passages_by_id.get(item["passage_id"])
            if passage is None or not evidence_is_node(finding, item["passage_id"]):
                continue
            passage_key = f"{item['passage_id']}::{item['quote'][:24]}"
            passage_node = passage_nodes.get(passage_key)
            if passage_node is None:
                passage_node = _node(
                    "evidence",
                    (item["quote"][:120] or passage.text[:120]),
                    passage_id=item["passage_id"],
                    payload={
                        "quote": item["quote"], "char_start": item.get("char_start"), "char_end": item.get("char_end"),
                        "page_number": getattr(passage, "page_number", None), "validation": item.get("validation"),
                        "reveal_after": reveal_after,
                    },
                )
                nodes.append(passage_node)
                passage_nodes[passage_key] = passage_node["id"]
            relation = "supports" if node_type in ("claim", "contradiction", "fact") else "occurs_in"
            edges.append(_edge(passage_node["id"] if isinstance(passage_node, dict) else passage_node,
                               node["id"], relation, item.get("validation", "verbatim"), 1.0))

        # Contradictions connect the two passages they were found between.
        if finding["kind"] == "contradiction":
            cited = [e["passage_id"] for e in finding.get("evidence", [])][:2]
            if len(cited) == 2:
                other = [f for f in findings if f["id"] != finding["id"] and cited[1] in (f.get("passage_ids") or [])]
                for related in other[:2]:
                    related_node = finding_node_by_id.get(related["id"])
                    if related_node:
                        edges.append(_edge(node["id"], related_node, "contradicts", "same term, opposite statements", 1.4))

    # Keywords: connect to the spider, to the findings that quote where they occur, and to
    # genuinely co-occurring keywords.
    keyword_nodes: dict[str, str] = {}
    findings_by_passage: dict[str, list[str]] = defaultdict(list)
    for finding in findings:
        for item in finding.get("evidence", []):
            findings_by_passage[item["passage_id"]].append(finding["id"])

    for keyword in keywords:
        node = _node(
            "keyword", keyword["term"], ref_id=keyword["id"],
            passage_id=(keyword.get("passage_ids") or [None])[0],
            weight=1.0 + min(2.0, (keyword.get("occurrences", 0)) / 12),
            payload={
                "category": keyword["category"], "occurrences": keyword.get("occurrences", 0),
                "in_document": keyword.get("in_document", True), "explanation": (keyword.get("explanation") or "")[:600],
                "reveal_after": keyword_seq,
            },
        )
        nodes.append(node)
        keyword_nodes[keyword["id"]] = node["id"]
        edges.append(_edge(spider["id"], node["id"], "mentions", keyword["category"], 1.0))
        # One branch per keyword to the finding that leans on it most, instead of one
        # branch per passage (which turned the web into a hairball).
        linked: list[str] = []
        for passage_id in (keyword.get("passage_ids") or []):
            linked.extend(findings_by_passage.get(passage_id, []))
        linked = list(dict.fromkeys(linked))[:2]
        for finding_id in linked:
            target = finding_node_by_id.get(finding_id)
            if target:
                edges.append(_edge(node["id"], target, "occurs_in", "appears in this evidence", 0.6))

    # Real co-occurrence between keywords (they share at least two passages).
    shared = defaultdict(list)
    for keyword in keywords:
        for passage_id in (keyword.get("passage_ids") or []):
            shared[passage_id].append(keyword["id"])
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for passage_id, ids in shared.items():
        for i, first in enumerate(ids):
            for second in ids[i + 1:]:
                pair = tuple(sorted((first, second)))
                pair_counts[pair] += 1
    for (first_id, second_id), count in sorted(pair_counts.items(), key=lambda kv: -kv[1])[:24]:
        if count >= 2 and first_id in keyword_nodes and second_id in keyword_nodes:
            edges.append(
                _edge(keyword_nodes[first_id], keyword_nodes[second_id], "mentions", f"in {count} passages together", 0.8)
            )

    # Recommendations point at the finding they address.
    for recommendation in recommendations:
        target_id = recommendation.get("finding_id")
        node = _node(
            "recommendation", (recommendation.get("rationale") or "")[:200] or "Recommendation",
            ref_id=recommendation["id"], passage_id=recommendation.get("passage_id"),
            payload={"kind": recommendation.get("kind", "revision"), "reveal_after": completion_seq,
                     "suggested_revision": (recommendation.get("suggested_revision") or "")[:800]},
        )
        nodes.append(node)
        if target_id and target_id in finding_node_by_id:
            edges.append(_edge(node["id"], finding_node_by_id[target_id], "suggests", "addresses this finding", 1.0))
        else:
            edges.append(_edge(spider["id"], node["id"], "suggests", "general improvement", 0.8))

    # Deduplicate edges (same pair + relation), keep the strongest.
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in edges:
        key = (edge["source_node_id"], edge["target_node_id"], edge["relation"])
        current = best.get(key)
        if current is None or edge["strength"] > current["strength"]:
            best[key] = edge
    edges = list(best.values())

    # Never point an edge at a missing node.
    node_ids = {node["id"] for node in nodes}
    edges = [edge for edge in edges if edge["source_node_id"] in node_ids and edge["target_node_id"] in node_ids]
    return nodes, edges


def summarise_nodes(nodes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for node in nodes:
        counts[node["node_type"]] += 1
    return dict(counts)
