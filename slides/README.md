# Slides

The three decks, as exported on 11 July 2026.

| | |
|---|---|
| [Session 1 — Distributed architectures](session-1-distributed-architectures.pdf) | The monolith, the eight fallacies, and where you would cut it |
| [Session 2 — API design](session-2-api-design.pdf) | REST at the edge, gRPC inside, and the contracts between them |
| [Session 3 — Building microservices](session-3-building-microservices.pdf) | Three services, then breaking them on purpose |

## Where a slide and the code disagree, the code is right

These were written before the system was built. The contracts and the services then made
decisions the decks could not have known about — the clearest being that payments listens
on **50051**, not the `9090` a couple of slides still show, and that the health endpoint
is `/health` rather than `/healthz`.

So read `contracts/` and `services/` as the source of truth, and the decks as the
argument for why they ended up looking the way they do. Every disagreement a machine can
find is listed by:

```bash
uv run --with pypdf python conformance/slides.py
```

which is the same idea as `conformance/contract.py`, pointed at the slides instead of at
a running service. It currently reports thirteen, and it will keep reporting them until
the decks are re-exported.

## Why a PDF is in git at all

Several READMEs here insist there is no generated code in this repository and none in
git, and every Dockerfile regenerates its protobuf stubs at build time to keep that true.

A committed PDF looks like that rule being broken by the person who wrote it. It is not,
and the distinction is worth knowing: **the rule is about artifacts you can rebuild.**
You can regenerate `payments_pb2.py` with one documented command, so it does not belong
in git. You cannot rebuild this deck — you have neither the source, nor the fonts, nor
the tool. That makes it a release artifact rather than a build artifact, and release
artifacts ship.

The diagrams inside them, on the other hand, *are* rebuildable, which is why
[`../diagrams`](../diagrams) exists.
