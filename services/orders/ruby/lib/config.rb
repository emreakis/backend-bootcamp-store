# frozen_string_literal: true

# Configuration from the environment. Never from code.
#
# Seven values, five of them about what to do when somebody else fails. Catalog has
# two. That ratio is the price of being the service in the middle.
#
# Note what is NOT here: a hostname anybody typed. `catalog` and `payments` are service
# names the platform resolves — compose's DNS today, a Kubernetes Service tomorrow, with
# no code change. Hard-coding an address is how you make an image that only runs in one
# place.
module Config
  IMPLEMENTATION = 'ruby'

  PORT = Integer(ENV.fetch('PORT', '8080'))
  DATABASE_URL = ENV.fetch('DATABASE_URL', 'postgres://store:store@localhost:5434/orders')

  CATALOG_URL   = ENV.fetch('CATALOG_URL', 'http://localhost:8000')
  PAYMENTS_ADDR = ENV.fetch('PAYMENTS_ADDR', 'localhost:50051')

  # Policy, not guesswork. 2000 ms is a statement about how long a checkout may wait on
  # a charge, made by the people who own checkout — not an estimate of how fast payments
  # happens to be today.
  #
  # All four are read here and then, in this starter, quietly ignored. That is
  # exercise 3.
  CATALOG_TIMEOUT_MS  = Integer(ENV.fetch('CATALOG_TIMEOUT_MS', '1000'))
  PAYMENTS_TIMEOUT_MS = Integer(ENV.fetch('PAYMENTS_TIMEOUT_MS', '2000'))
  PAYMENTS_RETRY_MAX  = Integer(ENV.fetch('PAYMENTS_RETRY_MAX', '2'))
  BREAKER_FAILURE_THRESHOLD = Integer(ENV.fetch('BREAKER_FAILURE_THRESHOLD', '5'))
  BREAKER_RESET_MS          = Integer(ENV.fetch('BREAKER_RESET_MS', '10000'))
end
