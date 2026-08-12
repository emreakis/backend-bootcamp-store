package main

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"strings"
)

// newID returns a random UUID v4. Hand-rolled so this service depends on gRPC and
// nothing else.
func newID() string {
	var b [16]byte
	rand.Read(b[:])
	b[6] = (b[6] & 0x0f) | 0x40 // version 4
	b[8] = (b[8] & 0x3f) | 0x80 // variant 10
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

// newToken returns an 8-character uppercase authorisation token.
func newToken() string {
	var b [4]byte
	rand.Read(b[:])
	return strings.ToUpper(hex.EncodeToString(b[:]))
}
