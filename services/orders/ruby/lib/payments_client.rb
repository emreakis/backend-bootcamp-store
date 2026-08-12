# frozen_string_literal: true

# SOLUTION — exercises 3.1, 3.2 and 3.3.
#
# Compare with the same file on `main`:
#
#     git diff main solution -- services/orders/ruby
#
# Three things arrived, in the order they matter. A deadline, so a slow payments service
# cannot hold a checkout open forever. A bounded retry, legal only because `Charge`
# carries an idempotency key. And a breaker, so that once payments is clearly unwell we
# stop asking — which fails fast for us and takes load off it.
#
# The first of those is worth more than the other two together. Delete the retry and the
# breaker and this service still degrades honestly; delete the deadline and nothing else
# here can save it.

require 'grpc'
require_relative 'config'
require_relative 'errors'

$LOAD_PATH.unshift(File.expand_path('../gen', __dir__))
require 'bootcamp/payments/v1/payments_services_pb'

# Exercise 3.3 — closed, open, or half-open.
#
# Half-open is the state people forget, and leaving it out is worse than having no
# breaker at all: a breaker that never closes again is a permanent outage you built
# yourself. After `reset_ms` this lets exactly one request through; if it succeeds the
# breaker closes, and if it fails the clock restarts.
#
# The Mutex is not decoration. puma serves this app from a thread pool, so the counter
# really is shared mutable state — and MRI's GVL will hide most of the races most of the
# time, which is worse than not hiding them.
class CircuitBreaker
  def initialize(threshold, reset_ms)
    @threshold = threshold
    @reset_seconds = reset_ms / 1000.0
    @lock = Mutex.new
    @consecutive_failures = 0
    @opened_at = nil
  end

  def open?
    @lock.synchronize do
      return false if @opened_at.nil?                          # closed

      if Process.clock_gettime(Process::CLOCK_MONOTONIC) - @opened_at >= @reset_seconds
        warn 'circuit breaker HALF-OPEN: letting one probe through'
        @opened_at = nil                                       # half-open
        return false
      end
      true                                                     # open
    end
  end

  def record_success
    @lock.synchronize do
      warn 'circuit breaker CLOSED after a success' if @consecutive_failures.positive?
      @consecutive_failures = 0
      @opened_at = nil
    end
  end

  def record_failure
    @lock.synchronize do
      @consecutive_failures += 1
      if @consecutive_failures >= @threshold && @opened_at.nil?
        @opened_at = Process.clock_gettime(Process::CLOCK_MONOTONIC)
        warn "circuit breaker OPEN after #{@consecutive_failures} consecutive failures; " \
             "not calling payments for #{Config::BREAKER_RESET_MS} ms"
      end
    end
  end
end

module PaymentsClient
  V1 = Bootcamp::Payments::V1

  # Backoff between attempts. Never zero — an instant retry is just a second failure.
  BACKOFF_MS = [50, 200, 800].freeze

  STUB = V1::Payments::Stub.new(Config::PAYMENTS_ADDR, :this_channel_is_insecure)
  BREAKER = CircuitBreaker.new(Config::BREAKER_FAILURE_THRESHOLD, Config::BREAKER_RESET_MS)

  warn "payments client -> #{Config::PAYMENTS_ADDR} " \
       "(timeout #{Config::PAYMENTS_TIMEOUT_MS} ms, retries #{Config::PAYMENTS_RETRY_MAX}, " \
       "breaker #{Config::BREAKER_FAILURE_THRESHOLD}/#{Config::BREAKER_RESET_MS} ms)"

  module_function

  def charge(order_id, amount_cents, idempotency_key)
    request = V1::ChargeRequest.new(
      order_id: order_id,
      amount_cents: amount_cents,
      currency: 'EUR',
      idempotency_key: idempotency_key
    )

    # EXERCISE 3.3 — the breaker, checked before anything else.
    #
    # If payments has failed BREAKER_FAILURE_THRESHOLD times in a row we do not call it
    # at all. That is not pessimism, it is arithmetic: the next call will almost
    # certainly fail too, and it would cost us the full timeout per attempt to find out
    # while adding load to a service that is already struggling.
    if BREAKER.open?
      warn "order=#{order_id} charge SKIPPED: circuit breaker is open"
      raise PaymentsUnavailable,
            'The payment service is not answering, so we stopped calling it. ' \
            'No charge was made.'
    end

    last_error = nil

    # EXERCISE 3.2 — a BOUNDED retry.
    #
    # At most PAYMENTS_RETRY_MAX extra attempts, and only for the two codes that mean
    # "try again". Never for a decline, which is not a failure, and never for
    # INVALID_ARGUMENT, which is our bug and will be our bug again next time.
    #
    # Written as an explicit counted loop rather than Ruby's `retry` keyword, on purpose:
    # `retry` makes attempt one look identical to attempt fifty, which is convenient and
    # is also exactly how an unbounded retry gets written by accident.
    #
    # This is only legal because ChargeRequest carries an idempotency key and payments
    # returns the original response for a key it has seen. Take that away and this loop
    # bills the customer up to three times.
    (0..Config::PAYMENTS_RETRY_MAX).each do |attempt|
      begin
        # ============================================================
        # EXERCISE 3.1 — THE DEADLINE. The most important line in this file.
        #
        # Ruby wants an ABSOLUTE Time, like Node and unlike Python and Go — and
        # computing it INSIDE the loop is what makes the deadline per attempt.
        #
        # Per attempt, the worst case is retries + 1 attempts plus backoff: with the
        # defaults, 3 x 2000 ms + 250 ms ~ 6.25 s. Hoist this line above the loop and
        # all three attempts share a single 2 s budget instead — the promise stays at
        # 2 s, but a slow dependency eats the whole thing on attempt one and the retries
        # never happen. Which is the honest lesson underneath: retries fix TRANSIENT
        # failures, not slow ones.
        # ============================================================
        response = STUB.charge(
          request, deadline: Time.now + (Config::PAYMENTS_TIMEOUT_MS / 1000.0)
        )
      rescue GRPC::Unavailable, GRPC::DeadlineExceeded => e
        last_error = e
        BREAKER.record_failure
        warn "order=#{order_id} charge attempt #{attempt + 1}/" \
             "#{Config::PAYMENTS_RETRY_MAX + 1} failed: #{e.class}"

        if attempt < Config::PAYMENTS_RETRY_MAX
          sleep(BACKOFF_MS[[attempt, BACKOFF_MS.size - 1].min] / 1000.0)
        end
        next
      rescue GRPC::BadStatus => e
        # Not retryable, and not the breaker's business either: we sent something wrong
        # and sending it again will not help.
        raise "payments rejected the request: #{e.class}"
      end

      BREAKER.record_success

      # A DECLINE IS NOT A FAILURE. The call succeeded; the answer was "no". It does not
      # count against the breaker and it is never retried.
      if response.status == :CHARGE_STATUS_DECLINED
        warn "order=#{order_id} charge DECLINED: #{response.decline_reason}"
        reason = response.decline_reason
        raise PaymentDeclined, reason.empty? ? 'The card was declined.' : reason
      end

      warn "order=#{order_id} charge APPROVED auth=#{response.auth_code} " \
           "(attempt #{attempt + 1})"
      return { status: 'APPROVED', auth_code: response.auth_code }
    end

    # Out of attempts. NO CHARGE WAS MADE — or if one was, the idempotency key means a
    # later retry finds it rather than duplicating it. 503 with Retry-After, because the
    # customer did nothing wrong.
    raise PaymentsUnavailable,
          "The payment service did not respond (#{last_error.class}) after " \
          "#{Config::PAYMENTS_RETRY_MAX + 1} attempts of #{Config::PAYMENTS_TIMEOUT_MS} ms. " \
          'No charge was made.'
  end
end
