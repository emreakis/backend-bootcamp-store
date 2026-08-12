// The module path matches the `go_package` option in
// contracts/proto/bootcamp/payments/v1/payments.proto, which is what lets protoc write
// the generated package straight into ./gen/paymentsv1.
//
// The payments service in Go declares the same module path for the same reason: both
// sides of a gRPC contract import the identical generated package, because both were
// produced from the identical file. That is not a coincidence to be tidied up — it is
// the contract being a single source of truth in the most literal sense available.
module github.com/backendguru/store

go 1.24

require (
	github.com/google/uuid v1.6.0
	github.com/jackc/pgx/v5 v5.7.2
	google.golang.org/grpc v1.70.0
	google.golang.org/protobuf v1.36.4
)
