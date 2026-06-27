#!/usr/bin/env python3
"""Regression tests for author-list formatting in acl_natbib.bst.

These tests exercise the ``format.names`` function, which is responsible for
rendering the author list of every bibliography entry. They specifically guard
against the regression reported in
https://github.com/acl-org/acl-style-files/issues/49 where a bib entry whose
author field literally ended with ``and others`` was rendered as
``A, B, and 1 others`` instead of ``A, B, et al.``.

The two behaviours that must coexist are:

1. *Truncation* of very long author lists (more than 20 authors): the first 19
   authors are shown, followed by ``and N others`` where ``N`` is the number of
   authors that were dropped.
2. *Literal* ``and others`` in the bib entry: rendered as ``et al.`` with no
   bogus count.

The tests drive the real ``bibtex`` binary against the style file and parse the
generated ``.bbl`` so that they validate the actual shipped behaviour rather
than a re-implementation of it.

Usage:
    python3 tests/regression/run_tests.py

Exits 0 if all cases pass, 1 otherwise. Requires ``bibtex`` on PATH.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BST = os.path.join(REPO_ROOT, "acl_natbib.bst")
YEAR = "1000"          # sentinel year used to delimit the author segment
TITLE = "ZZZTITLE"     # sentinel title (rendered after the year)


def syn_tokens(n):
    """n single-word synthetic author surnames: A01, A02, ..."""
    return [f"A{i:02d}" for i in range(1, n + 1)]


def bib_author(tokens, has_others):
    parts = list(tokens)
    if has_others:
        parts.append("others")
    return " and ".join(parts)


def expected_render(display, has_others):
    """Reference implementation of the spec that format.names must satisfy.

    ``display`` is the list of author surnames as they should appear (synthetic
    tokens are single words, so they render verbatim). ``has_others`` indicates
    whether the bib author field ends with a literal ``and others``.
    """
    numnames = len(display) + (1 if has_others else 0)

    # 1. Truncation path: more than 20 names total.
    if numnames > 20:
        shown = display[:19]
        dropped = numnames - 19
        return ", ".join(shown) + f", and {dropped} others"

    # 2. Literal "and others" -> et al. (no count).
    if has_others:
        if numnames == 2:          # exactly one real author + others
            return f"{display[0]} et al"
        return ", ".join(display) + ", et al"

    # 3. Ordinary, fully-listed author list.
    n = len(display)
    if n == 1:
        return display[0]
    if n == 2:
        return f"{display[0]} and {display[1]}"
    return ", ".join(display[:-1]) + f", and {display[-1]}"


def normalize(s):
    """Normalize a rendered author string for comparison.

    Collapses whitespace, turns BibTeX ties (~) into spaces (so ``et~al`` and
    ``John~Smith`` compare cleanly), and strips the trailing sentence period.
    """
    s = s.replace("~", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s.rstrip(". ").strip()


def build_cases():
    cases = []  # each: dict(key, author, expected)

    def add(key, tokens, has_others, display=None, expected=None):
        display = display if display is not None else tokens
        exp = expected if expected is not None else expected_render(display, has_others)
        cases.append({
            "key": key,
            "author": bib_author(tokens, has_others),
            "expected": normalize(exp),
        })

    # --- Hand-written golden cases (expected strings written out literally) ---
    add("g_one", ["Aa"], False, expected="Aa")
    add("g_two", ["Aa", "Bb"], False, expected="Aa and Bb")
    add("g_three", ["Aa", "Bb", "Cc"], False, expected="Aa, Bb, and Cc")
    add("g_four", ["Aa", "Bb", "Cc", "Dd"], False,
        expected="Aa, Bb, Cc, and Dd")
    # The regression: literal "and others" with few authors.
    add("g_one_others", ["Aa"], True, expected="Aa et al")
    add("g_two_others", ["Aa", "Bb"], True, expected="Aa, Bb, et al")
    add("g_three_others", ["Aa", "Bb", "Cc"], True,
        expected="Aa, Bb, Cc, et al")
    # Truncation goldens.
    add("g_21", syn_tokens(21), False, expected=(
        "A01, A02, A03, A04, A05, A06, A07, A08, A09, A10, A11, A12, A13, "
        "A14, A15, A16, A17, A18, A19, and 2 others"))
    add("g_25", syn_tokens(25), False, expected=(
        "A01, A02, A03, A04, A05, A06, A07, A08, A09, A10, A11, A12, A13, "
        "A14, A15, A16, A17, A18, A19, and 6 others"))

    # --- Realistic multi-token names (first/last) ---
    cases.append({
        "key": "r_two_full",
        "author": "John Smith and Jane Doe",
        "expected": normalize("John Smith and Jane Doe"),
    })
    cases.append({
        "key": "r_three_full_others",
        "author": "John Smith and Jane Doe and others",
        "expected": normalize("John Smith, Jane Doe, et al"),
    })
    cases.append({
        "key": "r_lastfirst_others",
        "author": "Smith, John and Doe, Jane and others",
        "expected": normalize("John Smith, Jane Doe, et al"),
    })

    # --- Bulk: fully-listed author lists, n = 1..30 (no "others") ---
    for n in range(1, 31):
        add(f"bulk_noother_{n:03d}", syn_tokens(n), False)

    # --- Bulk: author lists ending in literal "and others", r = 1..29 ---
    for r in range(1, 30):
        add(f"bulk_others_{r:03d}", syn_tokens(r), True)

    return cases


def run_bibtex(cases, workdir):
    shutil.copy(BST, os.path.join(workdir, "acl_natbib.bst"))

    with open(os.path.join(workdir, "refs.bib"), "w") as fh:
        for c in cases:
            fh.write(
                "@misc{%s,\n  author = {%s},\n  title = {%s},\n  year = {%s}\n}\n\n"
                % (c["key"], c["author"], TITLE, YEAR)
            )

    with open(os.path.join(workdir, "test.aux"), "w") as fh:
        fh.write("\\relax\n\\bibstyle{acl_natbib}\n\\bibdata{refs}\n")
        for c in cases:
            fh.write("\\citation{%s}\n" % c["key"])

    proc = subprocess.run(
        ["bibtex", "test"],
        cwd=workdir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # bibtex returns 0 on success, and a non-zero status for warnings (1),
    # errors (2), or fatal problems (3). The test entries are deliberately
    # minimal and should never produce warnings, so treat any non-zero exit
    # as a hard failure and surface bibtex's own output for debugging rather
    # than silently parsing a possibly-incomplete .bbl.
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        raise SystemExit(
            f"bibtex exited with status {proc.returncode}; see output above"
        )
    bbl_path = os.path.join(workdir, "test.bbl")
    if not os.path.exists(bbl_path):
        sys.stderr.write(proc.stdout)
        raise SystemExit("bibtex did not produce a .bbl file")
    with open(bbl_path) as fh:
        return fh.read()


def parse_bbl(text):
    """Return {citekey: normalized rendered author string}."""
    out = {}
    for chunk in text.split("\\bibitem")[1:]:
        keym = re.search(r"\]\{([^}]+)\}", chunk)
        if not keym:
            continue
        key = keym.group(1)
        body = chunk[keym.end():].split("\\newblock")[0]
        author_seg = body.split(YEAR)[0]
        out[key] = normalize(author_seg)
    return out


def main():
    if shutil.which("bibtex") is None:
        raise SystemExit("bibtex not found on PATH; cannot run regression tests")
    if not os.path.exists(BST):
        raise SystemExit(f"style file not found: {BST}")

    cases = build_cases()
    with tempfile.TemporaryDirectory() as workdir:
        bbl = run_bibtex(cases, workdir)
    rendered = parse_bbl(bbl)

    failures = []
    for c in cases:
        actual = rendered.get(c["key"])
        if actual != c["expected"]:
            failures.append((c["key"], c["author"], c["expected"], actual))

    total = len(cases)
    passed = total - len(failures)
    print(f"Author-list regression suite: {passed}/{total} passed")
    if failures:
        print("\nFAILURES:")
        for key, author, exp, act in failures:
            print(f"  [{key}]")
            print(f"    author:   {author}")
            print(f"    expected: {exp!r}")
            print(f"    actual:   {act!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
