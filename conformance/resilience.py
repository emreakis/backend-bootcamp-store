#!/usr/bin/env python3
"""The Session 3 exercise, as a test.

    python conformance/resilience.py            # against the running stack
    python conformance/resilience.py --expect-fixed

`contract.py` asks whether a service is correct when everything works.  This asks the
question Session 3 is actually about: what happens when it doesn't.

TWO MODES, AND THE DIFFERENCE IS THE POINT.

By default this asserts the STARTER behaviour — that a slow payments service hangs
checkout, and that orders keeps reporting itself perfectly healthy while it does. Those
are passing tests describing a broken system, which is an odd thing to write down until
you notice that the alternative is a broken system nobody wrote down.

With `--expect-fixed` it asserts the SOLUTION: the same outage produces a fast, honest
503 carrying Retry-After, and `/health` still says ok because orders is not sick — its
dependency is.

So the four TODO blocks in the orders service are the diff between two runs of this
file. Run it before you start, run it after each exercise, and watch the expectations
flip one at a time:

    python conformance/resilience.py                 # red -> green, before
    ... implement exercise 3.1 ...
    python conformance/resilience.py --expect-fixed  # red -> green, after

It manipulates the stack with `docker compose`, so run it from the repo root with the
services up, and expect it to take a couple of minutes: it deliberately spends real
seconds waiting for things that never arrive.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"

SERVICES = Path(__file__).resolve().parent.parent / "services"

passed: list[str] = []
failed: list[str] = []


def check(name: str, condition: object, detail: str = "") -> None:
    if condition:
        passed.append(name)
        print(f"  {GREEN}PASS{RESET}  {name}")
    else:
        failed.append(name)
        print(f"  {RED}FAIL{RESET}  {name}" + (f"\n          {detail}" if detail else ""))


def compose(*args: str, env: dict[str, str] | None = None) -> None:
    """Run docker compose in services/, inheriting the environment plus `env`."""
    import os

    merged = {**os.environ, **(env or {})}
    subprocess.run(["docker", "compose", *args], cwd=SERVICES, env=merged,
                   check=False, capture_output=True)


def post_order(base: str, timeout: float) -> tuple[int, dict | None, dict, float]:
    """POST a checkout and report how long it took, or how long we waited in vain."""
    body = json.dumps({"items": [{"sku": "GRD-002", "qty": 1}]}).encode()
    request = urllib.request.Request(f"{base}/v1/orders", data=body, method="POST")
    request.add_header("content-type", "application/json")
    request.add_header("Idempotency-Key", f"resilience-{uuid.uuid4()}")

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
            return (response.status, json.loads(raw) if raw else None,
                    {k.lower(): v for k, v in response.headers.items()},
                    time.monotonic() - started)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        return (exc.code, json.loads(raw) if raw else None,
                {k.lower(): v for k, v in exc.headers.items()},
                time.monotonic() - started)
    except Exception:
        # A socket timeout on our side. The server never answered — which, before the
        # exercise, is the correct observation to make.
        return 0, None, {}, time.monotonic() - started


def health(base: str) -> tuple[int, dict | None]:
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except Exception:
        return 0, None


def wait_until_healthy(base: str, seconds: int = 60) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if health(base)[0] == 200:
            return True
        time.sleep(1)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orders", default="http://localhost:8080")
    parser.add_argument("--expect-fixed", action="store_true",
                        help="assert the solution branch's behaviour instead of the starter's")
    parser.add_argument("--patience", type=float, default=15.0,
                        help="seconds to wait for a checkout before calling it hung")
    args = parser.parse_args()

    mode = "SOLUTION" if args.expect_fixed else "STARTER"
    print(f"\nResilience check against {args.orders}, expecting {mode} behaviour")

    if not wait_until_healthy(args.orders):
        print(f"\n  {RED}orders is not answering /health — bring the stack up first{RESET}\n")
        return 1

    # =======================================================================
    #  Baseline: with payments healthy, a checkout works and is quick.
    # =======================================================================
    print(f"\n{DIM}payments healthy{RESET}\n")
    compose("up", "-d", "payments", env={"PAYMENT_LATENCY_MS": "0"})
    time.sleep(6)

    status, _, _, took = post_order(args.orders, args.patience)
    check("baseline: checkout succeeds", status == 201, f"got {status}")
    check("baseline: and is fast", took < 3.0, f"took {took:.2f}s")

    # =======================================================================
    #  PAYMENTS IS SLOW. The failure this session exists for.
    #
    #  30 seconds of latency, against an orders timeout of 2000 ms. Everything
    #  about payments is working — it accepted the connection, it is executing
    #  the method, it will eventually answer. It is simply slower than anybody
    #  is prepared to wait, which is the failure mode that hurts most and the
    #  one people design for least.
    # =======================================================================
    print(f"\n{DIM}payments SLOW (PAYMENT_LATENCY_MS=30000){RESET}\n")
    compose("up", "-d", "--force-recreate", "payments",
            env={"PAYMENT_LATENCY_MS": "30000"})
    time.sleep(6)

    status, payload, headers, took = post_order(args.orders, args.patience)

    if args.expect_fixed:
        check("slow: checkout fails fast rather than hanging",
              took < 10.0, f"took {took:.2f}s")
        check("slow: 503, because the customer did nothing wrong",
              status == 503, f"got {status}")
        check("slow: problem+json",
              "application/problem+json" in headers.get("content-type", ""),
              f"got {headers.get('content-type')!r}")
        check("slow: type is payments-unavailable",
              isinstance(payload, dict)
              and str(payload.get("type", "")).endswith("payments-unavailable"),
              f"got {payload!r}")
        # A 503 without Retry-After tells the client something is wrong but not what to
        # do about it, so every well-behaved one guesses — and they all guess the same
        # aggressive number at the same moment.
        check("slow: carries Retry-After", "retry-after" in headers,
              f"headers were {sorted(headers)}")
    else:
        check(f"slow: checkout HANGS (no answer in {args.patience:.0f}s)",
              status == 0, f"got {status} after {took:.2f}s — has 3.1 been done already?")

    # THE POINT OF THE WHOLE SESSION, IN ONE ASSERTION.
    #
    # Orders is completely healthy. Its process is up, its database is fine, its own code
    # has no bug. And it cannot take an order. That gap — between "this service is
    # working" and "this service is useful" — is what a dependency does to you, and it is
    # true in both modes, which is why this check is outside the if.
    status, body = health(args.orders)
    check("slow: /health still says ok — orders is not sick, its dependency is",
          status == 200 and isinstance(body, dict) and body.get("status") == "ok",
          f"got {status} {body!r}")

    # =======================================================================
    #  PAYMENTS IS A BLACK HOLE. `pause`, not `stop`.
    #
    #  A paused container keeps its address and its socket, and answers nothing.
    #  SYN packets arrive and are never acknowledged, which is what a crashed host,
    #  a dropped route or a network partition looks like from the outside — and
    #  unlike `stop`, it behaves identically in every language.
    #
    #  To a caller with no deadline this is indistinguishable from "slow", which is
    #  the point: the deadline, not the outage, is what you fix first.
    # =======================================================================
    print(f"\n{DIM}payments BLACK-HOLED (paused){RESET}\n")
    compose("unpause", "payments")     # in case a previous run died mid-flight
    compose("pause", "payments")
    time.sleep(2)

    status, payload, headers, took = post_order(args.orders, args.patience)

    if args.expect_fixed:
        check("black hole: checkout fails fast", took < 10.0, f"took {took:.2f}s")
        check("black hole: 503", status == 503, f"got {status}")
        check("black hole: type is payments-unavailable",
              isinstance(payload, dict)
              and str(payload.get("type", "")).endswith("payments-unavailable"),
              f"got {payload!r}")
    else:
        check(f"black hole: checkout HANGS TOO (no answer in {args.patience:.0f}s)",
              status == 0,
              f"got {status} after {took:.2f}s — this should look exactly like 'slow'")

    status, body = health(args.orders)
    check("black hole: /health still says ok",
          status == 200 and isinstance(body, dict) and body.get("status") == "ok",
          f"got {status} {body!r}")

    compose("unpause", "payments")
    time.sleep(3)

    # =======================================================================
    #  PAYMENTS IS STOPPED. Measured, and deliberately NOT asserted in starter mode.
    #
    #  This is the one people expect to be simple, and it is the one that is not.
    #  A stopped container loses its DNS entry and its address, so the failure
    #  arrives through a different path than the black hole above — and how long
    #  that takes is decided entirely by the gRPC library you happen to be using.
    #
    #  Measured on this stack, with no deadline anywhere:
    #
    #      C#                  fails in ~4 s
    #      Python, Go, Ruby    fail in ~20 s   (the library's own connect timeout)
    #      Java, TypeScript    still waiting after 25 s
    #
    #  Same outage, same contract, four seconds to never. THAT is the argument for
    #  the deadline: without one, how long your checkout hangs is a property of
    #  somebody else's default. Twenty seconds is not "fast" for a checkout either;
    #  it is a hang with extra steps.
    #
    #  So this is only asserted once a deadline exists, where all six agree.
    # =======================================================================
    print(f"\n{DIM}payments DOWN (stopped) — timing varies by language{RESET}\n")
    compose("stop", "payments")
    time.sleep(3)

    status, payload, headers, took = post_order(args.orders, args.patience)

    if args.expect_fixed:
        check("down: checkout fails fast", took < 10.0, f"took {took:.2f}s")
        check("down: 503", status == 503, f"got {status}")
        check("down: type is payments-unavailable",
              isinstance(payload, dict)
              and str(payload.get("type", "")).endswith("payments-unavailable"),
              f"got {payload!r}")
    else:
        answer = "no answer" if status == 0 else f"{status}"
        print(f"  {DIM}note{RESET}  down: {answer} after {took:.2f}s "
              f"— not asserted, because this is your library's number and not yours")

    status, body = health(args.orders)
    check("down: /health still says ok",
          status == 200 and isinstance(body, dict) and body.get("status") == "ok",
          f"got {status} {body!r}")

    # =======================================================================
    #  Recovery. A service that fails well also has to come back on its own.
    # =======================================================================
    print(f"\n{DIM}payments back{RESET}\n")
    compose("up", "-d", "--force-recreate", "payments", env={"PAYMENT_LATENCY_MS": "0"})
    time.sleep(8)

    # Two attempts, because with a circuit breaker in place the first request after
    # recovery may legitimately be the one that finds the breaker still open. A breaker
    # that never closes again is not resilience, it is a permanent outage you built
    # yourself — so the second attempt has to work.
    status, _, _, _ = post_order(args.orders, args.patience)
    if status != 201:
        time.sleep(12)
        status, _, _, _ = post_order(args.orders, args.patience)

    check("recovery: checkout works again without restarting orders",
          status == 201, f"got {status}")

    total = len(passed) + len(failed)
    print(f"\n  {GREEN}{len(passed)} passed{RESET}"
          + (f", {RED}{len(failed)} failed{RESET}" if failed else "")
          + f"  ({total} checks, {mode} mode)\n")
    for name in failed:
        print(f"    {RED}x{RESET} {name}")

    if not args.expect_fixed and not failed:
        print(f"  {DIM}Everything above passed, and the system is still broken.{RESET}")
        print(f"  {DIM}Now do exercise 3.1 and run this again with --expect-fixed.{RESET}\n")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
