// The module path matches the `go_package` option in contracts/payments.v1.proto,
// which is what lets protoc write the generated package straight into ./gen/paymentsv1.
//
// The orders service in Go declares the same module path for the same reason: both
// sides of a gRPC contract import the identical generated package, because both were
// produced from the identical file.
module github.com/backendguru/store

go 1.24
