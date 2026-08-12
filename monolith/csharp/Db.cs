using Microsoft.Data.Sqlite;

namespace Store;

/// <summary>
/// The single database.
///
/// One file, one schema, every module's tables in it. <see cref="Transaction{T}"/> is
/// the thing this whole bootcamp is about losing: an atomic scope that spans three
/// modules, costs nothing, and cannot half-succeed.
/// </summary>
public sealed class Db : IDisposable
{
    private readonly SqliteConnection _connection;
    private SqliteTransaction? _transaction;

    public Db()
    {
        if (Config.ResetDb)
        {
            foreach (var suffix in new[] { "", "-journal", "-wal", "-shm" })
            {
                File.Delete(Config.DatabasePath + suffix);
            }
        }

        _connection = new SqliteConnection($"Data Source={Config.DatabasePath}");
        _connection.Open();
        // Foreign keys are off by default in SQLite. Turning them on is what makes
        // order_lines.sku -> products.sku a real constraint rather than a comment.
        Execute("PRAGMA foreign_keys = ON");

        // Real systems use migration tools. A teaching repo uses a file you can read,
        // and a database that is identical every time you start it.
        ExecuteScript(File.ReadAllText(Config.SchemaPath));
        ExecuteScript(File.ReadAllText(Config.SeedPath));
    }

    /// <summary>
    /// Runs a whole SQL file verbatim. Separate from <see cref="Execute"/> because the
    /// parameter rewriting there would mangle a literal <c>?</c> in a comment.
    /// </summary>
    private void ExecuteScript(string sql)
    {
        using var command = _connection.CreateCommand();
        command.Transaction = _transaction;
        command.CommandText = sql;
        command.ExecuteNonQuery();
    }

    /// <summary>
    /// Runs <paramref name="body"/> inside one transaction, rolling back if it throws.
    ///
    /// Note that no module has to pass a connection around: every service shares this
    /// one object, so once BEGIN has run, every statement any module executes is part
    /// of the transaction. That ambient behaviour is exactly how Spring's
    /// <c>@Transactional</c> works, and it is why the Java implementation reads the same.
    ///
    /// Look at what it buys checkout: stock is reserved, the order is written and the
    /// card is charged, and if the card is declined every one of those disappears. No
    /// compensating action, no saga, no idempotency key, no partial state to reconcile
    /// at 3am. One ROLLBACK.
    ///
    /// In Session 3 these three modules become three services with three databases and
    /// this method becomes impossible to write. Everything you will learn about sagas,
    /// idempotency and retries exists to buy back a fraction of what it does for free.
    /// </summary>
    public T Transaction<T>(Func<T> body)
    {
        _transaction = _connection.BeginTransaction();
        try
        {
            var result = body();
            _transaction.Commit();
            return result;
        }
        catch
        {
            _transaction.Rollback();
            throw;
        }
        finally
        {
            _transaction.Dispose();
            _transaction = null;
        }
    }

    public List<T> Query<T>(string sql, Func<SqliteDataReader, T> map, params object?[] parameters)
    {
        using var command = Command(sql, parameters);
        using var reader = command.ExecuteReader();

        var rows = new List<T>();
        while (reader.Read()) rows.Add(map(reader));
        return rows;
    }

    public T? QueryOne<T>(string sql, Func<SqliteDataReader, T> map, params object?[] parameters)
        where T : class => Query(sql, map, parameters).FirstOrDefault();

    public void Execute(string sql, params object?[] parameters)
    {
        using var command = Command(sql, parameters);
        command.ExecuteNonQuery();
    }

    /// <summary>
    /// Microsoft.Data.Sqlite binds parameters by name, while the other five
    /// implementations in this repo use positional <c>?</c> placeholders. Rewriting
    /// them here keeps every SQL string in the module code byte-identical across all
    /// six languages — the adapter lives in one place instead of leaking into the
    /// domain.
    /// </summary>
    private SqliteCommand Command(string sql, object?[] parameters)
    {
        var command = _connection.CreateCommand();
        command.Transaction = _transaction;

        var index = 0;
        while (sql.Contains('?'))
        {
            var position = sql.IndexOf('?');
            sql = string.Concat(sql.AsSpan(0, position), $"$p{index}", sql.AsSpan(position + 1));
            index++;
        }
        command.CommandText = sql;

        for (var i = 0; i < parameters.Length; i++)
        {
            command.Parameters.AddWithValue($"$p{i}", parameters[i] ?? DBNull.Value);
        }
        return command;
    }

    public void Dispose() => _connection.Dispose();
}
