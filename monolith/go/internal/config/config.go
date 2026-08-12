// Package config reads every setting from the environment. Never from code.
//
// Twelve-factor, and the reason it matters here: the artifact you run in Session 3
// is identical in dev and prod. Only the environment around it changes. Hard-code
// one address and that stops being true.
package config

import (
	"os"
	"strconv"
)

const Implementation = "go"

var (
	Port         = str("PORT", "8080")
	DatabasePath = str("DATABASE_PATH", "./store.db")
	SchemaPath   = str("SCHEMA_PATH", "../../db/schema.sql")
	SeedPath     = str("SEED_PATH", "../../db/seed.sql")
	ResetDB      = str("RESET_DB", "true") != "false"

	// The payment stub is deterministic on purpose. A demo that fails randomly
	// teaches nothing; a demo that fails on command teaches one thing at a time.
	PaymentDeclineOverCents = num("PAYMENT_DECLINE_OVER_CENTS", 500_000)
	PaymentAlwaysDecline    = str("PAYMENT_ALWAYS_DECLINE", "false") == "true"
)

func str(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}

func num(key string, fallback int64) int64 {
	if v, ok := os.LookupEnv(key); ok {
		if parsed, err := strconv.ParseInt(v, 10, 64); err == nil {
			return parsed
		}
	}
	return fallback
}
