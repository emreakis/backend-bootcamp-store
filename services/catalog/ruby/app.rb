# frozen_string_literal: true

# CATALOG — the read side of the store, and the simplest service in the system.
#
# Small enough to read in one file, which is why it is the one to read first. Everything
# here satisfies contracts/catalog.v1.yaml; if this file and that file disagree, this
# file is wrong.
#
# Compare it with `monolith/ruby/lib/catalog.rb`. The SQL is identical. What changed is
# everything around it: its own database, its own process, its own deployment, and a
# `reserve` method that no longer exists because stock cannot be taken off a shelf in one
# database inside a transaction that lives in another.

require 'json'
require 'pg'
require 'sinatra'

IMPLEMENTATION = 'ruby'
PROBLEM_BASE = 'https://bootcamp.backendguru.io/problems/'

PORT = Integer(ENV.fetch('PORT', '8000'))
DATABASE_URL = ENV.fetch('DATABASE_URL', 'postgres://store:store@localhost:5433/catalog')

set :bind, '0.0.0.0'
set :port, PORT
# Sinatra's friendly HTML error pages would bypass our envelope. Turn them off so the
# `error` handler below is the only way a failure leaves this process.
set :show_exceptions, false
set :raise_errors, false
set :environment, :production

# A connection per thread.
#
# puma serves this app from a thread pool and a PG::Connection is not safe to share
# across threads, so each one gets its own. Crude compared with the managed pools the
# other five implementations use — and visible, which is the point: something has to
# own the question "how many connections does this process hold open".
def db
  Thread.current[:pg] ||= PG.connect(DATABASE_URL)
end

# Wait for the database rather than crashing if it is a second behind. compose already
# gates startup on a healthcheck; this is the belt to that braces, because in a real
# platform nothing promises your dependencies start first.
deadline = Time.now + 30
begin
  PG.connect(DATABASE_URL).close
rescue PG::Error => e
  raise e if Time.now > deadline

  warn 'waiting for the database'
  sleep 0.5
  retry
end

# --- errors ------------------------------------------------------------------

# Signals a failure this service designed, as opposed to one that happened to it.
class DomainError < StandardError
  attr_reader :kind, :title, :status, :detail

  def initialize(kind, title, status, detail)
    super(detail)
    @kind = kind
    @title = title
    @status = status
    @detail = detail
  end
end

# One error envelope, everywhere — RFC 9457, exactly as contracts/problem.yaml says.
error DomainError do
  failure = env['sinatra.error']
  problem(failure.status, failure.kind, failure.title, failure.detail)
end

# Anything unnamed is a bug. 500, and the detail stays in our logs — never in a response
# body, where it becomes a client's problem to parse and an attacker's to read.
error StandardError do
  warn "unhandled error on #{request.path}: #{env['sinatra.error']}"
  problem(500, 'internal-error', 'Internal server error',
          'The request could not be completed.')
end

# A path that matches no route. Sinatra's default is an HTML page, which is a second
# error shape for clients to learn.
not_found do
  problem(404, 'product-not-found', 'Product not found',
          "No product with sku '#{request.path}'.")
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

# Liveness only — it does not touch the database.
#
# Tempting to run `SELECT 1` here. Don't: if this endpoint failed whenever Postgres
# hiccupped, the platform would start killing catalog pods during a database blip,
# removing capacity exactly when the system is least able to spare it.
get '/health' do
  { status: 'ok', implementation: IMPLEMENTATION }.to_json
end

# Keyset pagination. An offset would drift under concurrent inserts; a cursor is a
# position in the data rather than a count of rows someone else can change.
#
# Ask for limit + 1 rows: if the extra one comes back, there is another page.
get '/v1/products' do
  raw_limit = params['limit']
  cursor = params['cursor']

  # The contract declares 1..100 and says an out-of-range value is a 400 in the usual
  # envelope. Sinatra hands every parameter over as a string with no opinion about its
  # range, so the check happens here, by hand.
  limit = 20
  if raw_limit
    limit = Integer(raw_limit, exception: false)
    unless limit&.between?(1, 100)
      raise DomainError.new('validation-failed', 'Validation failed', 400,
                            'limit must be an integer between 1 and 100.')
    end
  end

  rows = if cursor && !cursor.empty?
           db.exec_params(
             'SELECT sku, name, price_cents, stock FROM products' \
             ' WHERE sku > $1 ORDER BY sku LIMIT $2', [cursor, limit + 1]
           )
         else
           db.exec_params(
             'SELECT sku, name, price_cents, stock FROM products ORDER BY sku LIMIT $1',
             [limit + 1]
           )
         end

  has_more = rows.ntuples > limit
  # Postgres hands everything back as a string, BIGINT included. Ship these without the
  # to_i and a client that expected a number gets "18900" instead.
  items = rows.first(limit).map do |row|
    { sku: row['sku'], name: row['name'],
      price_cents: row['price_cents'].to_i, stock: row['stock'].to_i }
  end

  # nil on the last page, which to_json renders as null — the contract says null, not "".
  { items: items, next_cursor: has_more && !items.empty? ? items.last[:sku] : nil }.to_json
end

# The call `orders` makes during checkout.
#
# Its 404 is the most consequential response in this service. Orders has to turn it into
# a designed order rejection — so it must be unambiguous, carry the sku that was missing,
# and never arrive as a 500. A dependency that fails clearly is a dependency you can
# build on.
get '/v1/products/:sku' do
  sku = params['sku']
  rows = db.exec_params(
    'SELECT sku, name, price_cents, stock FROM products WHERE sku = $1', [sku]
  )

  if rows.ntuples.zero?
    raise DomainError.new('product-not-found', 'Product not found', 404,
                          "No product with sku '#{sku}'.")
  end

  row = rows[0]
  { sku: row['sku'], name: row['name'],
    price_cents: row['price_cents'].to_i, stock: row['stock'].to_i }.to_json
end
