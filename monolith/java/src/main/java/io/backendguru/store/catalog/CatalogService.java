package io.backendguru.store.catalog;

import java.util.List;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Service;

import io.backendguru.store.DomainException;

/**
 * MODULE: catalog — owns {@code products}.
 *
 * <p>Public API: {@code listProducts}, {@code getProduct}, {@code reserve},
 * {@code release}.
 *
 * <p>No other module may touch the {@code products} table. If {@code orders} wants a
 * price it calls {@code getProduct}; if it wants stock it calls {@code reserve}. Java
 * enforces the half of this that a compiler can: {@code ROW_MAPPER} and the SQL below
 * are package-private, so nothing outside {@code io.backendguru.store.catalog} can
 * reach them. The other half — that the string "products" appears in no other package
 * — is discipline, and it is what makes the Session 3 split a mechanical exercise
 * rather than a rewrite.
 */
@Service
public class CatalogService {

    private final JdbcTemplate jdbc;

    CatalogService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<Product> ROW_MAPPER = (rs, rowNum) -> new Product(
            rs.getString("sku"), rs.getString("name"),
            rs.getLong("price_cents"), rs.getLong("stock"));

    /**
     * One page of products, plus the cursor for the next.
     *
     * <p>Keyset pagination, not OFFSET. An offset drifts: insert a product while a
     * client is on page 2 and it either sees a row twice or misses one entirely. A
     * cursor is a position in the data, not a count of rows someone else can change.
     *
     * <p>We ask for limit + 1 rows: if the extra one comes back there is another page.
     */
    public ProductPage listProducts(int limit, String cursor) {
        List<Product> rows = (cursor == null || cursor.isBlank())
                ? jdbc.query("SELECT sku, name, price_cents, stock FROM products"
                        + " ORDER BY sku LIMIT ?", ROW_MAPPER, limit + 1)
                : jdbc.query("SELECT sku, name, price_cents, stock FROM products"
                        + " WHERE sku > ? ORDER BY sku LIMIT ?", ROW_MAPPER, cursor, limit + 1);

        boolean hasMore = rows.size() > limit;
        List<Product> items = hasMore ? rows.subList(0, limit) : rows;
        String next = (hasMore && !items.isEmpty()) ? items.get(items.size() - 1).sku() : null;
        return new ProductPage(items, next);
    }

    public Product getProduct(String sku) {
        List<Product> found = jdbc.query(
                "SELECT sku, name, price_cents, stock FROM products WHERE sku = ?",
                ROW_MAPPER, sku);
        if (found.isEmpty()) {
            throw DomainException.productNotFound(sku);
        }
        return found.get(0);
    }

    /**
     * Takes {@code qty} units off the shelf and returns the product as it was priced.
     *
     * <p>Nothing here mentions a transaction. Spring binds one connection to the
     * calling thread, so this UPDATE silently joins whatever transaction the caller
     * opened — reserving stock and writing the order become one atomic act, and
     * neither module had to know that.
     *
     * <p>Once catalog is a separate service, that silence becomes a lie. What replaces
     * it is a saga, and a compensating "un-reserve" that has to survive the process
     * crashing between the two calls.
     */
    public Product reserve(String sku, long qty) {
        Product product = getProduct(sku);
        if (product.stock() < qty) {
            throw DomainException.insufficientStock(sku, qty, product.stock());
        }
        jdbc.update("UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?",
                qty, sku, qty);
        return product;
    }

    /** Puts stock back — used when an order is cancelled. */
    public void release(String sku, long qty) {
        jdbc.update("UPDATE products SET stock = stock + ? WHERE sku = ?", qty, sku);
    }
}
