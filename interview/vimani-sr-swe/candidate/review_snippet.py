"""Part 4: Code review.

Part of the AI layer: when a residente submits a purchase requisition from the
field, an LLM suggests a cost code for each line so they don't have to search
the catalog by hand. A teammate opened this PR and says it "works on the demo
project". Review it as you would a real pull request.
"""

import json

MISC_CODE = "99.99"

_cache = {}


def classify_requisition_lines(llm, lines, catalog_codes):
    """lines: [{"id": ..., "description": ..., "quantity": ..., "amount": ...}]"""
    results = []
    for line in lines:
        if line["description"] in _cache:
            results.append(_cache[line["description"]])
            continue

        prompt = (
            "You are a construction cost expert. Pick the best cost code for "
            "this item and answer as JSON {\"code\": ..., \"confidence\": ...}.\n"
            "Item: " + line["description"] + "\n"
            "Codes: " + str(catalog_codes)
        )
        try:
            answer = json.loads(llm.complete(prompt))
            code = answer["code"]
            confidence = float(answer.get("confidence", 1.0))
        except:
            code = MISC_CODE
            confidence = 1.0

        if confidence > 0.3:
            line["cost_code"] = code
        else:
            line["cost_code"] = MISC_CODE
        line["amount"] = float(line["amount"])

        _cache[line["description"]] = line
        results.append(line)
    return results
