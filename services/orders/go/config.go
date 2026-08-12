package main

import (
	"os"
	"strconv"
	"time"
)

const implementation = "go"

// Configuration from the environment. Never from code.
//
// Seven values, five of them about what to do when somebody else fails. Catalog has
// two. That ratio is the price of being the service in the middle.
//
// Note what is NOT here: a hostname anybody typed. `catalog` and `payments` are
// service names the platform resolves — compose's DNS today, a Kubernetes Service
// tomorrow, with no code change. Hard-coding an address is how you make an image that
// only runs in one place.
type config struct {
	port         string
	databaseURL  string
	catalogURL   string
	paymentsAddr string

	// Policy, not guesswork. 2000 ms is a statement about how long a checkout may
	// wait on a charge, made by the people who own checkout — not an estimate of how
	// fast payments happens to be today.
	//
	// All four are loaded here and then, in this starter, quietly ignored. That is
	// exercise 3.
	catalogTimeout   time.Duration
	paymentsTimeout  time.Duration
	paymentsRetryMax int
	breakerThreshold int
	breakerReset     time.Duration
}

func load() config {
	return config{
		port:         env("PORT", "8080"),
		databaseURL:  env("DATABASE_URL", "postgres://store:store@localhost:5434/orders"),
		catalogURL:   env("CATALOG_URL", "http://localhost:8000"),
		paymentsAddr: env("PAYMENTS_ADDR", "localhost:50051"),

		catalogTimeout:   time.Duration(envInt("CATALOG_TIMEOUT_MS", 1000)) * time.Millisecond,
		paymentsTimeout:  time.Duration(envInt("PAYMENTS_TIMEOUT_MS", 2000)) * time.Millisecond,
		paymentsRetryMax: int(envInt("PAYMENTS_RETRY_MAX", 2)),
		breakerThreshold: int(envInt("BREAKER_FAILURE_THRESHOLD", 5)),
		breakerReset:     time.Duration(envInt("BREAKER_RESET_MS", 10000)) * time.Millisecond,
	}
}

func env(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func envInt(key string, fallback int64) int64 {
	if value := os.Getenv(key); value != "" {
		if parsed, err := strconv.ParseInt(value, 10, 64); err == nil {
			return parsed
		}
	}
	return fallback
}
