#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — analysis_helpers/llm_utils.py

Pure helper functions for LLM response processing:
- JSON extraction from LLM text responses
- Response normalization (field mapping, type coercion)
- Structured comment building for bet records

No DB, no orchestration, no LLM calls, no global state.
Extracted from agent_handoff_v7.py Step 4 (2026-04-14).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict


def extract_json_object(text: str) -> Dict[str, Any]:
    """
    Extract a JSON object from text that may contain markdown code blocks
    or raw JSON embedded in prose.
    """
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
    if m:
        return json.loads(m.group(1))

    start = text.find("{")
    if start == -1:
        raise ValueError("JSON not found")

    depth = 0
    in_str = False
    esc = False
    end = None
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            esc = not esc if ch == "\\" and not esc else False
            if ch == '"' and not esc:
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end is None:
        raise ValueError("JSON end not found")
    return json.loads(text[start:end])


def normalize_response(rec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize LLM response fields: map market names to display labels,
    coerce types, ensure required fields exist.
    """
    if rec.get("decision") == "PASS" or rec.get("market") in ("pass", None) or rec.get("signal_type") == "Pass":
        rec.update({"market": "pass", "market_label": "PASS", "decision": "PASS", "signal_type": "Pass"})
        rec["confidence"] = int(rec.get("confidence", 0) or 0)
        return rec
    label_map = {"home": "П1", "draw": "X", "away": "П2", "btts_yes": "Обе забьют — Да", "btts_no": "Обе забьют — Нет"}
    rec.setdefault("market_label", label_map.get(rec.get("market"), rec.get("market")))
    rec["confidence"] = int(rec.get("confidence", 0) or 0)
    rec["lineup_data_available"] = bool(rec.get("lineup_data_available", False))
    return rec


def build_structured_comment(rec: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a structured comment object for a bet recommendation.
    """
    rule = None
    if rec.get("live_rule_family"):
        rule = rec.get("live_rule_family")
    elif payload.get("ba_rule"):
        rule = payload.get("ba_rule")
    elif rec.get("strategy_family"):
        rule = rec.get("strategy_family")

    return {
        "rule": rule,
        "edge": rec.get("ev"),
        "model_prob": rec.get("our_probability"),
        "market_prob": rec.get("market_probability"),
        "confidence": rec.get("confidence"),
        "reasons_confirmed": rec.get("confirmed_facts", []),
        "reasons_unconfirmed": rec.get("unconfirmed", []),
        "market_error_reason": rec.get("market_error"),
    }
