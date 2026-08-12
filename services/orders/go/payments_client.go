package main

import (
	"context"
	"fmt"
	"log"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"

	paymentsv1 "github.com/backendguru/store/gen/paymentsv1"
)

// paymentsClient is THE FILE THE SESSION 3 EXERCISE LIVES IN.
//
// The gRPC half of this service's dependencies, and the one that will take the store
// down with it if you let it. Everything inside charge() is the shape of a remote call
// that has not yet been made safe.
//
// Try it. All three of these break payments, and they do not break it the same way:
//
//	PAYMENT_LATENCY_MS=30000 docker compose up -d payments   # SLOW
//	docker compose pause payments                            # BLACK HOLE
//	docker compose stop payments                             # DOWN
//
// The first two hang, in every language, every time. A slow server accepts your
// connection and then never answers; a PAUSED one keeps its address and takes your SYN
// packets without acknowledging them, which is what a crashed host or a network
// partition looks like from the outside.
//
// The third is the one that surprises people, because it is not one behaviour. A
// stopped container loses its address and its DNS entry, and how long the failure
// takes is decided by whichever gRPC library you happen to be using. Measured on this
// stack, with no deadline anywhere: C# fails in about 4 seconds, Python, Go and Ruby
// in about 20 (their own connect timeout), and Java and TypeScript were still waiting
// after 25.
//
// Same outage, same contract, four seconds to never. THAT is the argument for the
// deadline: without one, how long checkout hangs is a property of somebody else's
// default rather than a number you chose — and 20 seconds is not "fast" for a
// checkout, it is a hang with extra steps.
//
// Meanwhile GET /health on this service keeps answering 200, because orders is not
// sick. Its dependency is. Watching a completely healthy service become unusable
// anyway is the moment Session 3 exists for, and it is the fallacy from Session 1 —
// *the network is reliable* — collecting its debt.
type paymentsClient struct {
	conn *grpc.ClientConn
	stub paymentsv1.PaymentsClient
	cfg  config
}

func newPaymentsClient(cfg config) (*paymentsClient, error) {
	// The channel is built once and reused for the life of the process.
	//
	// It is not a connection. It is a managed thing that resolves the name, opens
	// connections as needed, multiplexes concurrent calls over HTTP/2 and reconnects
	// on its own after a failure. Building one per request is both slow and a
	// misunderstanding of what it is.
	//
	// grpc.NewClient does NOT dial here — it is lazy, and the first RPC is what
	// actually connects. That is worth knowing during this exercise: a client that
	// constructs successfully tells you nothing at all about whether payments exists.
	//
	// `payments` is not a hostname anybody configured — it is a service name the
	// platform resolves. Insecure credentials because this hop is inside the cluster;
	// in production a service that moves money gets mTLS.
	conn, err := grpc.NewClient(cfg.paymentsAddr,
		grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, err
	}

	log.Printf("payments client -> %s (timeout %s, retries %d)",
		cfg.paymentsAddr, cfg.paymentsTimeout, cfg.paymentsRetryMax)
	return &paymentsClient{conn: conn, stub: paymentsv1.NewPaymentsClient(conn), cfg: cfg}, nil
}

// charge the card.
//
// idempotencyKey is what makes this call safe to repeat, and is therefore the
// precondition for exercise 3.2. Retrying a charge without one bills the customer
// twice.
func (p *paymentsClient) charge(orderID string, amountCents int64, idempotencyKey string) (*payment, error) {
	request := &paymentsv1.ChargeRequest{
		OrderId:        orderID,
		AmountCents:    amountCents,
		Currency:       "EUR",
		IdempotencyKey: idempotencyKey,
	}

	// ================================================================
	// TODO (exercise 3.1) — GIVE THIS CALL A DEADLINE.       [do this first]
	//
	// context.Background() has no deadline, so this call waits forever. Not "a long
	// time" — forever. The default value of a missing deadline is the worst value it
	// could have, and it is the single most important line missing from this file.
	//
	// In Go the deadline is not a stub option, it is the context — which is the
	// clearest expression of the idea in any of the six languages:
	//
	//     ctx, cancel := context.WithTimeout(context.Background(), p.cfg.paymentsTimeout)
	//     defer cancel()
	//
	// Always `defer cancel()`, even on the success path. Skip it and the timer and
	// its goroutine leak until the deadline fires, which `go vet` will tell you about
	// and a production heap profile will tell you about more expensively.
	//
	// The deadline also travels: gRPC puts the remaining budget on the wire, payments
	// sees it as its own ctx.Done(), and it abandons work nobody is listening for
	// instead of finishing an answer into a closed connection. Watch the payments log
	// say "ABANDONED: context canceled" the moment this expires.
	//
	// Verify: PAYMENT_LATENCY_MS=30000, then POST an order. Before, it hangs; after,
	// you get a 503 in two seconds.
	// ================================================================
	ctx := context.Background()

	// ================================================================
	// TODO (exercise 3.2) — RETRY, BUT ONLY BECAUSE YOU MAY.       [then this]
	//
	// Wrap the call in a bounded retry: at most p.cfg.paymentsRetryMax extra attempts,
	// with backoff between them (say 50 ms, then 200 ms), and ONLY for
	// codes.Unavailable and codes.DeadlineExceeded.
	//
	// Three rules, each of which someone learns the hard way:
	//
	//  1. Only retry what is safe to repeat. This call is, because ChargeRequest
	//     carries an idempotency key and payments returns the original response for a
	//     key it has seen. Delete that field and this exercise becomes a
	//     double-billing bug.
	//
	//  2. Never retry a business outcome. A declined card will be declined again;
	//     retrying it just costs the customer time.
	//
	//  3. Bound it, and back off. Retrying into an overloaded service is how a
	//     brownout becomes an outage — you add load to the exact system that is
	//     failing from load. Three attempts and a budget, not "retry until success".
	//
	// Note the interaction with 3.1: if the deadline is on the OUTER context, three
	// attempts share one 2 s budget and the whole operation still answers in 2 s. Put
	// it on each attempt instead and the worst case becomes 6 s. Both are defensible;
	// only one of them is what you meant. Decide on purpose.
	//
	// (grpc-go also ships a declarative retry policy via a service config, which is
	// worth knowing about and worth writing by hand once first.)
	// ================================================================

	// ================================================================
	// TODO (exercise 3.3) — PUT A CIRCUIT BREAKER IN FRONT.        [last]
	//
	// Count consecutive failures. At p.cfg.breakerThreshold, stop calling payments at
	// all and fail immediately for p.cfg.breakerReset; then let one probe through and
	// close on success.
	//
	// A breaker does two jobs, and the second is the one people forget:
	//
	//   - it turns a slow hang into an instant, designed failure, so orders stops
	//     burning goroutines on a call it can predict will fail; and
	//   - it takes load OFF payments, giving it room to recover. Without one, a
	//     struggling service is held under by the traffic of everyone politely
	//     waiting for it.
	//
	// Every HTTP handler runs in its own goroutine, so your counter is shared mutable
	// state under concurrency. A sync.Mutex around the whole thing is fine and honest;
	// sony/gobreaker does it properly. Writing the twenty lines yourself once is worth
	// doing first, because then you know what it is doing.
	// ================================================================

	response, err := p.stub.Charge(ctx, request)
	if err != nil {
		code := status.Code(err)
		log.Printf("order=%s charge failed at the transport: %s", orderID, code)

		// Transport-level trouble. The customer did nothing wrong, so this is a 5xx
		// and carries Retry-After. Crucially, NO CHARGE WAS MADE — or if one was, the
		// idempotency key means the retry will find it rather than duplicate it.
		if code == codes.Unavailable || code == codes.DeadlineExceeded {
			return nil, paymentsUnavailable(fmt.Sprintf(
				"The payment service did not respond within %d ms. No charge was made.",
				p.cfg.paymentsTimeout.Milliseconds()))
		}

		// Anything else — InvalidArgument, Unimplemented — means we sent something
		// wrong, which is our bug and not a retry candidate.
		return nil, fmt.Errorf("payments rejected the request: %s", code)
	}

	// A DECLINE IS NOT A FAILURE. The call succeeded; the answer was "no".
	//
	// Payments deliberately returns OK with status DECLINED rather than a gRPC error
	// code, so that no retry policy in the system ever re-attempts a decision that
	// will never change. Here that becomes a 402 — the customer's problem to solve,
	// and not ours.
	if response.GetStatus() == paymentsv1.ChargeStatus_CHARGE_STATUS_DECLINED {
		log.Printf("order=%s charge DECLINED: %s", orderID, response.GetDeclineReason())
		reason := response.GetDeclineReason()
		if reason == "" {
			reason = "The card was declined."
		}
		return nil, paymentDeclined(reason)
	}

	log.Printf("order=%s charge APPROVED auth=%s", orderID, response.GetAuthCode())
	return &payment{Status: "APPROVED", AuthCode: response.GetAuthCode()}, nil
}

func (p *paymentsClient) close() { _ = p.conn.Close() }
