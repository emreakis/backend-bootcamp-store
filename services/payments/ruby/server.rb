# frozen_string_literal: true

# PAYMENTS — a gRPC service, and the only one in the system with no HTTP surface and no
# database.
#
# Nothing outside the store ever calls it, which is why it does not need REST: there is
# no browser to please, no cache to negotiate with, and no human reading its responses.
# What it does need is a contract that cannot drift and a wire format that is cheap on a
# hot path, and that is the case for gRPC in one sentence.
#
# Read this next to services/catalog/ruby/app.rb — the same amount of work, an entirely
# different shape, and the difference is who the caller is.

require 'grpc'
require 'grpc/health/checker'
require 'grpc/health/v1/health_services_pb'
require 'securerandom'

# The generated code is put on the load path rather than required by relative path,
# because protoc emits `require 'bootcamp/payments/v1/payments_pb'` INSIDE the
# _services_pb file it also emits. Those requires are absolute — they assume the
# generated tree is a load-path root, exactly as a published gem would be.
$LOAD_PATH.unshift(File.expand_path('gen', __dir__))
require 'bootcamp/payments/v1/payments_services_pb'

IMPLEMENTATION = 'ruby'

PORT = ENV.fetch('PORT', '50051')
DECLINE_OVER_CENTS = Integer(ENV.fetch('PAYMENT_DECLINE_OVER_CENTS', '500000'))
ALWAYS_DECLINE = ENV.fetch('PAYMENT_ALWAYS_DECLINE', 'false') == 'true'
# The exercise dial. Set it above the caller's deadline and payments stops being down and
# starts being SLOW — which is the failure that actually hurts, because a slow service
# accepts your connection and then holds it.
LATENCY_MS = Integer(ENV.fetch('PAYMENT_LATENCY_MS', '0'))

V1 = Bootcamp::Payments::V1

# Inherits from the generated service class.
#
# That is not boilerplate — it is forward compatibility. Add a method to the .proto
# tomorrow and this still runs, serving UNIMPLEMENTED for the new one instead of failing
# to start.
class PaymentsService < V1::Payments::Service
  def initialize
    super
    # Idempotency, in memory.
    #
    # A restart forgets every key, and that is a real limitation left visible rather than
    # hidden. In production this is a datastore with a TTL, and "where do idempotency
    # records live, and for how long" is a design question with real answers. Here it is
    # a hash, so you can see the shape of the idea.
    #
    # The Mutex is not decoration: the gRPC server runs a thread pool, so two concurrent
    # retries of the same key really can arrive at once.
    @lock = Mutex.new
    @charges = {}
  end

  # Unary: one request, one reply.
  def charge(request, call)
    # Idempotency first, before any work. A repeat of a key we have seen returns the
    # ORIGINAL answer and charges nothing — which is the entire reason the caller is
    # allowed to retry this method automatically.
    unless request.idempotency_key.empty?
      previous = @lock.synchronize { @charges[request.idempotency_key] }
      if previous
        warn "charge order=#{request.order_id} " \
             "idempotency_key=#{request.idempotency_key} REPLAYED"
        return previous
      end
    end

    # Injected latency, applied while still watching the caller's deadline. If the caller
    # gave up, so do we — continuing to work for a client that has stopped listening is
    # how an overloaded system stays overloaded.
    #
    # Ruby's gRPC surfaces the deadline as `call.deadline`, an absolute Time, and gives
    # you no cancellation callback — so this is the one implementation of the six that
    # has to reason about the deadline arithmetically rather than waiting on a signal.
    # Same idea, less help from the library.
    if LATENCY_MS.positive?
      latency = LATENCY_MS / 1000.0

      # A CLIENT THAT SET NO DEADLINE REPORTS ONE FROM 1969.
      #
      # gRPC's C core represents "no deadline" as gpr_inf_future, and Ruby's conversion
      # of that to a Time overflows — it comes back as 1969-12-31 23:59:59, one second
      # before the epoch. So the absence of a deadline arrives looking exactly like a
      # deadline that expired fifty-six years ago.
      #
      # Take that at face value and this server abandons every call from a client that
      # has not done exercise 3.1 — which is every call, at the start of the session. It
      # would answer instantly and it would answer CANCELLED, so the exercise would
      # appear to be already solved while actually being broken in a new way. The
      # conformance suite caught precisely that.
      #
      # Hence: a deadline already in the past when the call STARTS was never really set.
      deadline = call.deadline
      deadline = nil if deadline.nil? || deadline <= Time.now

      if deadline && deadline - Time.now <= latency
        sleep([deadline - Time.now, 0].max)
        warn "charge order=#{request.order_id} ABANDONED: deadline exceeded"
        raise GRPC::Cancelled, 'the caller gave up'
      end
      sleep latency
    end

    if request.amount_cents <= 0
      # A malformed request IS an RPC error, and INVALID_ARGUMENT is the gRPC equivalent
      # of a 400. Contrast with the decline below.
      raise GRPC::InvalidArgument, "amount_cents must be positive, got #{request.amount_cents}"
    end

    declined = ALWAYS_DECLINE || request.amount_cents > DECLINE_OVER_CENTS

    # THE DESIGN DECISION IN THIS FILE.
    #
    # A declined card is not an RPC failure. The call succeeded: we asked the provider,
    # the provider said no, and that answer arrived intact. So this returns OK with status
    # DECLINED, and NOT `raise GRPC::PermissionDenied`.
    #
    # The distinction matters more than it looks. gRPC error codes are how the *transport*
    # reports trouble, and clients quite reasonably retry some of them. Encode a business
    # outcome as one and every retry policy in the system starts re-attempting a decision
    # that will never change — while a genuinely retryable UNAVAILABLE becomes
    # indistinguishable from "this card is stolen".
    #
    # Business outcomes go in the response. Failures go in the status.
    response = if declined
                 V1::ChargeResponse.new(
                   payment_id: SecureRandom.uuid,
                   status: :CHARGE_STATUS_DECLINED,
                   decline_reason: "amount exceeds the approval limit of #{DECLINE_OVER_CENTS} cents"
                 )
               else
                 V1::ChargeResponse.new(
                   payment_id: SecureRandom.uuid,
                   status: :CHARGE_STATUS_APPROVED,
                   auth_code: "AUTH-#{SecureRandom.hex(4).upcase}"
                 )
               end

    unless request.idempotency_key.empty?
      @lock.synchronize { @charges[request.idempotency_key] = response }
    end

    warn "charge order=#{request.order_id} amount=#{request.amount_cents} " \
         "status=#{response.status}"
    response
  end

  # Server streaming, declared in the contract and deliberately not built — see the note
  # in contracts/proto/bootcamp/payments/v1/payments.proto.
  #
  # UNIMPLEMENTED is a defined, catchable answer meaning "this exists in the contract and
  # not yet in this deployment". That is a far better thing for a consuming team to
  # receive than a method that hangs or returns an empty stream, and it is what lets a
  # contract legitimately run ahead of its implementations.
  def watch_status(_request, _call)
    raise GRPC::Unimplemented,
          'WatchStatus is declared in payments.v1 but not implemented in this deployment'
  end
end

# Ten threads, and that number is a capacity decision rather than a default. Every
# in-flight Charge holds one, so with PAYMENT_LATENCY_MS set high this server runs out of
# workers long before it runs out of anything else — a bounded pool being exactly the
# sort of resource a caller without a deadline exhausts on your behalf.
server = GRPC::RpcServer.new(pool_size: 10)
server.add_http2_port("0.0.0.0:#{PORT}", :this_port_is_insecure)
server.handle(PaymentsService.new)

# The standard gRPC health service. gRPC has its own health-checking protocol rather than
# borrowing HTTP's, so orchestrators probe it the same way in every language. Liveness
# only, same rule as the REST services: it reports on this process, never on its
# dependencies.
health_checker = Grpc::Health::Checker.new
health_checker.add_status('', Grpc::Health::V1::HealthCheckResponse::ServingStatus::SERVING)
server.handle(health_checker)

warn "payments (#{IMPLEMENTATION}) listening on :#{PORT}  " \
     "decline_over=#{DECLINE_OVER_CENTS} latency=#{LATENCY_MS}ms"
server.run_till_terminated_or_interrupted(['SIGTERM', 'SIGINT'])
