# frozen_string_literal: true

require 'grpc'
require_relative 'config'
require_relative 'errors'

# The generated code is put on the load path rather than required by relative path,
# because protoc emits `require 'bootcamp/payments/v1/payments_pb'` INSIDE the
# _services_pb file it also emits. Those requires are absolute — they assume the
# generated tree is a load-path root, exactly as a published gem would be — so
# require_relative into it works for the first file and fails on the one it pulls in.
$LOAD_PATH.unshift(File.expand_path('../gen', __dir__))
require 'bootcamp/payments/v1/payments_services_pb'

# THE FILE THE SESSION 3 EXERCISE LIVES IN.
#
# The gRPC half of this service's dependencies, and the one that will take the store
# down with it if you let it. Everything inside `charge` is the shape of a remote call
# that has not yet been made safe.
#
# Try it. All three of these break payments, and they do not break it the same way:
#
#     PAYMENT_LATENCY_MS=30000 docker compose up -d payments   # SLOW
#     docker compose pause payments                            # BLACK HOLE
#     docker compose stop payments                             # DOWN
#
# The first two hang, in every language, every time. A slow server accepts your
# connection and then never answers; a PAUSED one keeps its address and takes your SYN
# packets without acknowledging them, which is what a crashed host or a network
# partition looks like from the outside.
#
# The third is the one that surprises people, because it is not one behaviour. A
# stopped container loses its address and its DNS entry, and how long the failure
# takes is decided by whichever gRPC library you happen to be using. Measured on this
# stack, with no deadline anywhere: C# fails in about 4 seconds, Python, Go and Ruby
# in about 20 (their own connect timeout), and Java and TypeScript were still waiting
# after 25.
#
# Same outage, same contract, four seconds to never. THAT is the argument for the
# deadline: without one, how long checkout hangs is a property of somebody else's
# default rather than a number you chose — and 20 seconds is not "fast" for a
# checkout, it is a hang with extra steps.
#
# Meanwhile GET /health on this service keeps answering 200, because orders is not sick.
# Its dependency is. Watching a completely healthy service become unusable anyway is the
# moment Session 3 exists for, and it is the fallacy from Session 1 — *the network is
# reliable* — collecting its debt.
#
# There is no generated code in this repository. The Dockerfile runs
# grpc_tools_ruby_protoc over ../../../contracts/proto before this file is ever loaded,
# so the require above is the contract, compiled.
module PaymentsClient
  V1 = Bootcamp::Payments::V1

  # The stub is built once and reused for the life of the process.
  #
  # It is not a connection. It wraps a channel: a managed thing that resolves the name,
  # opens connections as needed, multiplexes concurrent calls over HTTP/2 and reconnects
  # on its own after a failure. Building one per request is both slow and a
  # misunderstanding of what it is.
  #
  # Unlike Net::HTTP above, this one IS safe to share across puma's threads — grpc's
  # channel is built for concurrent use. Two libraries in the same file with opposite
  # rules, which is why neither is worth guessing about.
  #
  # `payments` is not a hostname anybody configured — it is a service name the platform
  # resolves. Insecure credentials because this hop is inside the cluster; in production
  # a service that moves money gets mTLS.
  STUB = V1::Payments::Stub.new(Config::PAYMENTS_ADDR, :this_channel_is_insecure)

  warn "payments client -> #{Config::PAYMENTS_ADDR} " \
       "(timeout #{Config::PAYMENTS_TIMEOUT_MS} ms, retries #{Config::PAYMENTS_RETRY_MAX})"

  module_function

  # Charge the card.
  #
  # `idempotency_key` is what makes this call safe to repeat, and is therefore the
  # precondition for exercise 3.2. Retrying a charge without one bills the customer
  # twice.
  def charge(order_id, amount_cents, idempotency_key)
    request = V1::ChargeRequest.new(
      order_id: order_id,
      amount_cents: amount_cents,
      currency: 'EUR',
      idempotency_key: idempotency_key
    )

    begin
      # ================================================================
      # TODO (exercise 3.1) — GIVE THIS CALL A DEADLINE.       [do this first]
      #
      # `STUB.charge(request)` waits forever. Not "a long time" — forever. The default
      # value of a missing deadline is the worst value it could have, and it is the
      # single most important line missing from this file.
      #
      # Every generated method takes one, as a keyword argument. Ruby wants an ABSOLUTE
      # time, like Node and unlike Python and Go:
      #
      #     STUB.charge(request, deadline: Time.now + Config::PAYMENTS_TIMEOUT_MS / 1000.0)
      #
      # Note it is per CALL, not per stub. There is no way to set it once and forget it,
      # and that is deliberate across every gRPC library: a deadline is a property of the
      # request you are making right now, not of the connection you happen to be making
      # it over.
      #
      # The deadline also travels: payments sees the caller's remaining budget and
      # abandons its own work when the budget runs out, instead of finishing an answer
      # nobody is listening for. Watch the payments log say "ABANDONED: context canceled"
      # the moment this expires.
      #
      # Verify: PAYMENT_LATENCY_MS=30000, then POST an order. Before, it hangs; after,
      # you get a 503 in two seconds.
      # ================================================================

      # ================================================================
      # TODO (exercise 3.2) — RETRY, BUT ONLY BECAUSE YOU MAY.       [then this]
      #
      # Wrap the call in a bounded retry: at most Config::PAYMENTS_RETRY_MAX extra
      # attempts, with backoff between them (say 50 ms, then 200 ms), and ONLY for
      # GRPC::Unavailable and GRPC::DeadlineExceeded.
      #
      # Three rules, each of which someone learns the hard way:
      #
      #   1. Only retry what is safe to repeat. This call is, because ChargeRequest
      #      carries an idempotency key and payments returns the original response for a
      #      key it has seen. Delete that field and this exercise becomes a
      #      double-billing bug.
      #
      #   2. Never retry a business outcome. A declined card will be declined again;
      #      retrying it just costs the customer time.
      #
      #   3. Bound it, and back off. Retrying into an overloaded service is how a
      #      brownout becomes an outage — you add load to the exact system that is
      #      failing from load. Three attempts and a budget, not "retry until success".
      #
      # Ruby's `retry` keyword makes attempt 1 look identical to attempt 3, which is
      # convenient and is also exactly how an unbounded retry gets written by accident.
      # Count.
      # ================================================================

      # ================================================================
      # TODO (exercise 3.3) — PUT A CIRCUIT BREAKER IN FRONT.        [last]
      #
      # Count consecutive failures. At Config::BREAKER_FAILURE_THRESHOLD, stop calling
      # payments at all and fail immediately for Config::BREAKER_RESET_MS; then let one
      # probe through and close on success.
      #
      # A breaker does two jobs, and the second is the one people forget:
      #
      #   * it turns a slow hang into an instant, designed failure, so orders stops
      #     burning puma threads on a call it can predict will fail; and
      #   * it takes load OFF payments, giving it room to recover. Without one, a
      #     struggling service is held under by the traffic of everyone politely waiting
      #     for it.
      #
      # puma serves this app from a thread pool, so your counter is shared mutable state
      # across threads and wants a Mutex. MRI's GVL will hide most of the races most of
      # the time, which is worse than not hiding them. Writing the twenty lines yourself
      # once is worth doing first, because then you know what a gem like `circuitbox` is
      # doing.
      # ================================================================

      response = STUB.charge(request)
    rescue GRPC::Unavailable, GRPC::DeadlineExceeded => e
      # Transport-level trouble. The customer did nothing wrong, so this is a 5xx and
      # carries Retry-After. Crucially, NO CHARGE WAS MADE — or if one was, the
      # idempotency key means the retry will find it rather than duplicate it.
      warn "order=#{order_id} charge failed at the transport: #{e.class}"
      raise PaymentsUnavailable,
            "The payment service did not respond within #{Config::PAYMENTS_TIMEOUT_MS} ms. " \
            'No charge was made.'
    rescue GRPC::BadStatus => e
      # Anything else — INVALID_ARGUMENT, UNIMPLEMENTED — means we sent something wrong,
      # which is our bug and not a retry candidate.
      raise "payments rejected the request: #{e.class}"
    end

    # A DECLINE IS NOT A FAILURE. The call succeeded; the answer was "no".
    #
    # Payments deliberately returns OK with status DECLINED rather than a gRPC error
    # code, so that no retry policy in the system ever re-attempts a decision that will
    # never change. Here that becomes a 402 — the customer's problem to solve, and not
    # ours.
    if response.status == :CHARGE_STATUS_DECLINED
      warn "order=#{order_id} charge DECLINED: #{response.decline_reason}"
      reason = response.decline_reason
      raise PaymentDeclined, reason.empty? ? 'The card was declined.' : reason
    end

    warn "order=#{order_id} charge APPROVED auth=#{response.auth_code}"
    { status: 'APPROVED', auth_code: response.auth_code }
  end
end
