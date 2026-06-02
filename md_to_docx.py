#!/usr/bin/env python3
"""Convert any Markdown file to a formatted Word document (.docx).

Usage:
    python md_to_docx.py architecture.md   → writes architecture.docx
"""

import re
import sys
from pathlib import Path

from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# ── Constants ────────────────────────────────────────────────────────────────
FONT = "Calibri"
BODY_PT = Pt(12)
H2_PT = Pt(14)   # ## and #
H3_PT = Pt(13)   # ###
MARGIN = Cm(2.5)

# A4 portrait: 21 cm − 2×2.5 cm margins = 16 cm usable width
PAGE_USABLE_CM = 21.0 - 2 * 2.5

# A4 usable height ≈ 29.7 − 5 = 24.7 cm; at 12pt single-spacing ≈ 0.5 cm/line
TABLE_WARN_ROWS = 45

# ── Emoji / zero-width strip ──────────────────────────────────────────────────
# Explicit ranges so en dash (U+2013) and em dash (U+2014) are NOT stripped.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # misc symbols, pictographs, transport, etc.
    "\U00002600-\U000027BF"   # misc symbols, dingbats
    "︀-️"           # variation selectors
    "​-‍"           # zero-width space / non-joiner / joiner
    "﻿"                  # BOM / zero-width no-break space
    "]+",
    flags=re.UNICODE,
)


def _clean(text: str) -> str:
    text = _EMOJI_RE.sub("", text)
    # Normalize all dashes to plain hyphen-minus
    text = text.replace("---", "-")
    text = text.replace("--", "-")
    text = text.replace("—", "-")   # em dash
    text = text.replace("–", "-")   # en dash
    return text.strip()


# ── Paragraph helpers ─────────────────────────────────────────────────────────
def _fmt_para(para, keep_with_next: bool = False) -> None:
    pf = para.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    pf.left_indent = Pt(0)
    pf.first_line_indent = Pt(0)
    if keep_with_next:
        pf.keep_with_next = True
    # Suppress auto-hyphenation and spell/grammar check per paragraph
    pPr = para._p.get_or_add_pPr()
    if pPr.find(qn("w:suppressAutoHyphens")) is None:
        el = OxmlElement("w:suppressAutoHyphens")
        pPr.append(el)


def _run(para, text: str, *, bold=False, italic=False, size=None, font=None):
    r = para.add_run(text)
    r.bold = bold
    r.italic = italic
    r.font.name = font or FONT
    r.font.size = size or BODY_PT
    # Disable spell/grammar check and proofing on every run
    rPr = r._r.get_or_add_rPr()
    if rPr.find(qn("w:noProof")) is None:
        rPr.append(OxmlElement("w:noProof"))
    return r


# ── Inline Markdown renderer ──────────────────────────────────────────────────
_INLINE_RE = re.compile(
    r"("
    r"\*\*\*.+?\*\*\*"          # ***bold italic***
    r"|___.+?___"                # ___bold italic___
    r"|``.+?``"                  # ``code``
    r"|\*\*.+?\*\*"              # **bold**
    r"|__.+?__"                  # __bold__
    r"|`.+?`"                    # `code`
    r"|\*[^*\n]+?\*"             # *italic*
    r"|(?<!\w)_[^_\n]+?_(?!\w)" # _italic_ (word-boundary guarded)
    r")"
)


def _inline(para, text: str, base_size=None) -> None:
    text = text.replace("—", "-").replace("–", "-")
    text = _clean(text)
    bs = base_size or BODY_PT
    for part in _INLINE_RE.split(text):
        if not part:
            continue
        if re.fullmatch(r"\*\*\*.+?\*\*\*|___.+?___", part):
            _run(para, part[3:-3], bold=True, italic=True, size=bs)
        elif re.fullmatch(r"\*\*.+?\*\*|__.+?__", part):
            _run(para, part[2:-2], bold=True, size=bs)
        elif re.fullmatch(r"``.+?``", part):
            _run(para, part[2:-2], size=bs)
        elif re.fullmatch(r"`.+?`", part):
            _run(para, part[1:-1], size=bs)
        elif re.fullmatch(r"\*[^*\n]+?\*|(?<!\w)_[^_\n]+?_(?!\w)", part):
            _run(para, part[1:-1], italic=True, size=bs)
        else:
            _run(para, part, size=bs)


def _plain(text: str) -> str:
    """Strip inline markdown to plain text (used for width estimation)."""
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*|___(.+?)___",
                  lambda m: (m.group(1) or m.group(2)), text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__",
                  lambda m: (m.group(1) or m.group(2)), text)
    text = re.sub(r"``(.+?)``|`(.+?)`",
                  lambda m: (m.group(1) or m.group(2)), text)
    text = re.sub(r"\*(.+?)\*|_(.+?)_",
                  lambda m: (m.group(1) or m.group(2)), text)
    return text.strip()


# ── Table helpers ─────────────────────────────────────────────────────────────
def _cant_split_rows(table) -> None:
    """Mark every row cantSplit so table rows never break across pages."""
    for row in table.rows:
        tr = row._tr
        tr_pr = tr.find(qn("w:trPr"))
        if tr_pr is None:
            tr_pr = OxmlElement("w:trPr")
            tr.insert(0, tr_pr)
        if tr_pr.find(qn("w:cantSplit")) is None:
            cs = OxmlElement("w:cantSplit")
            cs.set(qn("w:val"), "true")
            tr_pr.append(cs)


def _no_borders(tbl_el) -> None:
    tbl_pr = tbl_el.find(qn("w:tblPr"))
    if tbl_pr is None:
        tbl_pr = OxmlElement("w:tblPr")
        tbl_el.insert(0, tbl_pr)
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{side}")
        b.set(qn("w:val"), "none")
        b.set(qn("w:sz"), "0")
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), "auto")
        borders.append(b)
    tbl_pr.append(borders)


def _apply_col_widths(table, widths_cm: list) -> None:
    tbl = table._tbl

    # Build tblGrid
    tbl_grid = OxmlElement("w:tblGrid")
    for w in widths_cm:
        gc = OxmlElement("w:gridCol")
        gc.set(qn("w:w"), str(int(Cm(w).twips)))
        tbl_grid.append(gc)

    # Remove existing tblGrid, insert after tblPr
    for old in tbl.findall(qn("w:tblGrid")):
        tbl.remove(old)
    tbl_pr = tbl.find(qn("w:tblPr"))
    if tbl_pr is not None:
        total_twips = sum(int(Cm(w).twips) for w in widths_cm)
        tblW = OxmlElement("w:tblW")
        tblW.set(qn("w:w"), str(total_twips))
        tblW.set(qn("w:type"), "dxa")
        tbl_pr.append(tblW)

        tblLayout = OxmlElement("w:tblLayout")
        tblLayout.set(qn("w:type"), "fixed")
        tbl_pr.append(tblLayout)

        tbl_pr.addnext(tbl_grid)
    else:
        tbl.insert(0, tbl_grid)

    # Per-cell widths
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            if i >= len(widths_cm):
                break
            tc = cell._tc
            tc_pr = tc.find(qn("w:tcPr"))
            if tc_pr is None:
                tc_pr = OxmlElement("w:tcPr")
                tc.insert(0, tc_pr)
            for old in tc_pr.findall(qn("w:tcW")):
                tc_pr.remove(old)
            tcW = OxmlElement("w:tcW")
            tcW.set(qn("w:w"), str(int(Cm(widths_cm[i]).twips)))
            tcW.set(qn("w:type"), "dxa")
            tc_pr.append(tcW)


def _parse_table_rows(lines: list) -> list:
    """Return list of cell-lists; separator rows are dropped."""
    rows = []
    for line in lines:
        s = line.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        cells = [c.strip() for c in s.split("|")]
        if all(re.fullmatch(r"[-: ]+", c) for c in cells if c):
            continue  # separator row
        rows.append(cells)
    return rows


def _col0_entity_test(para, text: str, is_header: bool) -> None:
    """Fill col-0 of an entity test table.

    Splits on '_': each segment run gets w:noBreak so Word cannot break inside
    a segment.  The '_' separator runs do NOT get w:noBreak, so those positions
    remain the only legal line-break opportunities.
    """
    parts = text.split("_")
    for idx, part in enumerate(parts):
        r = para.add_run(part)
        r.font.name = FONT
        r.font.size = BODY_PT
        if is_header:
            r.bold = True
        rPr = r._r.get_or_add_rPr()
        rPr.append(OxmlElement("w:noBreak"))
        if rPr.find(qn("w:noProof")) is None:
            rPr.append(OxmlElement("w:noProof"))
        if idx < len(parts) - 1:
            sep = para.add_run("_")
            sep.font.name = FONT
            sep.font.size = BODY_PT
            if is_header:
                sep.bold = True
            rPr_sep = sep._r.get_or_add_rPr()
            if rPr_sep.find(qn("w:noProof")) is None:
                rPr_sep.append(OxmlElement("w:noProof"))
            zwsp = para.add_run("​")
            zwsp.font.name = FONT
            zwsp.font.size = BODY_PT
            if is_header:
                zwsp.bold = True
            rPr_zw = zwsp._r.get_or_add_rPr()
            if rPr_zw.find(qn("w:noProof")) is None:
                rPr_zw.append(OxmlElement("w:noProof"))


def _add_table(doc, tbl_lines: list) -> None:
    rows = _parse_table_rows(tbl_lines)
    if not rows:
        return
    n_cols = max(len(r) for r in rows)
    n_rows = len(rows)

    if n_rows > TABLE_WARN_ROWS:
        print(
            f"WARNING: Table with {n_rows} data rows likely exceeds one page "
            "– please review manually."
        )

    _ENTITY_HDR = ["Test Function", "TC", "Layer", "What Is Verified"]
    _OVERVIEW_HDR = ["Test File", "Tests", "REQ_IDs Covered", "Layer(s)", "Gate Group", "Status"]
    _DB_HDR = ["Test Function", "Layer", "What Is Verified"]
    _GATE_HDR = ["Gate Group", "Test Type", "Rationale"]
    _NONBLOCK_HDR = ["Group", "Current Status", "Phase 2 Gate"]
    _P1GATE_HDR = ["Test File", "Test Function", "TC"]

    if n_cols == 6 and rows and [_plain(c) for c in rows[0]] == _OVERVIEW_HDR:
        col_cm = [4.0, 1.5, 3.0, 2.0, 3.5, 2.0]  # Section 1 Overview: col1 -2cm, col2 +0.5cm, col3 +1cm, col4 +1cm
    elif n_cols == 4 and rows and [_plain(c) for c in rows[0]] == _ENTITY_HDR:
        col_cm = [4.5, 2.0, 2.0, 7.5]
    elif n_cols == 3 and rows and [_plain(c) for c in rows[0]] == _DB_HDR:
        col_cm = [4.5, 2.0, 9.5]  # Section 4 DB Layer: col1=4.5cm, col2=2cm, col3=remainder
    elif n_cols == 3 and rows and [_plain(c) for c in rows[0]] == _GATE_HDR:
        col_cm = [5.0, 3.0, 8.0]  # Section 6.2: col1 -1cm, col2 +1cm
    elif n_cols == 3 and rows and [_plain(c) for c in rows[0]] == _NONBLOCK_HDR:
        col_cm = [5.0, 3.0, 8.0]  # Section 6.3: col1 -1cm, col2 +1cm
    elif n_cols == 3 and rows and [_plain(c) for c in rows[0]] == _P1GATE_HDR:
        col_cm = [3.5, 10.5, 2.0]  # Section 6.5: col1 -1cm, col3 +1cm
    else:
        # Column widths: per-column minimum sized to fit the longest single word,
        # then proportional distribution of remaining space based on max cell length.
        #
        # min[i] = longest_word_chars[i] * 0.2 cm  (Calibri 12pt ≈ 0.2 cm/char)
        # Iterative: pin columns whose proportional share < their min, redistribute
        # remainder among free columns. When sum(mins) > page width, fall back to
        # pure proportional (minimums cannot all be honoured).
        CM_PER_CHAR = 0.2

        col_max_cell = [1] * n_cols   # max total plain-text chars per column
        col_max_word = [1] * n_cols   # max single-word chars per column

        for row in rows:
            for i, cell in enumerate(row[:n_cols]):
                plain = _plain(cell)
                col_max_cell[i] = max(col_max_cell[i], len(plain))
                words = plain.split()
                if words:
                    col_max_word[i] = max(col_max_word[i], max(len(w) for w in words))

        col_min = [col_max_word[i] * CM_PER_CHAR for i in range(n_cols)]

        if sum(col_min) <= PAGE_USABLE_CM:
            col_cm = [0.0] * n_cols
            fixed: set = set()
            remaining = PAGE_USABLE_CM
            for _ in range(n_cols):
                free = [i for i in range(n_cols) if i not in fixed]
                if not free:
                    break
                total_free = sum(col_max_cell[i] for i in free) or 1
                prop = {i: remaining * col_max_cell[i] / total_free for i in free}
                under = [i for i in free if prop[i] < col_min[i]]
                if not under:
                    for i in free:
                        col_cm[i] = prop[i]
                    break
                for i in under:
                    col_cm[i] = col_min[i]
                    remaining -= col_min[i]
                    fixed.add(i)
        else:
            total_chars = sum(col_max_cell)
            col_cm = [PAGE_USABLE_CM * col_max_cell[i] / total_chars for i in range(n_cols)]

        # Normalise to exactly PAGE_USABLE_CM (guards against float drift)
        col_total = sum(col_cm)
        col_cm = [c * PAGE_USABLE_CM / col_total for c in col_cm]

    is_col0_testname = col_cm in ([4.5, 2.0, 2.0, 7.5], [4.5, 2.0, 9.5], [3.5, 10.5, 2.0])

    table = doc.add_table(rows=n_rows, cols=n_cols)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    _no_borders(table._tbl)
    _apply_col_widths(table, col_cm)
    _cant_split_rows(table)

    for r_idx, row in enumerate(rows):
        is_header = r_idx == 0
        for c_idx in range(n_cols):
            text = row[c_idx] if c_idx < len(row) else ""
            cell = table.cell(r_idx, c_idx)
            para = cell.paragraphs[0]
            para.clear()
            _fmt_para(para)
            if is_col0_testname and (c_idx == 0 or (col_cm == [3.5, 10.5, 2.0] and c_idx == 1)):
                _col0_entity_test(para, text, is_header)
            else:
                _inline(para, text)
                if is_header:
                    for run in para.runs:
                        run.bold = True
                        run.font.name = FONT
                        run.font.size = BODY_PT


# ── Page numbers ──────────────────────────────────────────────────────────────
def _add_page_numbers(doc) -> None:
    for section in doc.sections:
        footer = section.footer
        para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        para.clear()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run()
        run.font.name = FONT
        run.font.size = BODY_PT

        fc_begin = OxmlElement("w:fldChar")
        fc_begin.set(qn("w:fldCharType"), "begin")
        run._r.append(fc_begin)

        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = "PAGE"
        run._r.append(instr)

        fc_end = OxmlElement("w:fldChar")
        fc_end.set(qn("w:fldCharType"), "end")
        run._r.append(fc_end)


# ── Table line detection ───────────────────────────────────────────────────────
def _is_table_row(line: str) -> bool:
    """True if the line looks like a markdown table row."""
    s = line.strip()
    return "|" in s and (s.startswith("|") or s.count("|") >= 2)


def _is_table_separator(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    # Remove leading/trailing pipes
    s = s.strip("|")
    return bool(re.fullmatch(r"[\s\-:|]+", s))


# ── Document-level defaults ───────────────────────────────────────────────────
def _suppress_hyphenation_defaults(doc) -> None:
    """Set w:suppressAutoHyphens in docDefaults so it applies document-wide."""
    styles_el = doc.styles.element          # <w:styles>
    doc_defaults = styles_el.find(qn("w:docDefaults"))
    if doc_defaults is None:
        doc_defaults = OxmlElement("w:docDefaults")
        styles_el.insert(0, doc_defaults)

    ppr_default = doc_defaults.find(qn("w:pPrDefault"))
    if ppr_default is None:
        ppr_default = OxmlElement("w:pPrDefault")
        doc_defaults.append(ppr_default)

    ppr = ppr_default.find(qn("w:pPr"))
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        ppr_default.append(ppr)

    if ppr.find(qn("w:suppressAutoHyphens")) is None:
        ppr.append(OxmlElement("w:suppressAutoHyphens"))


# ── Main converter ─────────────────────────────────────────────────────────────
def convert(md_path: Path, docx_path: Path) -> None:
    doc = Document()

    # Page layout: A4 portrait, 2.5 cm margins
    sec = doc.sections[0]
    sec.page_width = Cm(21)
    sec.page_height = Cm(29.7)
    sec.left_margin = MARGIN
    sec.right_margin = MARGIN
    sec.top_margin = MARGIN
    sec.bottom_margin = MARGIN

    _suppress_hyphenation_defaults(doc)

    # Default Normal style baseline
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = BODY_PT
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE

    _add_page_numbers(doc)

    # Strip blockquote markers (> or >> etc.) from every line before processing
    _bq = re.compile(r"^(>\s*)+")
    lines = [_bq.sub("", l) for l in md_path.read_text(encoding="utf-8").splitlines()]
    i = 0

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        # Blank line
        if not line:
            i += 1
            continue

        # Fenced code block
        if line.startswith("```"):
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            for cl in code_lines:
                p = doc.add_paragraph()
                _fmt_para(p)
                _run(p, cl)
            continue

        # Markdown table: current line is a row and next non-blank is a separator
        if _is_table_row(line):
            next_idx = i + 1
            while next_idx < len(lines) and not lines[next_idx].strip():
                next_idx += 1
            if next_idx < len(lines) and _is_table_separator(lines[next_idx]):
                tbl_lines = []
                while i < len(lines) and _is_table_row(lines[i]):
                    tbl_lines.append(lines[i])
                    i += 1
                _add_table(doc, tbl_lines)
                continue

        # Heading
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            text = m.group(2)               # _clean is called inside _inline
            size = H2_PT if level <= 2 else H3_PT if level == 3 else BODY_PT
            bold = level <= 4
            p = doc.add_paragraph()
            _fmt_para(p, keep_with_next=True)
            _inline(p, text, base_size=size)
            if bold:
                for run in p.runs:          # force every run bold (incl. leading numbers)
                    run.bold = True
            i += 1
            continue

        # Horizontal rule — skip
        if re.fullmatch(r"[-*_]{3,}", line):
            i += 1
            continue

        # Bullet list — collect consecutive bullet lines
        if re.match(r"^[-*+] ", line):
            while i < len(lines) and re.match(r"^[-*+] ", lines[i].strip()):
                text = re.sub(r"^[-*+] ", "", lines[i].strip())
                p = doc.add_paragraph()
                _fmt_para(p)
                _run(p, "• ")   # bullet character, not a Word list style
                _inline(p, text)
                i += 1
            continue

        # Numbered list — collect consecutive numbered lines
        if re.match(r"^\d+\.", line):
            while i < len(lines) and re.match(r"^\d+\.", lines[i].strip()):
                m2 = re.match(r"^(\d+)\.\s*(.*)", lines[i].strip())
                label = m2.group(1) if m2 else "1"
                text = m2.group(2) if m2 else lines[i].strip()
                p = doc.add_paragraph()
                _fmt_para(p)
                _run(p, f"{label}. ")
                _inline(p, text)
                i += 1
            continue

        # Regular paragraph — join consecutive body lines (standard MD behaviour)
        parts = []
        while i < len(lines):
            l = lines[i].strip()
            if (
                not l
                or re.match(r"^#{1,6}\s", l)
                or re.match(r"^[-*+] ", l)
                or re.match(r"^\d+\.", l)
                or _is_table_row(l)
                or l.startswith("```")
                or re.fullmatch(r"[-*_]{3,}", l)
            ):
                break
            parts.append(l)
            i += 1
        if parts:
            p = doc.add_paragraph()
            _fmt_para(p)
            _inline(p, " ".join(parts))

    doc.save(str(docx_path))
    print(f"Saved: {docx_path}")


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python md_to_docx.py <file.md>")
        sys.exit(1)
    md_path = Path(sys.argv[1])
    if not md_path.exists():
        print(f"Error: file not found: {md_path}")
        sys.exit(1)
    if md_path.suffix.lower() not in (".md", ".markdown"):
        print(f"Warning: {md_path.name} does not have a .md extension, proceeding anyway.")
    docx_path = md_path.with_suffix(".docx")
    convert(md_path, docx_path)


if __name__ == "__main__":
    main()
