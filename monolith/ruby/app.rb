# frozen_string_literal: true

# The HTTP layer. The only place in the process that knows what a status code is.
#
# Everything in lib/ is domain logic that would be identical in a CLI tool. That
# separation is not decoration: in Session 3, catalog and payments grow their own HTTP
# and gRPC edges, and the module code underneath them barely changes.

require 'json'
require 'sinatra'
require_relative 'lib/catalog'
require_relative 'lib/config'
require_relative 'lib/database'
require_relative 'lib/errors'
require_relative 'lib/orders'

PROBLEM_BASE = 'https://bootcamp.backendguru.io/problems/'

set :bind, '0.0.0.0'
set :port, Config::PORT
# Sinatra's friendly HTML error pages would bypass our envelope. Turn them off so the
# `error` handler below is the only way a failure leaves this process.
set :show_exceptions, false
set :raise_errors, false
set :environment, :production

Database.bootstrap!

# --- errors ------------------------------------------------------------------

# One error envelope, everywhere. RFC 9457 Problem Details.
#
# A client that learns this shape once handles every failure this API can produce.
# Bespoke error bodies per endpoint are how you make consumers write a parser per
# endpoint.
error DomainError do
  failure = env['sinatra.error']
  problem(failure.status, failure.kind, failure.title, failure.detail)
end

# Anything we did not name is a bug, and the caller must not be told to change its
# request. 500, and the detail stays in our logs.
error StandardError do
  warn "unhandled error on #{request.path}: #{env['sinatra.error']}"
  problem(500, 'internal-error', 'Internal server error',
          'The request could not be completed.')
end

def problem(status_code, kind, title, detail)
  content_type 'application/problem+json'
  status status_code
  {
    type: PROBLEM_BASE + kind, title: title, status: status_code,
    detail: detail, instance: request.path
  }.to_json
end

before { content_type :json }

# --- endpoints ---------------------------------------------------------------

# Liveness only — deliberately checks nothing downstream.
#
# Session 3 revisits this. A health check that calls its dependencies turns one
# service's outage into everyone's outage, because the platform starts killing healthy
# pods for being downstream of a sick one.
get '/health' do
  { status: 'ok', implementation: Config::IMPLEMENTATION }.to_json
end

get '/v1/products' do
  limit = 20
  if params['limit']
    limit = Integer(params['limit'], exception: false)
    raise ValidationFailed, 'limit must be an integer between 1 and 100.' if
      limit.nil? || limit < 1 || limit > 100
  end

  Catalog.list_products(limit, params['cursor']).to_json
end

get '/v1/products/:sku' do
  Catalog.get_product(params['sku']).to_json
end

post '/v1/orders' do
  body = begin
    JSON.parse(request.body.read)
  rescue JSON::ParserError
    raise ValidationFailed, 'Body must be a JSON object with an `items` array.'
  end

  order = Orders.checkout(body['items'])
  status 201
  headers 'Location' => "/v1/orders/#{order[:id]}"
  order.to_json
end

get '/v1/orders/:id' do
  Orders.get_order(params['id']).to_json
end

post '/v1/orders/:id/cancel' do
  Orders.cancel(params['id']).to_json
end
