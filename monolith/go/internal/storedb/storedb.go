// Package storedb owns the single database connection and the atomic scope.
//
// One file, one schema, every module's tables in it. InTx is the thing this whole
// bootcamp is about losing: an atomic scope that spans three modules, costs
// nothing, and cannot half-succeed.
package storedb

import (
	"database/sql"
	"fmt"
	"os"

	"github.com/backendguru/store/internal/config"
	_ "modernc.org/sqlite" // pure-Go driver: no cgo, so the image needs no toolchain
)

// Querier is satisfied by both *sql.DB and *sql.Tx.
//
// This one interface is why a module function can be called standalone or as part
// of somebody else's transaction without knowing which. Look at how catalog.Reserve
// uses it, then imagine writing the same thing when catalog is across a network.
type Querier interface {
	Query(query string, args ...any) (*sql.Rows, error)
	QueryRow(query string, args ...any) *sql.Row
	Exec(query string, args ...any) (sql.Result, error)
}

func Open() (*sql.DB, error) {
	if config.ResetDB {
		for _, suffix := range []string{"", "-journal", "-wal", "-shm"} {
			os.Remove(config.DatabasePath + suffix)
		}
	}

	db, err := sql.Open("sqlite", config.DatabasePath+"?_pragma=busy_timeout(5000)")
	if err != nil {
		return nil, err
	}
	// SQLite takes one writer at a time. A single connection keeps this teaching
	// build free of "database is locked" noise that has nothing to teach.
	db.SetMaxOpenConns(1)

	// Foreign keys are off by default in SQLite. Turning them on is what makes
	// order_lines.sku -> products.sku a real constraint rather than a comment.
	if _, err := db.Exec("PRAGMA foreign_keys = ON"); err != nil {
		return nil, err
	}
	return db, nil
}

// Bootstrap applies schema and seed at boot. Real systems use migration tools; a
// teaching repo uses a file you can read and a database that is identical every
// time you start it.
func Bootstrap(db *sql.DB) error {
	for _, path := range []string{config.SchemaPath, config.SeedPath} {
		sqlText, err := os.ReadFile(path)
		if err != nil {
			return fmt.Errorf("reading %s: %w", path, err)
		}
		if _, err := db.Exec(string(sqlText)); err != nil {
			return fmt.Errorf("applying %s: %w", path, err)
		}
	}
	return nil
}

// InTx runs fn inside one transaction, rolling back on any error.
//
// Look at what this buys checkout: stock is reserved, the order is written and the
// card is charged, and if the card is declined every one of those disappears. No
// compensating action, no saga, no idempotency key, no partial state to reconcile
// at 3am. One ROLLBACK.
//
// In Session 3 these three modules become three services with three databases and
// this function becomes impossible to write. Everything you will learn about sagas,
// idempotency and retries exists to buy back a fraction of what it does for free.
func InTx(db *sql.DB, fn func(tx *sql.Tx) error) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	if err := fn(tx); err != nil {
		tx.Rollback()
		return err
	}
	return tx.Commit()
}
