# frozen_string_literal: true

# ORDERS — the orchestrator.
#
# REST at the edge, gRPC inside, two databases it cannot join across, and the only
# service in this system that can be woken up by somebody else's outage.
#
# Everything here satisfies contracts/orders.v1.yaml; if this file and that file
# disagree, this file is wrong.
#
# The HTTP layer is the only place in the process that knows what a status code is.
# Everything in lib/ is domain logic that would be identical in a CLI tool.

require 'json'
require 'sinatra'
require_relative 'lib/config'
require_relative 'lib/errors'
require_relative 'lib/orders_repository'
require_relative 'lib/orders_service'

PROBLEM_BASE = 'https://bootcamp.backendguru.io/problems/'

set :bind, '0.0.0.0'
set :port, Config::PORT
# Sinatra's friendly HTML error pages would bypass our envelope. Turn them off so the
# `error` handler below is the only way a failure leaves this process.
set :show_exceptions, false
set :raise_errors, false
set :environment, :production

OrdersRepository.wait_for_database!

# --- errors ------------------------------------------------------------------

# One error envelope, everywhere — RFC 9457, exactly as contracts/problem.yaml says.
#
# A client that learns this shape once handles every failure this API can produce, and a
# client written against orders already knows how to read an error from catalog. This
# handler is the single place in the process where a domain outcome becomes a status
# code: the translation happens once, at the edge, not in every module.
error DomainError do
  failure = env['sinatra.error']
  problem(failure.status, failure.kind, failure.title, failure.detail, failure.retry_after)
end

# Anything we did not name is a bug, and the caller must not be told to change its
# request. 500, and the detail stays in our logs — never in a response body, where it
# becomes a client's problem to parse and an attacker's to read.
error StandardError do
  warn "unhandled error on #{request.path}: #{env['sinatra.error']}"
  problem(500, 'internal-error', 'Internal server error',
          'The request could not be completed.')
end

# A path that matches no route. Sinatra's default is an HTML page, which is a second
# error shape for clients to learn. One envelope, everywhere, including the boring cases.
not_found do
  problem(404, 'order-not-found', 'Order not found',
          "No order with id '#{request.path}'.")
end

def problem(status_code, kind, title, detail, retry_after = nil)
  content_type 'application/problem+json'
  status status_code
  # Tells a well-behaved client when to come back, so it backs off instead of joining
  # the stampede that is currently keeping the dependency down.
  headers['Retry-After'] = retry_after.to_s if retry_after
  {
    type: PROBLEM_BASE + kind, title: title, status: status_code,
    detail: detail, instance: request.path
  }.to_json
end

before { content_type :json }

# --- endpoints ---------------------------------------------------------------

# Liveness only, and here that matters more than anywhere else in the system.
#
# Orders has dependencies, so the temptation to check them is real. Give in to it and a
# payments outage makes orders report unhealthy, and the platform starts restarting
# orders pods — removing capacity from a service that was working, during an incident,
# because we told it to.
#
# Orders is not sick when payments is down. It is degraded. That distinction belongs in
# metrics and alerts, not in the endpoint an orchestrator uses to decide whether to kill
# you.
get '/health' do
  { status: 'ok', implementation: Config::IMPLEMENTATION }.to_json
end

post '/v1/orders' do
  body = begin
    JSON.parse(request.body.read)
  rescue JSON::ParserError
    raise ValidationFailed, 'Body must be a JSON object with an `items` array.'
  end
  raise ValidationFailed, 'Body must be a JSON object with an `items` array.' unless body.is_a?(Hash)

  order = OrdersService.checkout(body['items'], request.env['HTTP_IDEMPOTENCY_KEY'])
  status 201
  headers['Location'] = "/v1/orders/#{order[:id]}"
  order.to_json
end

get '/v1/orders/:id' do
  OrdersService.get_order(params['id']).to_json
end

post '/v1/orders/:id/cancel' do
  OrdersService.cancel(params['id']).to_json
end
