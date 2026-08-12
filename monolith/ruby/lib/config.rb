# frozen_string_literal: true

# Configuration comes from the environment. Never from code.
#
# Twelve-factor, and the reason it matters here: the artifact you run in Session 3 is
# identical in dev and prod. Only the environment around it changes. Hard-code one
# address and that stops being true.
module Config
  IMPLEMENTATION = 'ruby'

  PORT          = Integer(ENV.fetch('PORT', '8080'))
  DATABASE_PATH = ENV.fetch('DATABASE_PATH', './store.db')
  SCHEMA_PATH   = ENV.fetch('SCHEMA_PATH', '../../db/schema.sql')
  SEED_PATH     = ENV.fetch('SEED_PATH', '../../db/seed.sql')
  RESET_DB      = ENV.fetch('RESET_DB', 'true') != 'false'

  # The payment stub is deterministic on purpose. A demo that fails randomly teaches
  # nothing; a demo that fails on command teaches one thing at a time.
  PAYMENT_DECLINE_OVER_CENTS = Integer(ENV.fetch('PAYMENT_DECLINE_OVER_CENTS', '500000'))
  PAYMENT_ALWAYS_DECLINE     = ENV.fetch('PAYMENT_ALWAYS_DECLINE', 'false') == 'true'
end
