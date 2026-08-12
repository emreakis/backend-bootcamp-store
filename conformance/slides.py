#!/usr/bin/env python3
"""The slides, checked against the code they describe.

    uv run --with pypdf python conformance/slides.py
    uv run --with pypdf python conformance/slides.py --slides ../slides

`contract.py` asserts that six implementations agree with one contract. This asserts
that the three decks agree with the same contract — because they are the one artifact in
this bootcamp that nothing else was checking, and a month of drift is what that bought.

Every check below is here because it was true on 2026-08-12: the decks were written on
11 July, the system was built on 12 August, and by the afternoon they disagreed about the
payments port, the health path, two message names, the proto package, and which
`docker compose` subcommand demonstrates an outage. None of that is exotic. It is what
happens to any document that no build step can fail on.

Where possible the expected value is READ FROM THE REPO rather than written down here —
the port comes out of the compose file, the type names out of the .proto. A check that
hard-codes what it is checking has the same drift problem one layer down.

This is the only script in `conformance/` that is not stdlib-only: reading a PDF needs
`pypdf`. `uv run --with pypdf` keeps that from becoming an install step, the same trick
`contracts/README.md` uses for grpcio-tools.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from pypdf import PdfReader
except ModuleNotFoundError:
    sys.exit("needs pypdf — run:  uv run --with pypdf python conformance/slides.py")

GREEN, RED, DIM, YELLOW, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[33m", "\033[0m"

ROOT = Path(__file__).resolve().parent.parent

passed: list[str] = []
failed: list[str] = []


def check(name: str, condition: object, detail: str = "") -> None:
    if condition:
        passed.append(name)
        print(f"  {GREEN}PASS{RESET}  {name}")
    else:
        failed.append(name)
        print(f"  {RED}FAIL{RESET}  {name}" + (f"\n          {detail}" if detail else ""))


# --- what the repo actually says ---------------------------------------------


def payments_port() -> str:
    """From the compose file, because that is what runs."""
    text = (ROOT / "services" / "docker-compose.yml").read_text(encoding="utf-8")
    m = re.search(r"PAYMENTS_ADDR:\s*payments:(\d+)", text)
    return m.group(1) if m else "50051"


def proto_facts() -> tuple[str, set[str], str]:
    """Package, declared type names, and the retry-safety field — from the .proto."""
    text = (ROOT / "contracts/proto/bootcamp/payments/v1/payments.proto").read_text(
        encoding="utf-8"
    )
    package = re.search(r"^package\s+([\w.]+);", text, re.M)
    names = set(re.findall(r"^\s*(?:message|enum)\s+(\w+)", text, re.M))
    names |= set(re.findall(r"^\s*rpc\s+(\w+)", text, re.M))

    # The field the Session 3 retry rests on, named by the contract rather than by us.
    body = re.search(r"message ChargeRequest \{(.*?)\n\}", text, re.S)
    fields = re.findall(r"^\s*\w+\s+(\w+)\s*=\s*\d+;", body.group(1), re.M) if body else []
    idempotency = next((f for f in fields if "idempot" in f), "idempotency_key")

    return (package.group(1) if package else "bootcamp.payments.v1"), names, idempotency


def repo_slug() -> str:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"github\.com/([\w-]+/[\w-]+)", text)
    return m.group(1) if m else "emreakis/backend-bootcamp-store"


def health_path() -> str:
    """Whatever the contract calls it — /health here, and not /healthz."""
    text = (ROOT / "contracts" / "orders.v1.yaml").read_text(encoding="utf-8")
    m = re.search(r"^\s{2}(/health\w*):", text, re.M)
    return m.group(1) if m else "/health"


# Words that look like a protobuf type but are ordinary English on a slide. Anything
# matching the pattern and NOT in this list has to be declared in the .proto.
PROSE = {"HTTPStatus", "ResponseStatus", "OrderStatus"}
TYPEISH = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:Request|Response|Reply|Event)\b")


def load_decks(folder: Path) -> dict[int, tuple[str, str]]:
    """{session number: (filename, text)} — matches either naming convention."""
    decks: dict[int, tuple[str, str]] = {}
    for pdf in sorted(folder.glob("*.pdf")):
        m = re.search(r"session[ _-]*([123])", pdf.name, re.I)
        if not m:
            continue
        text = "\n".join((p.extract_text() or "") for p in PdfReader(pdf).pages)
        decks[int(m.group(1))] = (pdf.name, text)
    return decks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slides", default=str(ROOT / "slides"))
    args = parser.parse_args()

    folder = Path(args.slides).resolve()
    if not folder.is_dir():
        print(f"\n  {DIM}no slides at {folder} — nothing to check{RESET}\n")
        return 0

    decks = load_decks(folder)
    if not decks:
        print(f"\n  {YELLOW}{folder} has no session PDFs in it{RESET}\n")
        return 1

    port = payments_port()
    package, declared, idempotency = proto_facts()
    slug = repo_slug()
    health = health_path()

    print(f"\nSlides in {folder}")
    print(f"{DIM}checked against payments:{port}, package {package}, {slug}{RESET}")

    check("all three decks are present", set(decks) == {1, 2, 3},
          f"found sessions {sorted(decks)}")

    for n in sorted(decks):
        name, text = decks[n]
        flat = " ".join(text.split())
        print(f"\n{DIM}{name}{RESET}\n")

        # The one that costs a participant the most: they cannot find any of this.
        check(f"s{n}: names the repository", slug in flat or slug.split("/")[1] in flat,
              f"no '{slug}' anywhere in {len(text)} characters — the room cannot find "
              f"the code, the contracts or the exercises")

        # Ports and paths people will type.
        check(f"s{n}: no stale payments port", "9090" not in flat,
              f"9090 appears; payments listens on {port}")

        check(f"s{n}: health path is {health}", "/healthz" not in flat,
              f"/healthz appears; every service in this repo serves {health}")

        # Type names, derived: anything shaped like a protobuf message must be one.
        unknown = {t for t in TYPEISH.findall(flat)
                   if t not in declared and t not in PROSE}
        check(f"s{n}: protobuf type names exist", not unknown,
              f"{sorted(unknown)} are not declared in payments.proto — it has "
              f"{sorted(n for n in declared if 'Charge' in n or 'Watch' in n)}")

        # The proto package, whose flat form is a real bug this repo already hit.
        if "package" in flat and "payments.v1" in flat:
            check(f"s{n}: proto package is {package}", package in flat,
                  f"a flat 'payments.v1' makes protoc emit a top-level 'payments' "
                  f"module that collides with the next service; see the .proto header")

        # A deck that shows the charge message must show the field that makes the
        # Session 3 retry legal rather than a double-billing bug.
        if "ChargeRequest" in flat:
            check(f"s{n}: ChargeRequest carries {idempotency}",
                  idempotency in flat,
                  "the retry exercise depends on this field existing; without it the "
                  "deck asks for a retry that charges the customer twice")

        # Paths carry their version in this system.
        bare = len(re.findall(r"(?<!/v1)/(?:orders|products)\b", flat))
        check(f"s{n}: paths carry /v1", bare == 0,
              f"{bare} unversioned path(s) — the API serves /v1/orders and /v1/products")

    # Session 3 only: the outage the exercise demonstrates has to be the deterministic
    # one, or the room splits three ways on the same command.
    if 3 in decks:
        flat = " ".join(decks[3][1].split())
        print(f"\n{DIM}session 3 — the exercise{RESET}\n")
        check("s3: the demonstrated outage is `pause`", "pause" in flat,
              "a stopped payments fails in ~4s on C#, ~20s on Python/Go/Ruby and never "
              "on Java/TypeScript, so `stop` shows a different lesson to each third of "
              "the room; `pause` hangs identically in all six")

    total = len(passed) + len(failed)
    print(f"\n  {GREEN}{len(passed)} passed{RESET}"
          + (f", {RED}{len(failed)} failed{RESET}" if failed else "")
          + f"  ({total} checks)\n")
    for name in failed:
        print(f"    {RED}x{RESET} {name}")
    if failed:
        print(f"\n  {DIM}Every one of these was found by hand on 2026-08-12 and written"
              f" down in slide-errata.md.{RESET}")
        print(f"  {DIM}The point of this file is that nobody has to do that again.{RESET}\n")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
