// Package id generates identifiers. Hand-rolled so the module stays at one
// dependency — the point of this repo is the architecture, not the go.sum.
package id

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
)

// New returns a random UUID v4.
func New() string {
	var b [16]byte
	rand.Read(b[:])
	b[6] = (b[6] & 0x0f) | 0x40 // version 4
	b[8] = (b[8] & 0x3f) | 0x80 // variant 10
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

// Short returns an 8-character uppercase token, used for authorisation codes.
func Short() string {
	var b [4]byte
	rand.Read(b[:])
	return string([]byte(hexUpper(b[:])))
}

func hexUpper(b []byte) string {
	s := hex.EncodeToString(b)
	out := make([]byte, len(s))
	for i := 0; i < len(s); i++ {
		if s[i] >= 'a' && s[i] <= 'f' {
			out[i] = s[i] - 32
		} else {
			out[i] = s[i]
		}
	}
	return string(out)
}
