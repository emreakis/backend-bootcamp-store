package io.backendguru.store.catalog;

import java.net.URI;
import java.util.List;
import java.util.Map;

import javax.sql.DataSource;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import com.zaxxer.hikari.HikariDataSource;

import jakarta.servlet.http.HttpServletRequest;

/**
 * CATALOG — the read side of the store, and the simplest service in the system.
 *
 * <p>Small enough to read in one file, which is why it is the one to read first.
 * Everything here satisfies contracts/catalog.v1.yaml; if this file and that file
 * disagree, this file is wrong.
 *
 * <p>Compare it with {@code monolith/java/.../catalog/CatalogService.java}. The SQL is
 * identical. What changed is everything around it: its own database, its own process,
 * its own deployment, and a {@code reserve} method that no longer exists because stock
 * cannot be taken off a shelf in one database inside a transaction that lives in
 * another.
 */
@SpringBootApplication
public class CatalogApplication {

    public static void main(String[] args) {
        SpringApplication.run(CatalogApplication.class, args);
    }

    /**
     * Every service in this repo reads one {@code DATABASE_URL} in the same libpq
     * form, whatever language it is written in. JDBC wants a different shape, so the
     * translation happens here — once, at the boundary — rather than by giving Java a
     * special environment variable the other five do not have.
     */
    @Bean
    DataSource dataSource(
            @Value("${DATABASE_URL:postgres://store:store@localhost:5433/catalog}") String databaseUrl) {
        URI uri = URI.create(databaseUrl);
        String[] credentials = uri.getUserInfo().split(":", 2);

        HikariDataSource dataSource = new HikariDataSource();
        dataSource.setJdbcUrl("jdbc:postgresql://%s:%d%s".formatted(
                uri.getHost(), uri.getPort() == -1 ? 5432 : uri.getPort(), uri.getPath()));
        dataSource.setUsername(credentials[0]);
        dataSource.setPassword(credentials.length > 1 ? credentials[1] : "");
        return dataSource;
    }
}

record Product(String sku, String name, long priceCents, long stock) {
}

/** {@code nextCursor} is null on the last page — the contract says null, not "". */
record ProductPage(List<Product> items, String nextCursor) {
}

/** Signals a failure this service designed, as opposed to one that happened to it. */
class DomainException extends RuntimeException {
    final String kind;
    final String title;
    final int status;

    DomainException(String kind, String title, int status, String detail) {
        super(detail);
        this.kind = kind;
        this.title = title;
        this.status = status;
    }
}

@RestController
class CatalogController {

    private static final RowMapper<Product> MAPPER = (rs, i) -> new Product(
            rs.getString("sku"), rs.getString("name"),
            rs.getLong("price_cents"), rs.getLong("stock"));

    private final JdbcTemplate jdbc;
    private final String implementation;

    CatalogController(JdbcTemplate jdbc, @Value("${store.implementation}") String implementation) {
        this.jdbc = jdbc;
        this.implementation = implementation;
    }

    /**
     * Liveness only — it does not touch the database.
     *
     * <p>Tempting to run {@code SELECT 1} here. Don't: if this endpoint failed whenever
     * Postgres hiccupped, the platform would start killing catalog pods during a
     * database blip, removing capacity exactly when the system is least able to spare
     * it. Liveness answers "should I be restarted?", and only this process knows.
     */
    @GetMapping("/health")
    Map<String, String> health() {
        return Map.of("status", "ok", "implementation", implementation);
    }

    /**
     * Keyset pagination. An offset would drift under concurrent inserts; a cursor is a
     * position in the data rather than a count of rows someone else can change.
     *
     * <p>Ask for limit + 1 rows: if the extra one comes back, there is another page.
     */
    @GetMapping("/v1/products")
    ProductPage list(@RequestParam(defaultValue = "20") int limit,
                     @RequestParam(required = false) String cursor) {

        if (limit < 1 || limit > 100) {
            throw new DomainException("validation-failed", "Validation failed", 400,
                    "limit must be an integer between 1 and 100.");
        }

        List<Product> rows = (cursor == null || cursor.isBlank())
                ? jdbc.query("SELECT sku, name, price_cents, stock FROM products"
                        + " ORDER BY sku LIMIT ?", MAPPER, limit + 1)
                : jdbc.query("SELECT sku, name, price_cents, stock FROM products"
                        + " WHERE sku > ? ORDER BY sku LIMIT ?", MAPPER, cursor, limit + 1);

        boolean hasMore = rows.size() > limit;
        List<Product> items = hasMore ? rows.subList(0, limit) : rows;
        return new ProductPage(items,
                hasMore && !items.isEmpty() ? items.get(items.size() - 1).sku() : null);
    }

    /**
     * The call {@code orders} makes during checkout.
     *
     * <p>Its 404 is the most consequential response in this service. Orders has to turn
     * it into a designed order rejection — so it must be unambiguous, carry the sku
     * that was missing, and never arrive as a 500. A dependency that fails clearly is a
     * dependency you can build on.
     */
    @GetMapping("/v1/products/{sku}")
    Product get(@PathVariable String sku) {
        return jdbc.query("SELECT sku, name, price_cents, stock FROM products WHERE sku = ?",
                        MAPPER, sku)
                .stream().findFirst()
                .orElseThrow(() -> new DomainException("product-not-found", "Product not found",
                        404, "No product with sku '%s'.".formatted(sku)));
    }
}

/**
 * One error envelope, everywhere — RFC 9457, exactly as contracts/problem.yaml says.
 *
 * <p>Spring ships {@link ProblemDetail} as a first-class type, so the RFC is not
 * something this project invented. The whole ecosystem already speaks it.
 */
@RestControllerAdvice
class ProblemAdvice {

    private ResponseEntity<ProblemDetail> render(String kind, String title, int status,
                                                 String detail, HttpServletRequest request) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.valueOf(status), detail);
        problem.setType(URI.create("https://bootcamp.backendguru.io/problems/" + kind));
        problem.setTitle(title);
        problem.setInstance(URI.create(request.getRequestURI()));

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_PROBLEM_JSON);
        return new ResponseEntity<>(problem, headers, HttpStatus.valueOf(status));
    }

    @ExceptionHandler(DomainException.class)
    ResponseEntity<ProblemDetail> onDomain(DomainException e, HttpServletRequest request) {
        return render(e.kind, e.title, e.status, e.getMessage(), request);
    }

    /**
     * {@code ?limit=abc}. Spring's default for a query parameter it cannot bind is a
     * 400 with its own body shape — right status, wrong envelope. The contract has one
     * error shape and this is still one of its paths, so it gets translated here.
     *
     * <p>This is the most common way an implementation drifts from its spec: not by
     * getting an endpoint wrong, but by letting the framework answer on a path nobody
     * wrote by hand.
     */
    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    ResponseEntity<ProblemDetail> onUnbindable(HttpServletRequest request) {
        return render("validation-failed", "Validation failed", 400,
                "limit must be an integer between 1 and 100.", request);
    }

    /** A path that matches no route. Spring's default would let this become a 500. */
    @ExceptionHandler(NoResourceFoundException.class)
    ResponseEntity<ProblemDetail> onNoRoute(HttpServletRequest request) {
        return render("product-not-found", "Product not found", 404,
                "No product with sku '%s'.".formatted(request.getRequestURI()), request);
    }

    /** Anything unnamed is a bug. 500, and the detail stays in our logs. */
    @ExceptionHandler(Exception.class)
    ResponseEntity<ProblemDetail> onUnexpected(Exception e, HttpServletRequest request) {
        System.err.println("unhandled error on " + request.getRequestURI() + ": " + e);
        return render("internal-error", "Internal server error", 500,
                "The request could not be completed.", request);
    }
}
