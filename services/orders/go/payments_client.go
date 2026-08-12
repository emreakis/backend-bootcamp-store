package main

import (
	"context"
	"fmt"
	"log"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"

	paymentsv1 "github.com/backendguru/store/gen/paymentsv1"
)

// SOLUTION — exercises 3.1, 3.2 and 3.3.
//
// Compare with the same file on main:
//
//	git diff main solution -- services/orders/go
//
// Three things arrived, in the order they matter. A deadline, so a slow payments service
// cannot hold a checkout open forever. A bounded retry, legal only because Charge carries
// an idempotency key. And a breaker, so that once payments is clearly unwell we stop
// asking — which fails fast for us and takes load off it.
//
// The first of those is worth more than the other two together. Delete the retry and the
// breaker and this service still degrades honestly; delete the deadline and nothing else
// here can save it.
type paymentsClient struct {
	conn    *grpc.ClientConn
	stub    paymentsv1.PaymentsClient
	cfg     config
	breaker *circuitBreaker
}

// backoff between attempts. Never zero — an instant retry is just a second failure.
var backoff = []time.Duration{50 * time.Millisecond, 200 * time.Millisecond, 800 * time.Millisecond}

func newPaymentsClient(cfg config) (*paymentsClient, error) {
	conn, err := grpc.NewClient(cfg.paymentsAddr,
		grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, err
	}

	log.Printf("payments client -> %s (timeout %s, retries %d, breaker %d/%s)",
		cfg.paymentsAddr, cfg.paymentsTimeout, cfg.paymentsRetryMax,
		cfg.breakerThreshold, cfg.breakerReset)

	return &paymentsClient{
		conn:    conn,
		stub:    paymentsv1.NewPaymentsClient(conn),
		cfg:     cfg,
		breaker: &circuitBreaker{threshold: cfg.breakerThreshold, reset: cfg.breakerReset},
	}, nil
}

func (p *paymentsClient) charge(orderID string, amountCents int64, idempotencyKey string) (*payment, error) {
	request := &paymentsv1.ChargeRequest{
		OrderId:        orderID,
		AmountCents:    amountCents,
		Currency:       "EUR",
		IdempotencyKey: idempotencyKey,
	}

	// EXERCISE 3.3 — the breaker, checked before anything else.
	//
	// If payments has failed breakerThreshold times in a row we do not call it at all.
	// That is not pessimism, it is arithmetic: the next call will almost certainly fail
	// too, and it would cost us the full timeout per attempt to find out while adding
	// load to a service that is already struggling.
	if p.breaker.isOpen() {
		log.Printf("order=%s charge SKIPPED: circuit breaker is open", orderID)
		return nil, paymentsUnavailable(
			"The payment service is not answering, so we stopped calling it. " +
				"No charge was made.")
	}

	var lastCode codes.Code

	// EXERCISE 3.2 — a BOUNDED retry.
	//
	// At most paymentsRetryMax extra attempts, and only for the two codes that mean "try
	// again": Unavailable (nobody answered) and DeadlineExceeded (somebody answered too
	// slowly). Never for a decline, which is not a failure, and never for
	// InvalidArgument, which is our bug and will be our bug again next time.
	//
	// This is only legal because ChargeRequest carries an idempotency key and payments
	// returns the original response for a key it has seen. Take that away and this loop
	// bills the customer up to three times.
	for attempt := 0; attempt <= p.cfg.paymentsRetryMax; attempt++ {
		// ================================================================
		// EXERCISE 3.1 — THE DEADLINE. The most important lines in this file.
		//
		// In Go the deadline is the context, which is the clearest expression of the
		// idea in any of the six languages: it is the first argument to every generated
		// method, and it is impossible to make the call without passing something.
		//
		// `defer cancel()` inside the loop would not run until the function returns, so
		// on three attempts you would hold three timers. Hence cancel() at the end of
		// each iteration instead — the sort of thing `go vet` catches and a production
		// heap profile catches more expensively.
		//
		// The deadline is PER ATTEMPT, which means the worst case is retries + 1
		// attempts plus backoff: with the defaults, 3 x 2s + 250ms ~ 6.25s. State that
		// number out loud, because whoever calls checkout has their own budget.
		//
		// The other defensible design is one context created outside the loop and shared
		// by every attempt. That keeps the promise at 2s but means a slow dependency eats
		// the whole budget on attempt one and the retries never happen — which is the
		// honest lesson underneath: retries fix TRANSIENT failures, not slow ones.
		// ================================================================
		ctx, cancel := context.WithTimeout(context.Background(), p.cfg.paymentsTimeout)
		response, err := p.stub.Charge(ctx, request)
		cancel()

		if err == nil {
			p.breaker.recordSuccess()

			// A DECLINE IS NOT A FAILURE. The call succeeded; the answer was "no". It
			// does not count against the breaker and it is never retried.
			if response.GetStatus() == paymentsv1.ChargeStatus_CHARGE_STATUS_DECLINED {
				log.Printf("order=%s charge DECLINED: %s", orderID, response.GetDeclineReason())
				reason := response.GetDeclineReason()
				if reason == "" {
					reason = "The card was declined."
				}
				return nil, paymentDeclined(reason)
			}

			log.Printf("order=%s charge APPROVED auth=%s (attempt %d)",
				orderID, response.GetAuthCode(), attempt+1)
			return &payment{Status: "APPROVED", AuthCode: response.GetAuthCode()}, nil
		}

		code := status.Code(err)
		if code != codes.Unavailable && code != codes.DeadlineExceeded {
			// Not retryable, and not the breaker's business either: we sent something
			// wrong and sending it again will not help.
			return nil, fmt.Errorf("payments rejected the request: %s", code)
		}

		lastCode = code
		p.breaker.recordFailure()
		log.Printf("order=%s charge attempt %d/%d failed: %s",
			orderID, attempt+1, p.cfg.paymentsRetryMax+1, code)

		if attempt < p.cfg.paymentsRetryMax {
			time.Sleep(backoff[min(attempt, len(backoff)-1)])
		}
	}

	// Out of attempts. NO CHARGE WAS MADE — or if one was, the idempotency key means a
	// later retry finds it rather than duplicating it. 503 with Retry-After, because the
	// customer did nothing wrong.
	return nil, paymentsUnavailable(fmt.Sprintf(
		"The payment service did not respond (%s) after %d attempts of %d ms. "+
			"No charge was made.",
		lastCode, p.cfg.paymentsRetryMax+1, p.cfg.paymentsTimeout.Milliseconds()))
}

func (p *paymentsClient) close() { _ = p.conn.Close() }

// --- the breaker -------------------------------------------------------------

// circuitBreaker is closed, open, or half-open.
//
// Half-open is the state people forget, and leaving it out is worse than having no
// breaker at all: a breaker that never closes again is a permanent outage you built
// yourself. After `reset` this lets exactly one request through; if it succeeds the
// breaker closes, and if it fails the clock restarts.
//
// The mutex is not decoration. Every HTTP handler runs in its own goroutine, so this
// counter really is shared mutable state — and an unsynchronised one is a bug that only
// shows up under load, which is the only time this code matters. (`go test -race` on the
// checkout path is the cheapest way to prove that to yourself.)
type circuitBreaker struct {
	threshold int
	reset     time.Duration

	mu                  sync.Mutex
	consecutiveFailures int
	openedAt            time.Time
}

func (b *circuitBreaker) isOpen() bool {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.openedAt.IsZero() {
		return false // closed
	}
	if time.Since(b.openedAt) >= b.reset {
		log.Print("circuit breaker HALF-OPEN: letting one probe through")
		b.openedAt = time.Time{} // half-open
		return false
	}
	return true // open
}

func (b *circuitBreaker) recordSuccess() {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.consecutiveFailures > 0 {
		log.Print("circuit breaker CLOSED after a success")
	}
	b.consecutiveFailures = 0
	b.openedAt = time.Time{}
}

func (b *circuitBreaker) recordFailure() {
	b.mu.Lock()
	defer b.mu.Unlock()

	b.consecutiveFailures++
	if b.consecutiveFailures >= b.threshold && b.openedAt.IsZero() {
		b.openedAt = time.Now()
		log.Printf("circuit breaker OPEN after %d consecutive failures; "+
			"not calling payments for %s", b.consecutiveFailures, b.reset)
	}
}
