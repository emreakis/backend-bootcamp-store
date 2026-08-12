# frozen_string_literal: true

require 'sqlite3'
require_relative 'config'

# The single database.
#
# One file, one schema, every module's tables in it. `transaction` is the thing this
# whole bootcamp is about losing: an atomic scope that spans three modules, costs
# nothing, and cannot half-succeed.
module Database
  module_function

  def connection
    @connection ||= begin
      db = SQLite3::Database.new(Config::DATABASE_PATH)
      db.busy_timeout = 5000
      # Foreign keys are off by default in SQLite. Turning them on is what makes
      # order_lines.sku -> products.sku a real constraint rather than a comment.
      db.execute('PRAGMA foreign_keys = ON')
      db
    end
  end

  # Applies schema and seed at boot. Real systems use migration tools; a teaching repo
  # uses a file you can read, and a database that is identical every time you start it.
  def bootstrap!
    if Config::RESET_DB
      ['', '-journal', '-wal', '-shm'].each do |suffix|
        File.delete(Config::DATABASE_PATH + suffix) if File.exist?(Config::DATABASE_PATH + suffix)
      end
    end

    connection.execute_batch(File.read(Config::SCHEMA_PATH))
    connection.execute_batch(File.read(Config::SEED_PATH))
  end

  def query(sql, *params)
    connection.execute(sql, params)
  end

  def execute(sql, *params)
    connection.execute(sql, params)
  end

  # Runs the block inside one transaction, rolling back if it raises.
  #
  # Note that no module has to pass a connection around: every module reaches the same
  # object, so once BEGIN has run, every statement any of them executes is part of the
  # transaction. That ambient behaviour is exactly how Spring's @Transactional works,
  # and it is why the Java implementation reads the same.
  #
  # Look at what it buys checkout: stock is reserved, the order is written and the card
  # is charged, and if the card is declined every one of those disappears. No
  # compensating action, no saga, no idempotency key, no partial state to reconcile at
  # 3am. One ROLLBACK.
  #
  # In Session 3 these three modules become three services with three databases and
  # this method becomes impossible to write. Everything you will learn about sagas,
  # idempotency and retries exists to buy back a fraction of what it does for free.
  def transaction
    # The result is captured rather than returned from inside the block: sqlite3's
    # own `transaction` returns true, not the block's value, and a bare `return`
    # here would jump out past its commit.
    result = nil
    connection.transaction { result = yield }
    result
  end
end
