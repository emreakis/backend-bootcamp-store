namespace Store.Catalog;

/// <summary>The catalog module's public data.</summary>
public sealed record Product(string Sku, string Name, long PriceCents, long Stock);

/// <summary>One page of products. <c>NextCursor</c> is null on the last page.</summary>
public sealed record ProductPage(IReadOnlyList<Product> Items, string? NextCursor);

/// <summary>
/// MODULE: catalog — owns <c>products</c>.
///
/// Public API: ListProducts, GetProduct, Reserve, Release.
///
/// No other module may touch the <c>products</c> table. If <c>orders</c> wants a price
/// it calls GetProduct; if it wants stock it calls Reserve. C# enforces the half of
/// this that a compiler can: <c>MapProduct</c> below is private, so the only surface
/// another module can reach is the four public methods. The other half — that the
/// string "products" appears in no other file — is discipline, and it is what makes
/// the Session 3 split a mechanical exercise rather than a rewrite.
/// </summary>
public sealed class CatalogService(Db db)
{
    /// <summary>
    /// One page of products, plus the cursor for the next.
    ///
    /// Keyset pagination, not OFFSET. An offset drifts: insert a product while a client
    /// is on page 2 and it either sees a row twice or misses one entirely. A cursor is
    /// a position in the data, not a count of rows someone else can change.
    ///
    /// We ask for limit + 1 rows: if the extra one comes back there is another page.
    /// </summary>
    public ProductPage ListProducts(int limit = 20, string? cursor = null)
    {
        var rows = string.IsNullOrEmpty(cursor)
            ? db.Query("SELECT sku, name, price_cents, stock FROM products ORDER BY sku LIMIT ?",
                MapProduct, limit + 1)
            : db.Query("SELECT sku, name, price_cents, stock FROM products WHERE sku > ?" +
                " ORDER BY sku LIMIT ?", MapProduct, cursor, limit + 1);

        var hasMore = rows.Count > limit;
        var items = hasMore ? rows.Take(limit).ToList() : rows;
        return new ProductPage(items, hasMore && items.Count > 0 ? items[^1].Sku : null);
    }

    public Product GetProduct(string sku) =>
        db.QueryOne("SELECT sku, name, price_cents, stock FROM products WHERE sku = ?",
            MapProduct, sku)
        ?? throw DomainException.ProductNotFound(sku);

    /// <summary>
    /// Takes <paramref name="qty"/> units off the shelf and returns the product as it
    /// was priced.
    ///
    /// Nothing here mentions a transaction. Because every service shares one connection,
    /// this UPDATE silently joins whatever transaction the caller opened — reserving
    /// stock and writing the order become one atomic act, and neither module had to
    /// know that.
    ///
    /// Once catalog is a separate service, that silence becomes a lie. What replaces it
    /// is a saga, and a compensating "un-reserve" that has to survive the process
    /// crashing between the two calls.
    /// </summary>
    public Product Reserve(string sku, long qty)
    {
        var product = GetProduct(sku);
        if (product.Stock < qty)
        {
            throw DomainException.InsufficientStock(sku, qty, product.Stock);
        }

        db.Execute("UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?",
            qty, sku, qty);
        return product;
    }

    /// <summary>Puts stock back — used when an order is cancelled.</summary>
    public void Release(string sku, long qty) =>
        db.Execute("UPDATE products SET stock = stock + ? WHERE sku = ?", qty, sku);

    private static Product MapProduct(Microsoft.Data.Sqlite.SqliteDataReader reader) =>
        new(reader.GetString(0), reader.GetString(1), reader.GetInt64(2), reader.GetInt64(3));
}
