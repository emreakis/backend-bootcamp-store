// PAYMENTS — a gRPC service, and the only one in the system with no HTTP surface and
// no database.
//
// Nothing outside the store ever calls it, which is why it does not need REST: there
// is no browser to please, no cache to negotiate with, and no human reading its
// responses. What it does need is a contract that cannot drift and a wire format that
// is cheap on a hot path, and that is the case for gRPC in one sentence.
//
// Read this next to services/catalog — the same amount of work, an entirely different
// shape, and the difference is who the caller is.
package main

import (
	"context"
	"log"
	"net"
	"os"
	"strconv"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/reflection"
	"google.golang.org/grpc/status"

	paymentsv1 "github.com/backendguru/store/gen/paymentsv1"
)

const implementation = "go"

type config struct {
	port              string
	declineOverCents  int64
	alwaysDecline     bool
	latency           time.Duration
}

func load() config {
	return config{
		port:             env("PORT", "50051"),
		declineOverCents: envInt("PAYMENT_DECLINE_OVER_CENTS", 500_000),
		alwaysDecline:    env("PAYMENT_ALWAYS_DECLINE", "false") == "true",
		// The exercise dial. Set it above the caller's deadline and payments stops
		// being down and starts being SLOW — which is the failure that actually hurts,
		// because a slow service accepts your connection and then holds it.
		latency: time.Duration(envInt("PAYMENT_LATENCY_MS", 0)) * time.Millisecond,
	}
}

// server implements the generated PaymentsServer interface.
//
// Embedding UnimplementedPaymentsServer is not boilerplate — it is forward
// compatibility. Add a method to the .proto tomorrow and this still compiles, serving
// UNIMPLEMENTED for the new one instead of failing to build.
type server struct {
	paymentsv1.UnimplementedPaymentsServer

	cfg config

	// Idempotency, in memory.
	//
	// A restart forgets every key, and that is a real limitation left visible rather
	// than hidden. In production this is a datastore with a TTL, and "where do
	// idempotency records live, and for how long" is a design question with real
	// answers. Here it is a map, so you can see the shape of the idea.
	mu      sync.Mutex
	charges map[string]*paymentsv1.ChargeResponse
}

// Charge is unary: one request, one reply.
func (s *server) Charge(ctx context.Context, req *paymentsv1.ChargeRequest) (*paymentsv1.ChargeResponse, error) {
	// Idempotency first, before any work. A repeat of a key we have seen returns the
	// ORIGINAL answer and charges nothing — which is the entire reason the caller is
	// allowed to retry this method automatically.
	if key := req.GetIdempotencyKey(); key != "" {
		s.mu.Lock()
		previous, seen := s.charges[key]
		s.mu.Unlock()
		if seen {
			log.Printf("charge order=%s idempotency_key=%s REPLAYED", req.GetOrderId(), key)
			return previous, nil
		}
	}

	// Injected latency, applied while still watching the caller's deadline. If the
	// caller gave up, so do we — continuing to work for a client that has stopped
	// listening is how an overloaded system stays overloaded.
	if s.cfg.latency > 0 {
		select {
		case <-time.After(s.cfg.latency):
		case <-ctx.Done():
			log.Printf("charge order=%s ABANDONED: %v", req.GetOrderId(), ctx.Err())
			return nil, status.FromContextError(ctx.Err()).Err()
		}
	}

	if req.GetAmountCents() <= 0 {
		// A malformed request IS an RPC error, and InvalidArgument is the gRPC
		// equivalent of a 400. Contrast with the decline below.
		return nil, status.Errorf(codes.InvalidArgument, "amount_cents must be positive, got %d", req.GetAmountCents())
	}

	declined := s.cfg.alwaysDecline || req.GetAmountCents() > s.cfg.declineOverCents

	// THE DESIGN DECISION IN THIS FILE.
	//
	// A declined card is not an RPC failure. The call succeeded: we asked the
	// provider, the provider said no, and that answer arrived intact. So this returns
	// OK with status DECLINED, and NOT status.Error(codes.PermissionDenied, …).
	//
	// The distinction matters more than it looks. gRPC error codes are how the
	// *transport* reports trouble, and clients quite reasonably retry some of them.
	// Encode a business outcome as one and every retry policy in the system starts
	// re-attempting a decision that will never change — while a genuinely retryable
	// UNAVAILABLE becomes indistinguishable from "this card is stolen".
	//
	// Business outcomes go in the response. Failures go in the status.
	response := &paymentsv1.ChargeResponse{
		PaymentId: newID(),
		Status:    paymentsv1.ChargeStatus_CHARGE_STATUS_APPROVED,
	}
	if declined {
		response.Status = paymentsv1.ChargeStatus_CHARGE_STATUS_DECLINED
		response.DeclineReason = "amount exceeds the approval limit of " +
			strconv.FormatInt(s.cfg.declineOverCents, 10) + " cents"
	} else {
		response.AuthCode = "AUTH-" + newToken()
	}

	if key := req.GetIdempotencyKey(); key != "" {
		s.mu.Lock()
		s.charges[key] = response
		s.mu.Unlock()
	}

	log.Printf("charge order=%s amount=%d status=%s", req.GetOrderId(),
		req.GetAmountCents(), response.GetStatus())
	return response, nil
}

// WatchStatus is server streaming, declared in the contract and deliberately not
// built — see the note in contracts/payments.v1.proto.
//
// UNIMPLEMENTED is a defined, catchable answer meaning "this exists in the contract
// and not yet in this deployment". That is a far better thing for a consuming team to
// receive than a method that hangs or returns an empty stream, and it is what lets a
// contract legitimately run ahead of its implementations.
func (s *server) WatchStatus(*paymentsv1.WatchStatusRequest, grpc.ServerStreamingServer[paymentsv1.PaymentStatus]) error {
	return status.Error(codes.Unimplemented,
		"WatchStatus is declared in payments.v1 but not implemented in this deployment")
}

func main() {
	cfg := load()

	listener, err := net.Listen("tcp", ":"+cfg.port)
	if err != nil {
		log.Fatalf("listening on :%s: %v", cfg.port, err)
	}

	grpcServer := grpc.NewServer()
	paymentsv1.RegisterPaymentsServer(grpcServer, &server{
		cfg:     cfg,
		charges: make(map[string]*paymentsv1.ChargeResponse),
	})

	// The standard gRPC health service. gRPC has its own health-checking protocol
	// rather than borrowing HTTP's, so orchestrators probe it the same way in every
	// language. Liveness only, same rule as the REST services: it reports on this
	// process, never on its dependencies.
	healthServer := health.NewServer()
	healthServer.SetServingStatus("", healthpb.HealthCheckResponse_SERVING)
	healthpb.RegisterHealthServer(grpcServer, healthServer)

	// Reflection lets grpcurl explore this server with no .proto file in hand:
	//     grpcurl -plaintext localhost:50051 list
	// Convenient in a classroom, and worth disabling in production.
	reflection.Register(grpcServer)

	log.Printf("payments (%s) listening on :%s  decline_over=%d latency=%s",
		implementation, cfg.port, cfg.declineOverCents, cfg.latency)
	if err := grpcServer.Serve(listener); err != nil {
		log.Fatal(err)
	}
}

// --- small helpers -----------------------------------------------------------

func env(key, fallback string) string {
	if value, ok := os.LookupEnv(key); ok && value != "" {
		return value
	}
	return fallback
}

func envInt(key string, fallback int64) int64 {
	if value, ok := os.LookupEnv(key); ok {
		if parsed, err := strconv.ParseInt(value, 10, 64); err == nil {
			return parsed
		}
	}
	return fallback
}
