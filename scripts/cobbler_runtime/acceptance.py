"""Shared Elves acceptance grammar and staging-contract helpers.

The plan, delegated-worker handoff, full-run packet, and landing checker all
consume the same stable IDs.  Keep their Markdown grammar here so a template
cannot silently drift away from the launch and landing paths again.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


MAX_BATCH_NUMBER_DIGITS = 128
BATCH_NUMBER_PATTERN = rf"(?:0|[1-9][0-9]{{0,{MAX_BATCH_NUMBER_DIGITS - 1}}})"
_BATCH_NUMBER_LIMIT = 10**MAX_BATCH_NUMBER_DIGITS
STABLE_ACCEPTANCE_ID_PATTERN = (
    rf"(?:B{BATCH_NUMBER_PATTERN}-A[0-9]+|M-A[0-9]+)"
)
STABLE_ACCEPTANCE_ID_RE = re.compile(rf"^{STABLE_ACCEPTANCE_ID_PATTERN}$")
STABLE_BATCH_ACCEPTANCE_ID_RE = re.compile(
    rf"^B({BATCH_NUMBER_PATTERN})-A[0-9]+$"
)

_SEPARATOR_PATTERN = r"(?:—|–|--?|:)"
_MARKDOWN_ROW_RE = re.compile(
    rf"^[ ]{{0,3}}[-*][ \t]+"
    rf"(?:\[(?P<check>[ xX])\][ \t]+)?"
    rf"(?:"
    rf"\[(?P<bracket_id>{STABLE_ACCEPTANCE_ID_PATTERN})\]"
    rf"(?:[ \t]*{_SEPARATOR_PATTERN}[ \t]*|[ \t]+)"
    rf"(?P<bracket_criterion>\S(?:.*\S)?)"
    rf"|"
    rf"(?P<bare_id>{STABLE_ACCEPTANCE_ID_PATTERN})"
    rf"[ \t]*{_SEPARATOR_PATTERN}[ \t]*"
    rf"(?P<bare_criterion>\S(?:.*\S)?)"
    rf")"
    rf"[ \t]*\r?$",
    re.MULTILINE,
)
_CANDIDATE_ROW_RE = re.compile(
    r"^[ ]{0,3}[-*][ \t]+(?:\[[ xX]\][ \t]+)?"
    r"\[?(?P<id>B[0-9]+-A[0-9]+|M-A[0-9]+)\b.*$",
    re.MULTILINE,
)
_CHECKBOX_RE = re.compile(r"^[ ]{0,3}[-*][ \t]+\[([ xX])\][ \t]+(.+)$", re.MULTILINE)

_BOLD_ACCEPTANCE_LABEL_RE = re.compile(
    r"^[ ]{0,3}\*\*[ \t]*Acceptance[ \t]+criteria[ \t]*:?"
    r"[ \t]*\*\*[ \t]*:?[ \t]*$",
    re.IGNORECASE,
)
_HEADING_ACCEPTANCE_LABEL_RE = re.compile(
    r"^[ ]{0,3}(#{1,6})[ \t]+Acceptance[ \t]+criteria[ \t]*:?[ \t]*$",
    re.IGNORECASE,
)
_PLAIN_ACCEPTANCE_LABEL_RE = re.compile(
    r"^[ ]{0,3}Acceptance[ \t]+criteria[ \t]*:?[ \t]*$",
    re.IGNORECASE,
)
_MARKDOWN_HEADING_RE = re.compile(
    r"^[ ]{0,3}(#{1,6})[ \t]+.+$",
    re.MULTILINE,
)
_BOLD_SECTION_RE = re.compile(r"^[ ]{0,3}\*\*[^*\n]+\*\*[ \t]*:?[ \t]*$")
_BATCH_HEADING_RE = re.compile(
    r"^###?\s+Batch\s+\[?([0-9]+)\]?\s*[:.\-–—]?\s*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
_MASTER_ACCEPTANCE_HEADING_RE = re.compile(
    r"(?im)^(#{1,6})\s+Master\s+Acceptance\s*$"
)


@dataclass(frozen=True)
class AcceptanceRow:
    """One canonical stable-ID definition parsed from Markdown."""

    id: str
    criterion: str
    checked: bool | None
    line: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "criterion": self.criterion,
            "checked": self.checked,
            "line": self.line,
        }


@dataclass(frozen=True)
class AcceptanceIssue:
    """One line-addressable plan/session acceptance defect."""

    code: str
    message: str
    line: int | None = None


@dataclass(frozen=True)
class AcceptanceSection:
    """The body of an explicit Acceptance criteria section."""

    text: str
    content_line: int
    label_line: int


@dataclass(frozen=True)
class PlanAcceptanceContract:
    """Canonical stable-ID rows plus staging diagnostics from one plan."""

    rows: tuple[AcceptanceRow, ...]
    batch_ids: tuple[int, ...]
    issues: tuple[AcceptanceIssue, ...]


def normalize_batch_id(value: Any) -> int | None:
    """Return an unambiguous non-negative batch number, including ``B0``.

    Legacy integer and numeric-string forms remain readable.  Leading-zero
    aliases are rejected so ``B0``/``0`` cannot collide with ``B00``/``00``.
    """

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value < _BATCH_NUMBER_LIMIT else None
    if not isinstance(value, str):
        return None
    match = re.fullmatch(rf"(?:B)?({BATCH_NUMBER_PATTERN})", value)
    if match is None or len(match.group(1)) > MAX_BATCH_NUMBER_DIGITS:
        return None
    return int(match.group(1))


def _blank_markdown_span(value: str) -> str:
    return "".join("\n" if char == "\n" else " " for char in value)


def active_markdown(markdown: str) -> str:
    """Blank comments and fenced code while preserving offsets and line numbers."""

    without_comments = re.sub(
        r"<!--.*?(?:-->|\Z)",
        lambda match: _blank_markdown_span(match.group(0)),
        markdown,
        flags=re.DOTALL,
    )
    rendered: list[str] = []
    fence_char: str | None = None
    fence_length = 0
    for line in without_comments.splitlines(keepends=True):
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence_char is None:
            if match is None:
                rendered.append(line)
                continue
            marker = match.group(1)
            fence_char = marker[0]
            fence_length = len(marker)
            rendered.append(_blank_markdown_span(line))
            continue
        rendered.append(_blank_markdown_span(line))
        if match is not None:
            marker = match.group(1)
            if marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = None
                fence_length = 0
    return "".join(rendered)


def _line_number(text: str, offset: int, *, base_line: int) -> int:
    return base_line + text.count("\n", 0, offset)


def acceptance_row_syntax_message(acceptance_id: str, line: int) -> str:
    """Return a neutral diagnostic showing both supported row spellings."""

    return (
        f"Line {line}: acceptance row for {acceptance_id} is malformed. "
        f"Use either `- [ ] {acceptance_id}: <criterion>` or "
        f"`- [ ] [{acceptance_id}] <criterion>`."
    )


def invalid_acceptance_id_message(acceptance_id: str, line: int) -> str:
    """Return a targeted canonical replacement for a leading-zero batch ID."""

    match = re.fullmatch(r"B([0-9]+)-A([0-9]+)", acceptance_id)
    batch_digits = match.group(1) if match is not None else ""
    canonical_digits = batch_digits.lstrip("0") or "0"
    observed = (
        acceptance_id
        if len(acceptance_id) <= 80
        else f"{acceptance_id[:40]}…{acceptance_id[-20:]}"
    )
    if len(canonical_digits) > MAX_BATCH_NUMBER_DIGITS:
        return (
            f"Line {line}: acceptance id {observed} is not canonical because its "
            f"batch number exceeds {MAX_BATCH_NUMBER_DIGITS} digits."
        )
    replacement = (
        f"B{canonical_digits}-A{match.group(2)}"
        if match is not None
        else acceptance_id
    )
    return (
        f"Line {line}: acceptance id {observed} is not canonical. "
        f"Use either `- [ ] {replacement}: <criterion>` or "
        f"`- [ ] [{replacement}] <criterion>`."
    )


def parse_markdown_acceptance_rows(
    markdown: str,
    *,
    require_checkbox: bool,
    base_line: int = 1,
) -> tuple[list[AcceptanceRow], list[AcceptanceIssue]]:
    """Parse both bare and bracketed stable-ID rows with wrapped criteria.

    Plan sections require checkboxes.  Full-run packets use the same grammar
    but may omit them.  Stable-looking malformed rows are returned as targeted
    syntax issues rather than disappearing as zero parsed criteria.
    """

    text = active_markdown(markdown)
    matches = list(_MARKDOWN_ROW_RE.finditer(text))
    rows: list[AcceptanceRow] = []
    issues: list[AcceptanceIssue] = []
    valid_line_starts: set[int] = set()

    for index, match in enumerate(matches):
        line = _line_number(text, match.start(), base_line=base_line)
        valid_line_starts.add(match.start())
        checked_raw = match.group("check")
        acceptance_id = match.group("bracket_id") or match.group("bare_id")
        criterion = match.group("bracket_criterion") or match.group("bare_criterion")
        if require_checkbox and checked_raw is None:
            issues.append(
                AcceptanceIssue(
                    "acceptance_row_syntax",
                    acceptance_row_syntax_message(acceptance_id, line),
                    line,
                )
            )
            continue

        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        continuation: list[str] = []
        for raw_line in text[match.end() : end].splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith(("#", "**")) or re.match(
                r"^[-*][ \t]+", stripped
            ):
                break
            if raw_line[:1].isspace():
                continuation.append(stripped)
                continue
            break
        canonical_criterion = " ".join(
            [criterion.strip(), *continuation]
        ).strip()
        rows.append(
            AcceptanceRow(
                id=acceptance_id,
                criterion=canonical_criterion,
                checked=(
                    None if checked_raw is None else checked_raw.lower() == "x"
                ),
                line=line,
            )
        )

    for candidate in _CANDIDATE_ROW_RE.finditer(text):
        if candidate.start() in valid_line_starts:
            continue
        acceptance_id = candidate.group("id")
        line = _line_number(text, candidate.start(), base_line=base_line)
        code = (
            "acceptance_id_invalid"
            if STABLE_ACCEPTANCE_ID_RE.fullmatch(acceptance_id) is None
            else "acceptance_row_syntax"
        )
        message = (
            invalid_acceptance_id_message(acceptance_id, line)
            if code == "acceptance_id_invalid"
            else acceptance_row_syntax_message(acceptance_id, line)
        )
        issues.append(
            AcceptanceIssue(
                code,
                message,
                line,
            )
        )

    # A concrete line-level correction is more useful than an aggregate error
    # that is merely a consequence of the malformed row not parsing.
    issues.sort(
        key=lambda item: (
            item.line is None,
            item.line if item.line is not None else 0,
            item.code,
            item.message,
        )
    )
    return rows, issues


def _acceptance_label_heading_level(line: str) -> int | None:
    heading = _HEADING_ACCEPTANCE_LABEL_RE.fullmatch(line.rstrip("\r\n"))
    if heading is not None:
        return len(heading.group(1))
    plain = line.rstrip("\r\n")
    if _BOLD_ACCEPTANCE_LABEL_RE.fullmatch(plain) or _PLAIN_ACCEPTANCE_LABEL_RE.fullmatch(
        plain
    ):
        return 0
    return None


def find_acceptance_section(
    markdown: str,
    *,
    base_line: int = 1,
) -> AcceptanceSection | None:
    """Find a style-neutral explicit Acceptance criteria section."""

    lines = markdown.splitlines(keepends=True)
    for index, line in enumerate(lines):
        heading_level = _acceptance_label_heading_level(line)
        if heading_level is None:
            continue
        end = len(lines)
        for cursor in range(index + 1, len(lines)):
            candidate = lines[cursor].rstrip("\r\n")
            heading = _MARKDOWN_HEADING_RE.fullmatch(candidate)
            if heading is not None and (
                heading_level == 0 or len(heading.group(1)) <= heading_level
            ):
                end = cursor
                break
            if heading_level == 0 and _BOLD_SECTION_RE.fullmatch(candidate):
                end = cursor
                break
        return AcceptanceSection(
            text="".join(lines[index + 1 : end]),
            content_line=base_line + index + 1,
            label_line=base_line + index,
        )
    return None


def parse_plan_acceptance_contract(markdown: str) -> PlanAcceptanceContract:
    """Parse stable rows only from explicit batch and Master Acceptance scopes.

    Legacy unlabelled criteria remain readable when a plan contains no stable
    rows.  Once any stable row (or stable-looking malformed row) is present,
    every checkbox in those scopes must carry a stable ID.
    """

    text = active_markdown(markdown)
    batch_matches = list(_BATCH_HEADING_RE.finditer(text))
    rows: list[AcceptanceRow] = []
    issues: list[AcceptanceIssue] = []
    batch_ids: list[int] = []
    scoped_counts: list[tuple[int, int, int, bool]] = []

    for index, match in enumerate(batch_matches):
        raw_number = match.group(1)
        if not re.fullmatch(BATCH_NUMBER_PATTERN, raw_number):
            line = _line_number(text, match.start(), base_line=1)
            issues.append(
                AcceptanceIssue(
                    "batch_id_invalid",
                    f"Line {line}: Batch {raw_number} uses an ambiguous leading-zero id.",
                    line,
                )
            )
            continue
        batch_number = normalize_batch_id(raw_number)
        if batch_number is None:
            line = _line_number(text, match.start(), base_line=1)
            issues.append(
                AcceptanceIssue(
                    "batch_id_invalid",
                    f"Line {line}: Batch {raw_number[:80]} exceeds the supported numeric bound.",
                    line,
                )
            )
            continue
        batch_ids.append(batch_number)
        start = match.end()
        end = (
            batch_matches[index + 1].start()
            if index + 1 < len(batch_matches)
            else len(text)
        )
        body = text[start:end]
        body_line = _line_number(text, start, base_line=1)
        section = find_acceptance_section(body, base_line=body_line)
        if section is None:
            issues.append(
                AcceptanceIssue(
                    "acceptance_section_missing",
                    f"Batch {batch_number} has no explicit Acceptance criteria section. "
                    "Use `**Acceptance criteria:**`, `**Acceptance criteria**:`, "
                    "`### Acceptance criteria`, or `Acceptance criteria:`.",
                    _line_number(text, match.start(), base_line=1),
                )
            )
            continue
        section_rows, section_issues = parse_markdown_acceptance_rows(
            section.text,
            require_checkbox=True,
            base_line=section.content_line,
        )
        issues.extend(section_issues)
        scoped_counts.append(
            (
                batch_number,
                checkbox_count(section.text),
                len(section_rows),
                bool(section_issues),
            )
        )
        for row in section_rows:
            match_id = STABLE_BATCH_ACCEPTANCE_ID_RE.fullmatch(row.id)
            if match_id is None:
                issues.append(
                    AcceptanceIssue(
                        "acceptance_id_wrong_scope",
                        f"Line {row.line}: {row.id} belongs under Master Acceptance, not Batch {batch_number}.",
                        row.line,
                    )
                )
            else:
                row_batch_number = normalize_batch_id(match_id.group(1))
                if row_batch_number is None:
                    issues.append(
                        AcceptanceIssue(
                            "acceptance_id_invalid",
                            f"Line {row.line}: {row.id[:80]} exceeds the supported numeric bound.",
                            row.line,
                        )
                    )
                elif row_batch_number != batch_number:
                    issues.append(
                        AcceptanceIssue(
                            "acceptance_id_wrong_batch",
                            f"Line {row.line}: {row.id} belongs under Batch {match_id.group(1)}, not Batch {batch_number}.",
                            row.line,
                        )
                    )
            rows.append(row)

    master_found = False
    master_checkbox_count = 0
    master_row_count = 0
    master_had_syntax = False
    for match in _MASTER_ACCEPTANCE_HEADING_RE.finditer(text):
        master_found = True
        level = len(match.group(1))
        end = len(text)
        for heading in _MARKDOWN_HEADING_RE.finditer(text, match.end()):
            if len(heading.group(1)) <= level:
                end = heading.start()
                break
        section = text[match.end() : end]
        section_line = _line_number(text, match.end(), base_line=1)
        section_rows, section_issues = parse_markdown_acceptance_rows(
            section,
            require_checkbox=True,
            base_line=section_line,
        )
        issues.extend(section_issues)
        master_checkbox_count += checkbox_count(section)
        master_row_count += len(section_rows)
        master_had_syntax = master_had_syntax or bool(section_issues)
        for row in section_rows:
            if not row.id.startswith("M-A"):
                issues.append(
                    AcceptanceIssue(
                        "acceptance_id_wrong_scope",
                        f"Line {row.line}: {row.id} belongs under its Batch Acceptance section, not Master Acceptance.",
                        row.line,
                    )
                )
            rows.append(row)

    stable_mode = bool(rows) or any(
        issue.code in {"acceptance_row_syntax", "acceptance_id_invalid"}
        for issue in issues
    )
    if stable_mode:
        if not batch_ids and not batch_matches:
            # aigorahub/elves#248: pre-v2.23-era plans used `### B0 · Name`
            # headings, which look fine but never match the canonical
            # grammar — say so explicitly instead of leaving the operator to
            # diff heading shapes by eye.
            legacy_headings = re.findall(
                r"(?m)^#{2,3}\s+(B\d+)\s*[·:.\-–—]", text
            )
            hint = (
                f"Found {len(legacy_headings)} legacy heading(s) like "
                f"`### {legacy_headings[0]} · Name` — rewrite each as "
                f"`### Batch {legacy_headings[0][1:]} [{legacy_headings[0]}]: Name` "
                "(canonical grammar; see references/plan-template.md)."
                if legacy_headings
                else None
            )
            issues.append(
                AcceptanceIssue(
                    "plan_batch_required",
                    "Stable-ID plans require at least one canonical Batch heading with B#-A# Acceptance."
                    + (f" {hint}" if hint else ""),
                )
            )
        elif batch_ids and not any(
            STABLE_BATCH_ACCEPTANCE_ID_RE.fullmatch(row.id) is not None
            for row in rows
        ):
            issues.append(
                AcceptanceIssue(
                    "batch_acceptance_ids_required",
                    "Stable-ID plans require at least one B#-A# row under a Batch Acceptance section.",
                )
            )
        for batch_number, generic_count, stable_count, had_syntax in scoped_counts:
            if generic_count == 0 and stable_count == 0 and not had_syntax:
                issues.append(
                    AcceptanceIssue(
                        "acceptance_ids_required",
                        f"Batch {batch_number} stable-ID mode requires at least one Acceptance row.",
                    )
                )
            elif generic_count != stable_count and not had_syntax:
                issues.append(
                    AcceptanceIssue(
                        "acceptance_id_missing",
                        f"Batch {batch_number} stable-ID mode requires every Acceptance checkbox to carry B#-A#.",
                    )
                )
        if not master_found:
            issues.append(
                AcceptanceIssue(
                    "master_acceptance_missing",
                    "Stable-ID plans require an explicit `## Master Acceptance` section.",
                )
            )
        elif master_checkbox_count == 0 and not master_had_syntax:
            issues.append(
                AcceptanceIssue(
                    "master_acceptance_ids_required",
                    "Stable-ID plans require at least one M-A# row under Master Acceptance.",
                )
            )
        elif master_checkbox_count != master_row_count and not master_had_syntax:
            issues.append(
                AcceptanceIssue(
                    "master_acceptance_id_missing",
                    "Stable-ID mode requires every Master Acceptance checkbox to carry M-A#.",
                )
            )
    else:
        for batch_number, generic_count, _, _ in scoped_counts:
            if generic_count == 0:
                issues.append(
                    AcceptanceIssue(
                        "acceptance_criteria_required",
                        f"Batch {batch_number} has an explicit Acceptance criteria section but no "
                        "parseable checkbox criterion. Add `- [ ] <criterion>` (or a stable "
                        "`- [ ] B#-A#: <criterion>` / `- [ ] [B#-A#] <criterion>` row).",
                    )
                )
        if master_found and master_checkbox_count == 0:
            issues.append(
                AcceptanceIssue(
                    "master_acceptance_criteria_required",
                    "Master Acceptance is declared but has no parseable checkbox criterion. "
                    "Add `- [ ] <criterion>` (or a stable `- [ ] M-A#: <criterion>` / "
                    "`- [ ] [M-A#] <criterion>` row).",
                )
            )

    if len(batch_ids) != len(set(batch_ids)):
        issues.append(
            AcceptanceIssue(
                "batch_id_duplicate",
                f"Plan contains duplicate Batch ids: {batch_ids}.",
            )
        )
    seen_ids: set[str] = set()
    for row in rows:
        if row.id in seen_ids:
            issues.append(
                AcceptanceIssue(
                    "acceptance_id_duplicate",
                    f"Line {row.line}: plan contains duplicate acceptance id {row.id}.",
                    row.line,
                )
            )
        seen_ids.add(row.id)

    # Prioritize a concrete correction over aggregate defects caused by the
    # malformed row not contributing to the parsed contract.
    issues.sort(
        key=lambda item: (
            item.line is None,
            item.line if item.line is not None else 0,
            item.code,
            item.message,
        )
    )
    return PlanAcceptanceContract(
        rows=tuple(rows),
        batch_ids=tuple(batch_ids),
        issues=tuple(issues),
    )


def session_batch_numbers(
    session: Mapping[str, Any],
    *,
    expected_batch_ids: Sequence[int] | None = None,
) -> tuple[list[int | None], list[AcceptanceIssue]]:
    """Normalize session batch IDs and optionally require exact plan parity."""

    issues: list[AcceptanceIssue] = []
    batches = session.get("batches")
    if not isinstance(batches, list):
        return [], [
            AcceptanceIssue(
                "session_batches_invalid",
                "Session staging contract requires a `batches` array.",
            )
        ]

    batch_numbers: list[int | None] = []
    seen_batch_numbers: set[int] = set()
    for index, batch in enumerate(batches):
        if not isinstance(batch, Mapping):
            batch_numbers.append(None)
            issues.append(
                AcceptanceIssue(
                    "session_batch_invalid",
                    f"Session batches[{index}] must be an object.",
                )
            )
            continue
        batch_number = normalize_batch_id(batch.get("id"))
        batch_numbers.append(batch_number)
        if batch_number is None:
            issues.append(
                AcceptanceIssue(
                    "batch_id_invalid",
                    f"Session batches[{index}].id must be B0, B1+, or an unambiguous non-negative legacy integer.",
                )
            )
        elif batch_number in seen_batch_numbers:
            issues.append(
                AcceptanceIssue(
                    "batch_id_duplicate",
                    f"Session contains duplicate aliases for Batch {batch_number}.",
                )
            )
        else:
            seen_batch_numbers.add(batch_number)

    if expected_batch_ids is not None:
        expected = set(expected_batch_ids)
        for batch_number in sorted(seen_batch_numbers - expected):
            issues.append(
                AcceptanceIssue(
                    "session_batch_missing_in_plan",
                    f"Session Batch {batch_number} has no matching Batch heading in the authoritative plan.",
                )
            )
        for batch_number in sorted(expected - seen_batch_numbers):
            issues.append(
                AcceptanceIssue(
                    "plan_batch_missing_in_session",
                    f"Plan Batch {batch_number} has no matching entry in session `batches`.",
                )
            )
    return batch_numbers, issues


def session_acceptance_rows(
    session: Mapping[str, Any],
    *,
    expected_batch_ids: Sequence[int] | None = None,
) -> tuple[list[tuple[str, str]], list[AcceptanceIssue]]:
    """Flatten canonical session rows while checking IDs, scope, and duplicates."""

    rows: list[tuple[str, str]] = []
    batch_numbers, issues = session_batch_numbers(
        session,
        expected_batch_ids=expected_batch_ids,
    )
    batches = session.get("batches")
    if not isinstance(batches, list):
        return rows, issues

    for index, batch in enumerate(batches):
        if not isinstance(batch, Mapping):
            continue
        batch_number = batch_numbers[index]
        acceptance = batch.get("acceptance")
        if not isinstance(acceptance, list):
            issues.append(
                AcceptanceIssue(
                    "session_acceptance_invalid",
                    f"Session batches[{index}].acceptance must be an array.",
                )
            )
            continue
        for row_index, item in enumerate(acceptance):
            if not isinstance(item, Mapping):
                issues.append(
                    AcceptanceIssue(
                        "session_acceptance_invalid",
                        f"Session batches[{index}].acceptance[{row_index}] must be an object.",
                    )
                )
                continue
            acceptance_id = item.get("id")
            criterion = item.get("criterion")
            if not isinstance(acceptance_id, str) or STABLE_ACCEPTANCE_ID_RE.fullmatch(
                acceptance_id
            ) is None:
                issues.append(
                    AcceptanceIssue(
                        "acceptance_id_invalid",
                        f"Session batches[{index}].acceptance[{row_index}] requires a canonical B#-A# id.",
                    )
                )
                continue
            match = STABLE_BATCH_ACCEPTANCE_ID_RE.fullmatch(acceptance_id)
            acceptance_batch = (
                normalize_batch_id(match.group(1)) if match is not None else None
            )
            if (
                match is None
                or batch_number is None
                or acceptance_batch is None
                or acceptance_batch != batch_number
            ):
                issues.append(
                    AcceptanceIssue(
                        "acceptance_id_wrong_batch",
                        f"Session acceptance {acceptance_id} is not stored under its matching batch.",
                    )
                )
            if not isinstance(criterion, str) or not criterion.strip():
                issues.append(
                    AcceptanceIssue(
                        "acceptance_criterion_missing",
                        f"Session acceptance {acceptance_id} requires a non-empty criterion.",
                    )
                )
                continue
            rows.append((acceptance_id, criterion.strip()))

    master = session.get("master_acceptance")
    if not isinstance(master, list):
        issues.append(
            AcceptanceIssue(
                "session_master_acceptance_invalid",
                "Session staging contract requires a `master_acceptance` array.",
            )
        )
    else:
        for index, item in enumerate(master):
            if not isinstance(item, Mapping):
                issues.append(
                    AcceptanceIssue(
                        "session_master_acceptance_invalid",
                        f"Session master_acceptance[{index}] must be an object.",
                    )
                )
                continue
            acceptance_id = item.get("id")
            criterion = item.get("criterion")
            if (
                not isinstance(acceptance_id, str)
                or not re.fullmatch(r"M-A[0-9]+", acceptance_id)
            ):
                issues.append(
                    AcceptanceIssue(
                        "acceptance_id_wrong_scope",
                        f"Session master_acceptance[{index}] requires an M-A# id.",
                    )
                )
                continue
            if not isinstance(criterion, str) or not criterion.strip():
                issues.append(
                    AcceptanceIssue(
                        "acceptance_criterion_missing",
                        f"Session acceptance {acceptance_id} requires a non-empty criterion.",
                    )
                )
                continue
            rows.append((acceptance_id, criterion.strip()))

    seen: set[str] = set()
    for acceptance_id, _ in rows:
        if acceptance_id in seen:
            issues.append(
                AcceptanceIssue(
                    "acceptance_id_duplicate",
                    f"Session contains duplicate acceptance id {acceptance_id}.",
                )
            )
        seen.add(acceptance_id)
    return rows, issues


def validate_contract_mapping(
    plan_rows: Sequence[AcceptanceRow],
    session: Mapping[str, Any],
    *,
    plan_batch_ids: Sequence[int] | None = None,
    packet_rows: Sequence[tuple[str, str]] | None = None,
) -> list[AcceptanceIssue]:
    """Validate plan/session[/packet] ID and criterion parity for staging."""

    issues: list[AcceptanceIssue] = []
    plan_by_id: dict[str, str] = {}
    for row in plan_rows:
        if row.id in plan_by_id:
            issues.append(
                AcceptanceIssue(
                    "acceptance_id_duplicate",
                    f"Plan contains duplicate acceptance id {row.id}.",
                    row.line,
                )
            )
        else:
            plan_by_id[row.id] = row.criterion

    if plan_batch_ids is None:
        derived_batch_ids: set[int] = set()
        for row in plan_rows:
            match = STABLE_BATCH_ACCEPTANCE_ID_RE.fullmatch(row.id)
            if match is not None:
                number = normalize_batch_id(match.group(1))
                if number is not None:
                    derived_batch_ids.add(number)
        plan_batch_ids = tuple(sorted(derived_batch_ids))

    session_rows, session_issues = session_acceptance_rows(
        session,
        expected_batch_ids=plan_batch_ids,
    )
    issues.extend(session_issues)
    session_by_id = dict(session_rows)
    for acceptance_id in sorted(set(plan_by_id) | set(session_by_id)):
        expected = plan_by_id.get(acceptance_id)
        observed = session_by_id.get(acceptance_id)
        if expected is None:
            issues.append(
                AcceptanceIssue(
                    "acceptance_evidence_unrelated",
                    f"Session acceptance {acceptance_id} is not present in the authoritative plan.",
                )
            )
        elif observed is None:
            issues.append(
                AcceptanceIssue(
                    "acceptance_evidence_missing",
                    f"Plan acceptance {acceptance_id} is missing from the session staging rows.",
                )
            )
        elif observed != expected:
            issues.append(
                AcceptanceIssue(
                    "acceptance_criterion_mismatch",
                    f"Session criterion for {acceptance_id} does not match the authoritative plan: expected {expected!r}, got {observed!r}.",
                )
            )

    if packet_rows is not None:
        packet_by_id = dict(packet_rows)
        if len(packet_by_id) != len(packet_rows):
            issues.append(
                AcceptanceIssue(
                    "acceptance_id_duplicate",
                    "Full-run packet contains duplicate stable acceptance ids.",
                )
            )
        for acceptance_id in sorted(set(plan_by_id) | set(packet_by_id)):
            expected = plan_by_id.get(acceptance_id)
            observed = packet_by_id.get(acceptance_id)
            if expected is None:
                issues.append(
                    AcceptanceIssue(
                        "acceptance_packet_unrelated",
                        f"Packet acceptance {acceptance_id} is not present in the authoritative plan.",
                    )
                )
            elif observed is None:
                issues.append(
                    AcceptanceIssue(
                        "acceptance_packet_missing",
                        f"Plan acceptance {acceptance_id} is missing from the full-run packet.",
                    )
                )
            elif observed != expected:
                issues.append(
                    AcceptanceIssue(
                        "acceptance_packet_criterion_mismatch",
                        f"Packet criterion for {acceptance_id} does not match the authoritative plan: expected {expected!r}, got {observed!r}.",
                    )
                )
    return issues


def sync_session_acceptance(
    session: Mapping[str, Any],
    plan_rows: Sequence[AcceptanceRow],
) -> tuple[dict[str, Any], list[AcceptanceIssue]]:
    """Derive session acceptance rows from the plan without erasing proof.

    Matching rows preserve all runtime fields while their criterion is sourced
    from the plan.  Removing or changing an already completed/evidenced row is
    refused; staging rows with no proof can be safely regenerated.
    """

    updated = deepcopy(dict(session))
    issues: list[AcceptanceIssue] = []
    raw_batches = updated.get("batches")
    if raw_batches is None:
        raw_batches = []
        updated["batches"] = raw_batches
    elif not isinstance(raw_batches, list):
        return updated, [
            AcceptanceIssue(
                "session_batches_invalid",
                "Session batches must be an array before synchronization; refusing to replace malformed data.",
            )
        ]

    batches_by_number: dict[int, dict[str, Any]] = {}
    for index, item in enumerate(raw_batches):
        if not isinstance(item, dict):
            issues.append(
                AcceptanceIssue(
                    "session_batch_invalid",
                    f"Session batches[{index}] must be an object before synchronization.",
                )
            )
            continue
        number = normalize_batch_id(item.get("id"))
        if number is None:
            issues.append(
                AcceptanceIssue(
                    "batch_id_invalid",
                    f"Session batches[{index}].id is not a canonical or legacy non-negative batch id.",
                )
            )
            continue
        if number in batches_by_number:
            issues.append(
                AcceptanceIssue(
                    "batch_id_duplicate",
                    f"Session contains duplicate aliases for Batch {number}.",
                )
            )
            continue
        batches_by_number[number] = item

    plan_batches: dict[int, list[AcceptanceRow]] = {}
    plan_master: list[AcceptanceRow] = []
    for row in plan_rows:
        match = STABLE_BATCH_ACCEPTANCE_ID_RE.fullmatch(row.id)
        if match is None:
            plan_master.append(row)
        else:
            number = normalize_batch_id(match.group(1))
            if number is not None:
                plan_batches.setdefault(number, []).append(row)

    def _has_proof(item: Mapping[str, Any], *, parent_complete: bool = False) -> bool:
        return (
            parent_complete
            or item.get("met") is True
            or bool(str(item.get("evidence") or "").strip())
        )

    retained_batches: list[Any] = []
    for item in raw_batches:
        if not isinstance(item, dict):
            retained_batches.append(item)
            continue
        number = normalize_batch_id(item.get("id"))
        if number is None or number in plan_batches:
            retained_batches.append(item)
            continue

        parent_complete = (
            str(item.get("status") or "").strip().lower() == "complete"
        )
        acceptance = item.get("acceptance")
        rows = acceptance if isinstance(acceptance, list) else []
        has_proof = parent_complete or any(
            not isinstance(row, Mapping)
            or _has_proof(row, parent_complete=parent_complete)
            for row in rows
        )
        if acceptance is not None and not isinstance(acceptance, list):
            has_proof = True
        if has_proof:
            issues.append(
                AcceptanceIssue(
                    "acceptance_sync_would_erase_proof",
                    f"Refusing to remove completed, evidenced, or malformed obsolete Batch {number}.",
                )
            )
            retained_batches.append(item)
            continue
        batches_by_number.pop(number, None)

    raw_batches[:] = retained_batches

    def _sync_rows(
        existing: Any,
        expected: Sequence[AcceptanceRow],
        *,
        scope: str,
        parent_complete: bool = False,
    ) -> list[dict[str, Any]]:
        current = existing if isinstance(existing, list) else []
        by_id: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(current):
            if not isinstance(item, dict):
                issues.append(
                    AcceptanceIssue(
                        "session_acceptance_invalid",
                        f"{scope}[{index}] must be an object before synchronization.",
                    )
                )
                continue
            acceptance_id = str(item.get("id") or "")
            if acceptance_id in by_id:
                issues.append(
                    AcceptanceIssue(
                        "acceptance_id_duplicate",
                        f"{scope} contains duplicate acceptance id {acceptance_id!r}.",
                    )
                )
                continue
            by_id[acceptance_id] = item

        expected_ids = {row.id for row in expected}
        for acceptance_id, item in by_id.items():
            if acceptance_id not in expected_ids and _has_proof(
                item, parent_complete=parent_complete
            ):
                issues.append(
                    AcceptanceIssue(
                        "acceptance_sync_would_erase_proof",
                        f"Refusing to remove evidenced {scope} row {acceptance_id!r}.",
                    )
                )

        result: list[dict[str, Any]] = []
        for row in expected:
            item = deepcopy(by_id.get(row.id, {}))
            observed = str(item.get("criterion") or "").strip()
            if observed != row.criterion and _has_proof(
                item, parent_complete=parent_complete
            ):
                issues.append(
                    AcceptanceIssue(
                        "acceptance_sync_would_rewrite_proof",
                        f"Refusing to rewrite evidenced criterion for {row.id}: expected {row.criterion!r}, found {observed!r}.",
                    )
                )
            item["id"] = row.id
            item["criterion"] = row.criterion
            item.setdefault("met", False)
            item.setdefault("evidence", "")
            result.append(item)
        return result

    for number, expected in sorted(plan_batches.items()):
        batch = batches_by_number.get(number)
        if batch is None:
            batch = {
                "id": f"B{number}",
                "status": "pending",
                "acceptance": [],
            }
            raw_batches.append(batch)
            batches_by_number[number] = batch
        existing_acceptance = batch.get("acceptance")
        if existing_acceptance is not None and not isinstance(
            existing_acceptance, list
        ):
            issues.append(
                AcceptanceIssue(
                    "session_acceptance_invalid",
                    f"Batch {number} acceptance must be an array; refusing to replace malformed data.",
                )
            )
            continue
        batch["acceptance"] = _sync_rows(
            existing_acceptance,
            expected,
            scope=f"Batch {number} acceptance",
            parent_complete=(
                str(batch.get("status") or "").strip().lower() == "complete"
            ),
        )

    existing_master = updated.get("master_acceptance")
    if existing_master is not None and not isinstance(existing_master, list):
        issues.append(
            AcceptanceIssue(
                "session_master_acceptance_invalid",
                "Session master_acceptance must be an array; refusing to replace malformed data.",
            )
        )
    else:
        updated["master_acceptance"] = _sync_rows(
            existing_master,
            plan_master,
            scope="master_acceptance",
        )
    return updated, issues


def checkbox_count(markdown: str) -> int:
    """Count active task-list rows in one already scoped section."""

    return len(list(_CHECKBOX_RE.finditer(active_markdown(markdown))))
