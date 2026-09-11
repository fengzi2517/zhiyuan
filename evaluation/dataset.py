"""Validate frozen labels and map verbatim evidence to actual application chunks."""

import json
from pathlib import Path

from app.chunker import chunk_units
from app.parser import parse_file_units


def load_dataset(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _required_text(record, key):
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be nonempty text")
    return value


def prepare_dataset(data):
    _required_text(data, "version")
    documents = data.get("documents")
    questions = data.get("questions")
    if not isinstance(documents, list) or not documents:
        raise ValueError("documents must be a nonempty list")
    if not isinstance(questions, list) or not questions:
        raise ValueError("questions must be a nonempty list")
    known_docs, chunks = {}, []
    for doc in documents:
        doc_id = _required_text(doc, "id")
        if doc_id in known_docs:
            raise ValueError(f"duplicate document: {doc_id}")
        title = _required_text(doc, "title")
        content = _required_text(doc, "text")
        known_docs[doc_id] = doc
        units = parse_file_units(title, content.encode("utf-8"))
        for chunk in chunk_units(units):
            chunks.append({
                "chunk_id": len(chunks) + 1, "doc_id": doc_id, "title": title,
                "content": chunk.content, "section": chunk.section,
                "start_char": chunk.start_char, "end_char": chunk.end_char,
            })
    seen, groups, document_splits, prepared = set(), {}, {}, []
    for question in questions:
        qid = _required_text(question, "id")
        if qid in seen:
            raise ValueError(f"duplicate question: {qid}")
        seen.add(qid)
        group = _required_text(question, "group")
        _required_text(question, "query")
        _required_text(question, "category")
        split = question.get("split")
        if split not in ("dev", "test"):
            raise ValueError(f"invalid split: {qid}")
        if group in groups and groups[group] != split:
            raise ValueError(f"group leaks across splits: {group}")
        groups[group] = split
        evidence = question.get("evidence")
        if not isinstance(evidence, list):
            raise ValueError(f"evidence must be a list: {qid}")
        if evidence:
            _required_text(question, "answer")
        elif question.get("category") != "unanswerable" or question.get("answer"):
            raise ValueError(f"empty evidence must be labeled unanswerable: {qid}")
        if evidence and question["category"] == "unanswerable":
            raise ValueError(f"unanswerable question has evidence: {qid}")
        gold = set()
        for ref in evidence:
            doc_id = _required_text(ref, "doc_id")
            quote = _required_text(ref, "quote")
            if doc_id not in known_docs or quote not in known_docs[doc_id]["text"]:
                raise ValueError(f"evidence missing from document: {qid}")
            if doc_id in document_splits and document_splits[doc_id] != split:
                raise ValueError(f"document labels leak across splits: {doc_id}")
            document_splits[doc_id] = split
            matched = {chunk["chunk_id"] for chunk in chunks
                       if chunk["doc_id"] == doc_id and quote in chunk["content"]}
            if not matched:
                raise ValueError(f"evidence not contained in a production chunk: {qid}")
            gold.update(matched)
        prepared.append({**question, "gold_ids": sorted(gold)})
    return chunks, prepared
