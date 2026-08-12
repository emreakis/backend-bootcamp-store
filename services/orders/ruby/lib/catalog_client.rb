# frozen_string_literal: true

require 'json'
require 'net/http'
require 'uri'
require_relative 'config'
require_relative 'errors'

# The REST half of this service's dependencies.
#
# In the monolith this was `Catalog.get_product(db, sku)` — a method call that could not
# fail on its own. It is now an HTTP request over a network, and every one of the eight
# fallacies applies to it.
module CatalogClient
  BASE = URI.parse(Config::CATALOG_URL)

  module_function

  # Price one sku.
  #
  # Three outcomes, and all three are designed:
  #
  #   * the product exists — we take its name and price and stop caring about it;
  #   * catalog says 404 — a *designed order rejection*, not a 500. Passing a
  #     dependency's status straight through would be lazy; letting it become a stack
  #     trace would be worse;
  #   * catalog cannot be reached — 503, because the customer did nothing wrong.
  def fetch(sku)
    response = http.request(Net::HTTP::Get.new("/v1/products/#{sku}"))

    raise ProductNotFound, sku if response.code == '404'

    unless response.code == '200'
      warn "catalog answered #{response.code} for sku=#{sku}"
      raise CatalogUnavailable,
            'The catalog service returned an unusable response. No order was placed.'
    end

    body = JSON.parse(response.body)
    { sku: body['sku'], name: body['name'], price_cents: body['price_cents'] }
  rescue Net::OpenTimeout, Net::ReadTimeout
    # Only reachable once exercise 3.4 is done. Until then this client is patient to a
    # fault and the request simply never comes back.
    warn "catalog timed out for sku=#{sku}"
    raise CatalogUnavailable,
          'The catalog service did not respond in time. No order was placed.'
  rescue SystemCallError, SocketError, IOError => e
    # Connection refused, DNS failure, connection reset.
    warn "catalog unreachable for sku=#{sku}: #{e.message}"
    raise CatalogUnavailable,
          'The catalog service could not be reached. No order was placed.'
  end

  # One connection per call, deliberately not memoised.
  #
  # Net::HTTP is not thread-safe, and puma serves this app from a pool of threads — so a
  # single shared connection would be a race waiting for load to find it. Every other
  # implementation in this repo reuses one client object because their libraries are
  # built for it; Ruby's standard one is not, and pretending otherwise is how you get a
  # bug that only appears in production.
  def http
    client = Net::HTTP.new(BASE.host, BASE.port)

    # ====================================================================
    # TODO (exercise 3.4) — GIVE THIS CLIENT A TIMEOUT.
    #
    # Read the two `nil`s below carefully, because Ruby is one of three languages in
    # this repo that ships a default here at all.
    #
    # Net::HTTP defaults to 60 seconds for both open and read. They have been switched
    # OFF on purpose, and for two reasons.
    #
    #   1. So this exercise matches the languages that genuinely wait forever — Java's
    #      RestClient, Go's bare http.Client, Node's fetch. Sixty seconds in a classroom
    #      is indistinguishable from forever anyway.
    #
    #   2. Because a library default is not a policy. Sixty seconds is Ruby's opinion
    #      about a reasonable wait for an arbitrary HTTP call; CATALOG_TIMEOUT_MS is
    #      *your* statement about how long a checkout may spend pricing a line. Those
    #      are different numbers that happen to share units, and inheriting one when you
    #      meant the other is how a service ends up with a latency budget nobody chose.
    #
    # So: set both from Config::CATALOG_TIMEOUT_MS, in SECONDS.
    #
    #     client.open_timeout = Config::CATALOG_TIMEOUT_MS / 1000.0
    #     client.read_timeout = Config::CATALOG_TIMEOUT_MS / 1000.0
    #
    # Two settings, not one, and the split is the useful part: `open` is "I cannot reach
    # this host" and `read` is "this host accepted my connection and then went quiet".
    # They are different failures with different causes, and Ruby is one of the few
    # standard libraries that makes you name both.
    #
    # Then prove it: `docker compose pause catalog` and post an order. Before the fix the
    # request hangs; after it, you get a 503 in one second. `pause` rather than `stop`,
    # because a stopped container refuses connections instantly and a paused one leaves
    # you hanging — which is the whole point.
    # ====================================================================
    client.open_timeout = nil
    client.read_timeout = nil

    client.start
    client
  end
end
