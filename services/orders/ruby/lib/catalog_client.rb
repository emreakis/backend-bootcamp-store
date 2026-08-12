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
    # EXERCISE 3.4 — the timeout.
    #
    # Two settings, not one, and the split is the useful part: `open` is "I cannot reach
    # this host" and `read` is "this host accepted my connection and then went quiet".
    # Different failures with different causes, and only the second is what
    # `docker compose pause catalog` produces. Ruby is one of the few standard libraries
    # that makes you name both, which is a kindness disguised as extra work.
    #
    # Both come from the same environment variable here because one number is enough for
    # a teaching system. In a real service they differ: open is fast and unforgiving,
    # read is generous enough for the slowest legitimate response.
    #
    # Note what this replaced: two explicit `nil`s, not Ruby's 60-second defaults. Those
    # were switched off on `main` on purpose, because sixty seconds is Ruby's opinion
    # about a reasonable wait and CATALOG_TIMEOUT_MS is *your* statement about how long
    # a checkout may spend pricing a line.
    #
    # Prove it: `docker compose pause catalog` and post an order. Before this change the
    # request hung; now it is a 503 in one second.
    # ====================================================================
    client.open_timeout = Config::CATALOG_TIMEOUT_MS / 1000.0
    client.read_timeout = Config::CATALOG_TIMEOUT_MS / 1000.0

    client.start
    client
  end
end
