"""
Build related_articles.json — cross-reference graph of insurance policy articles.
Extracts 제X조, 별표N, 제X관 references from enriched JSON files.

Handles duplicate 조 numbers across 주계약/특약 by using compound keys:
  주계약:제3조, 특약(암진단):제3조, etc.
The 관 field disambiguates within a type.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

BASE = Path(r"C:\Users\이창현\Documents\Projects\creaiit_ainos")
ENRICHED_DIR = BASE / "data" / "약관_enriched"
OUTPUT_PATH = BASE / "data" / "agent_data" / "related_articles.json"

# Regex patterns for cross-references
RE_JO = re.compile(r"제\s*(\d+)\s*조")
RE_BYEOL = re.compile(r"[<]?별표\s*(\d+)[>]?")
RE_GWAN = re.compile(r"제\s*(\d+)\s*관")


def make_key(section: dict) -> str:
    """Create a unique key for a section within a product.
    Uses type prefix to distinguish 주계약 vs 특약 articles."""
    jo = section["조"]
    stype = section.get("type", "")
    gwan = section.get("관", "")
    if stype == "주계약":
        return jo  # 주계약 articles keep simple key
    else:
        # For 특약, include 관 name to disambiguate
        # Extract short 관 name (remove 제X관 prefix)
        gwan_short = re.sub(r"^제\d+관\s*", "", gwan).strip()
        if gwan_short:
            return f"특약({gwan_short}):{jo}"
        return f"특약:{jo}"


def extract_references(text: str, self_jo: str) -> dict:
    """Extract all cross-references from article text.
    Returns dict with 'jo', 'byeoltable', 'gwan' lists."""
    refs = {
        "jo": set(),       # 제X조 references
        "byeol": set(),    # 별표N references
        "gwan": set(),     # 제X관 references
    }

    for m in RE_JO.finditer(text):
        ref = f"제{m.group(1)}조"
        if ref != self_jo:
            refs["jo"].add(ref)

    for m in RE_BYEOL.finditer(text):
        refs["byeol"].add(f"별표{m.group(1)}")

    for m in RE_GWAN.finditer(text):
        refs["gwan"].add(f"제{m.group(1)}관")

    return refs


def build_graph():
    result = {}
    stats = {
        "products": 0,
        "total_articles": 0,
        "articles_with_refs": 0,
        "total_ref_edges": 0,
        "total_referenced_by_edges": 0,
        "byeoltable_refs": 0,
    }

    files = sorted(ENRICHED_DIR.glob("*.json"))
    stats["products"] = len(files)

    for fpath in files:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)

        prod_code = data["prodCode"]
        product_graph = {}

        # Track which keys map to which simple 제X조 for referenced_by resolution
        # Within 주계약, 제X조 references resolve to 주계약 articles
        jo_to_keys = defaultdict(list)  # "제3조" -> ["제3조", "특약(...)::제3조"]

        # First pass: build references_to for each article
        for sec in data["sections"]:
            jo = sec["조"]
            key = make_key(sec)
            text = sec.get("text", "") or ""
            title = sec.get("title", "")
            art_type = sec.get("type", "")

            raw_refs = extract_references(text, jo)
            all_refs = sorted(raw_refs["jo"] | raw_refs["byeol"] | raw_refs["gwan"])

            product_graph[key] = {
                "title": title,
                "type": art_type,
                "관": sec.get("관", ""),
                "references_to": all_refs,
                "referenced_by": [],
            }

            jo_to_keys[jo].append(key)
            stats["total_articles"] += 1
            if all_refs:
                stats["articles_with_refs"] += 1
            stats["total_ref_edges"] += len(all_refs)
            stats["byeoltable_refs"] += sum(1 for r in all_refs if r.startswith("별표"))

        # Second pass: compute referenced_by
        # A "제X조" reference in a 주계약 article -> targets same-type 주계약 제X조
        # A "제X조" reference in a 특약 article -> could target same 관/특약 scope
        for src_key, info in product_graph.items():
            src_type = info["type"]
            src_gwan = info["관"]

            for ref in info["references_to"]:
                if ref.startswith("별표") or ref.startswith("제") and "관" in ref:
                    continue  # 별표 and 관 don't have article entries

                # ref is like "제X조" — find target(s)
                target_keys = jo_to_keys.get(ref, [])
                if not target_keys:
                    continue

                # Try to find same-type match first
                same_type = [k for k in target_keys if product_graph[k]["type"] == src_type]
                # For 특약, try same 관 first
                if src_type == "특약":
                    same_gwan = [k for k in same_type if product_graph[k]["관"] == src_gwan]
                    if same_gwan:
                        for tk in same_gwan:
                            product_graph[tk]["referenced_by"].append(src_key)
                            stats["total_referenced_by_edges"] += 1
                        continue

                if same_type:
                    for tk in same_type:
                        product_graph[tk]["referenced_by"].append(src_key)
                        stats["total_referenced_by_edges"] += 1
                elif len(target_keys) == 1:
                    # Only one match, use it
                    product_graph[target_keys[0]]["referenced_by"].append(src_key)
                    stats["total_referenced_by_edges"] += 1
                else:
                    # Ambiguous — add to 주계약 version if exists (most references
                    # from 특약 to "제X조" refer to 주계약 articles)
                    main_keys = [k for k in target_keys if product_graph[k]["type"] == "주계약"]
                    if main_keys:
                        for tk in main_keys:
                            product_graph[tk]["referenced_by"].append(src_key)
                            stats["total_referenced_by_edges"] += 1

        # Sort and deduplicate referenced_by lists
        for info in product_graph.values():
            info["referenced_by"] = sorted(set(info["referenced_by"]))

        result[prod_code] = product_graph

    return result, stats


def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    graph, stats = build_graph()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)

    print("=== related_articles.json build complete ===")
    print(f"Output: {OUTPUT_PATH}")
    print(f"Products:                {stats['products']}")
    print(f"Total articles:          {stats['total_articles']}")
    print(f"Articles with refs:      {stats['articles_with_refs']}")
    print(f"Total references_to:     {stats['total_ref_edges']}")
    print(f"  - 별표 references:     {stats['byeoltable_refs']}")
    print(f"Total referenced_by:     {stats['total_referenced_by_edges']}")

    # Top referenced articles
    print(f"\n--- Top 10 most-referenced articles (by referenced_by count) ---")
    ranking = []
    for prod, articles in graph.items():
        for art_id, info in articles.items():
            if info["referenced_by"]:
                ranking.append((prod, art_id, info["title"], len(info["referenced_by"])))
    ranking.sort(key=lambda x: -x[3])
    for prod, art_id, title, count in ranking[:10]:
        print(f"  {prod} {art_id} ({title[:30]}): {count}")

    # Articles with most outgoing references
    print(f"\n--- Top 10 articles with most outgoing references ---")
    outgoing = []
    for prod, articles in graph.items():
        for art_id, info in articles.items():
            if info["references_to"]:
                outgoing.append((prod, art_id, info["title"], len(info["references_to"])))
    outgoing.sort(key=lambda x: -x[3])
    for prod, art_id, title, count in outgoing[:10]:
        print(f"  {prod} {art_id} ({title[:30]}): {count}")

    # Sample entry
    print("\n--- Sample entry (KL0420, 제3조 주계약) ---")
    sample = graph.get("KL0420", {}).get("제3조", {})
    print(json.dumps({"KL0420": {"제3조": sample}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
