"""
별표(appendix) body content parser for KB Life insurance product raw text files.

Extracts appendix bodies from 18 insurance product text files and saves
structured JSON output per product.

Algorithm:
1. Read each .txt file
2. Find all <별표N> header lines
3. Distinguish TOC entries vs body entries:
   - Body entries have substantial content (>= 15 non-empty lines) before the next header
   - TOC entries are clustered together with minimal content
4. Extract appendix number, title, body text
5. Track insurance type (주계약 or specific 특약 name) via number-reset detection
6. Classify as "structured" or "text"
"""

import json
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(r"C:\Users\이창현\Documents\Projects\creaiit_ainos")
TEXT_DIR = BASE_DIR / "data" / "약관_텍스트"
OUTPUT_DIR = BASE_DIR / "data" / "별표_parsed"

# Pattern matching a 별표 header at the start of a line
BYULPYO_HEADER = re.compile(r"^<별표(\d+)>\s*(.+)")
PAGE_BREAK = "---PAGE_BREAK---"
PAGE_MARKER = re.compile(r"^\s*현재【\d+/\d+】페이지")

# Minimum number of content lines between headers to consider it a body section
BODY_MIN_LINES = 10


def extract_prod_info(filename):
    """Extract product code and name from filename."""
    stem = Path(filename).stem
    parts = stem.split("_", 1)
    prod_code = parts[0]
    prod_name = parts[1] if len(parts) > 1 else stem
    return prod_code, prod_name


def classify_category(title):
    """Classify appendix as 'structured' or 'text'."""
    title_clean = title.replace(" ", "")

    text_keywords = [
        "장해분류표",
        "재해분류표",
        "특정신체부위",
        "특정질병분류표",
    ]
    for kw in text_keywords:
        if kw in title_clean:
            return "text"

    structured_keywords = [
        "보험금지급기준표",
        "적립이율계산",
        "악성신생물", "신생물분류표",
        "고액암분류표", "고액치료비",
        "유방암분류표", "남녀생식기암분류표",
        "간암", "폐암", "췌장암",
        "심근경색", "심장질환", "심장부정맥",
        "뇌출혈", "뇌경색", "뇌졸중", "뇌혈관", "뇌질환", "뇌심질환",
        "허혈성",
        "수술분류표",
        "질병및재해분류표", "질병분류표",
        "부정맥분류표",
        "재해골절",
        "순환계질환",
        "표적항암제",
        "급여뇌심", "급여뇌혈관",
        "관련법규",
    ]
    for kw in structured_keywords:
        if kw in title_clean:
            return "structured"

    return "text"


def find_teukak_name_in_range(lines, start_idx, end_idx):
    """Search lines[start_idx:end_idx] for 특약 name patterns. Return the last match found."""
    patterns = [
        re.compile(r"^(무배당\s*특별조건부특약)"),
        re.compile(r"^(특정신체부위[ㆍ·]질병보장제한부인수특약)"),
        re.compile(r"^(지정대리청구서비스특약)"),
        re.compile(r"^(단체취급특약)"),
        re.compile(r"^(장애인전용보험전환특약)"),
        re.compile(r"^(사후정리특약)"),
        re.compile(r"^(보험료납입유예특약)"),
        re.compile(r"^(.+특약)\s*약관"),
    ]

    best_name = None
    for i in range(start_idx, min(end_idx, len(lines))):
        line = lines[i].strip()
        for pattern in patterns:
            m = pattern.match(line)
            if m:
                name = m.group(1).strip()
                name = re.sub(r"약관목차$", "", name)
                name = re.sub(r"약관$", "", name)
                best_name = name.strip()

    return best_name


def build_section_map(lines):
    """
    Build a map of line ranges to section types by doing a forward pass.

    Track section boundaries:
    - "특약 약관" page -> entering 특약 zone
    - Specific 특약 names (X특약 약관/약관목차) -> new 특약 section
    - 별표 TOC clusters following 특약 headers -> part of that 특약

    Returns a sorted list of (start_line, section_type) tuples.
    """
    # Patterns for 특약 section headers
    # These must match standalone headers (lines that ARE the 특약 name),
    # not inline references within article text.
    # Require: starts with 특약 name, optionally followed by 약관/목차/whitespace/end
    teukak_header_pattern = re.compile(
        r"^([가-힣A-Za-z0-9\s\-\(\)·ㆍ]+?특약)\s*(?:약관|목차|$)"
    )

    sections = [(0, "주계약")]

    for i, line_raw in enumerate(lines):
        line = line_raw.strip()

        # Skip empty lines
        if not line:
            continue

        # "특약 약관" generic section marker (standalone page)
        if re.match(r"^특약\s*약관\s*$", line):
            sections.append((i, "특약"))
            continue

        # Specific 특약 headers: "X특약 약관목차", "X특약약관", "X특약\n약관목차"
        # The line must be a section header, not an article reference
        m = teukak_header_pattern.match(line)
        if m:
            name = m.group(1).strip()
            # Filter out false positives:
            # - Lines starting with 제N조 (article numbers)
            # - Lines starting with ② or other markers
            # - Lines that are too long (> 40 chars for the 특약 name)
            if (not re.match(r"^제\d", name) and
                not re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", name) and
                not re.match(r"^[·ㆍ\-]", name) and
                len(name) <= 40):
                sections.append((i, name))
                continue

        # Also match standalone 특약 name on its own line (without 약관/목차 suffix)
        # Only if it looks like a section title (short line, specific names)
        specific_names = [
            "무배당특별조건부특약",
            "무배당 특별조건부특약",
        ]
        for sn in specific_names:
            if line == sn:
                sections.append((i, sn.replace(" ", "")))
                break

    # Normalize section names: remove spaces, normalize middle dots
    normalized = []
    for start, typ in sections:
        typ = typ.replace(" ", "")
        typ = typ.replace("·", "ㆍ")  # normalize middle dot
        normalized.append((start, typ))
    sections = normalized

    return sections


def determine_section_type(section_map, body_line_idx):
    """
    Given a section map and a body header line index, determine the section type.
    Uses the most recent section marker before the body header.
    """
    result = "주계약"
    for start_line, section_type in section_map:
        if start_line <= body_line_idx:
            result = section_type
        else:
            break
    return result


def parse_file(filepath):
    """Parse a single insurance product text file to extract appendix bodies."""
    prod_code, prod_name = extract_prod_info(filepath.name)

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")

    # Step 1: Find all 별표 header lines
    header_entries = []  # (line_idx, number, title)
    for i, line in enumerate(lines):
        m = BYULPYO_HEADER.match(line.strip())
        if m:
            num = int(m.group(1))
            title = m.group(2).strip()
            header_entries.append((i, num, title))

    if not header_entries:
        return {"prodCode": prod_code, "product": prod_name, "appendices": []}

    # Build set of header line indices for quick lookup
    header_line_set = set(entry[0] for entry in header_entries)

    # Step 2: Classify each header as TOC vs body
    # A body entry has:
    # (a) substantial content lines before the next 별표 header, AND
    # (b) is NOT preceded by another 별표 header within a few lines (TOC cluster check)
    body_headers = []  # (line_idx, num, title)

    for idx, (line_idx, num, title) in enumerate(header_entries):
        if idx + 1 < len(header_entries):
            next_line_idx = header_entries[idx + 1][0]
        else:
            next_line_idx = min(line_idx + 500, len(lines))

        # Count non-empty, non-marker content lines until next header
        content_lines = 0
        for j in range(line_idx + 1, next_line_idx):
            if j >= len(lines):
                break
            stripped = lines[j].strip()
            if (stripped and
                not PAGE_MARKER.match(stripped) and
                PAGE_BREAK not in stripped):
                content_lines += 1

        # Check if preceded by another 별표 header within 10 lines
        # (scanning backwards, skipping blanks/markers/page numbers)
        has_preceding_header = False
        for j in range(line_idx - 1, max(0, line_idx - 10), -1):
            if j in header_line_set:
                has_preceding_header = True
                break
            stripped = lines[j].strip()
            # Skip blank lines, page markers, page numbers, PAGE_BREAKs
            if (stripped == "" or
                PAGE_MARKER.match(stripped) or
                PAGE_BREAK in stripped or
                re.match(r"^\d+$", stripped)):  # bare page numbers like "167"
                continue
            # Hit a real content line that isn't a header - stop looking
            break

        # Filter out inline references (title starts with quote or contains reference markers)
        is_inline_ref = (
            title.startswith('"') or
            title.startswith('"') or
            title.startswith('\u201c') or  # left double quote "
            title.startswith('\u201d') or  # right double quote "
            title.startswith('\u2018') or  # left single quote '
            title.startswith('\u2019') or  # right single quote '
            "참조)" in title or
            "에서정한" in title or
            "에서회사가" in title
        )

        # Body entry: substantial content AND not in a TOC cluster AND not an inline ref
        if content_lines >= BODY_MIN_LINES and not has_preceding_header and not is_inline_ref:
            body_headers.append((line_idx, num, title))

    if not body_headers:
        return {"prodCode": prod_code, "product": prod_name, "appendices": []}

    # Step 3: Detect insurance type for each body header
    # Build a section map from forward pass, then look up each body header
    section_map = build_section_map(lines)

    # First pass: assign types from section map
    type_assignments = []
    for idx, (line_idx, num, title) in enumerate(body_headers):
        t = determine_section_type(section_map, line_idx)
        type_assignments.append(t)

    # Post-processing: find the longest ascending sequence starting from 별표1
    # and reclassify it as "주계약"
    # This handles the case where 주계약 별표 bodies appear after 특약 sections
    best_start = -1
    best_len = 0
    for start in range(len(body_headers)):
        if body_headers[start][1] != 1:  # Must start with 별표1
            continue
        seq_len = 1
        prev_n = 1
        for j in range(start + 1, len(body_headers)):
            n = body_headers[j][1]
            if n > prev_n:
                seq_len += 1
                prev_n = n
            else:
                break
        if seq_len > best_len:
            best_len = seq_len
            best_start = start

    if best_start >= 0 and best_len >= 3:
        # Reclassify this sequence as 주계약
        prev_n = 0
        for j in range(best_start, len(body_headers)):
            n = body_headers[j][1]
            if n > prev_n:
                type_assignments[j] = "주계약"
                prev_n = n
            else:
                break

    appendices = []

    for idx, (line_idx, num, title) in enumerate(body_headers):
        current_type = type_assignments[idx]

        # Determine end of body
        if idx + 1 < len(body_headers):
            end_line = body_headers[idx + 1][0]
        else:
            end_line = len(lines)

        # Trim trailing markers
        actual_end = end_line
        for j in range(end_line - 1, line_idx, -1):
            if j >= len(lines):
                continue
            stripped = lines[j].strip()
            if PAGE_BREAK in stripped or PAGE_MARKER.match(stripped) or stripped == "":
                actual_end = j
            else:
                break

        # Extract body text
        body_lines = lines[line_idx:actual_end]

        # Clean: remove trailing empty/marker lines
        while body_lines and (
            body_lines[-1].strip() == "" or
            PAGE_MARKER.match(body_lines[-1].strip()) or
            PAGE_BREAK in body_lines[-1]
        ):
            body_lines.pop()

        body_text = "\n".join(body_lines)

        # Remove inline page markers and PAGE_BREAK
        body_text = re.sub(
            r"\n\s*현재【\d+/\d+】페이지 입니다\.\s*\n\s*\n---PAGE_BREAK---",
            "", body_text
        )
        body_text = re.sub(
            r"\n\s*현재【\d+/\d+】페이지 입니다\.\s*\n",
            "\n", body_text
        )
        body_text = re.sub(
            r"\n\s*현재【\d+/\d+】페이지\s*\n",
            "\n", body_text
        )
        body_text = re.sub(r"\n---PAGE_BREAK---\n?", "\n", body_text)

        category = classify_category(title)

        appendices.append({
            "appendix_id": f"별표{num}",
            "title": title,
            "type": current_type,
            "body": body_text.strip(),
            "category": category,
        })

    return {
        "prodCode": prod_code,
        "product": prod_name,
        "appendices": appendices,
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    txt_files = sorted(TEXT_DIR.glob("*.txt"))
    if not txt_files:
        print("No .txt files found in", TEXT_DIR)
        sys.exit(1)

    print(f"Found {len(txt_files)} text files\n")

    summary = []

    for filepath in txt_files:
        prod_code, prod_name = extract_prod_info(filepath.name)
        print(f"Processing {prod_code} ({prod_name})...")

        result = parse_file(filepath)

        # Save JSON
        out_path = OUTPUT_DIR / f"{prod_code}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # Summary stats
        total = len(result["appendices"])
        types = {}
        for a in result["appendices"]:
            t = a["type"]
            types[t] = types.get(t, 0) + 1

        # Show appendix IDs per type
        type_ids = {}
        for a in result["appendices"]:
            t = a["type"]
            if t not in type_ids:
                type_ids[t] = []
            type_ids[t].append(a["appendix_id"])

        for t, ids in sorted(type_ids.items()):
            print(f"  {t}: {', '.join(ids)}")

        type_str = ", ".join(f"{k}: {v}" for k, v in sorted(types.items()))
        summary.append((prod_code, prod_name, total, type_str))

    # Print summary table
    print("\n" + "=" * 110)
    print(f"{'Product':<12} {'Name':<55} {'Count':>5}  Types")
    print("-" * 110)
    total_all = 0
    for code, name, count, types in summary:
        display_name = name[:53] + ".." if len(name) > 55 else name
        print(f"{code:<12} {display_name:<55} {count:>5}  {types}")
        total_all += count
    print("-" * 110)
    print(f"{'TOTAL':<12} {'':<55} {total_all:>5}")
    print("=" * 110)

    print(f"\nOutput saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
