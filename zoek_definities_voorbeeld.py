# Voorbeeld: simpele zoekfunctie voor het definitiebestand
import json
from pathlib import Path

CURATED = json.loads(Path("ho_definities_curated.json").read_text(encoding="utf-8"))["entries"]
INDEX = [json.loads(line) for line in Path("ho_definities_index.jsonl").read_text(encoding="utf-8").splitlines()]

def search_definitions(query, limit=10):
    q = query.lower()
    results = []
    for source_name, rows, weight in [("curated", CURATED, 3), ("index", INDEX, 1)]:
        for row in rows:
            haystack = " ".join(str(row.get(k, "")) for k in ["term", "definition", "aliases", "related_fields", "available_in_datasets", "tags"]).lower()
            score = 0
            for token in q.split():
                if token in haystack:
                    score += weight
                if token in str(row.get("term", "")).lower():
                    score += 2 * weight
            if score:
                results.append((score, source_name, row))
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:limit]

if __name__ == "__main__":
    for score, source, row in search_definitions("waar vind ik internationale studenten"):
        print(f"[{source} | score={score}] {row.get('term')}")
        print(row.get('definition', '')[:400])
        print("Datasets:", row.get('available_in_datasets'))
        print("Fields:", row.get('related_fields') or row.get('related_field_names'))
        print()
