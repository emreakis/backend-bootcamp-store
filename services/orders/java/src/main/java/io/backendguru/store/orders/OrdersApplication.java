package io.backendguru.store.orders;

import java.net.URI;

import javax.sql.DataSource;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;

import com.zaxxer.hikari.HikariDataSource;

/**
 * ORDERS — the orchestrator. REST at the edge, gRPC inside, and the only service that
 * talks to the other two.
 *
 * <p>It is also the one that pages you at 3am, which is not a coincidence: a service
 * with no dependencies has no partial failures to handle.
 */
@SpringBootApplication
public class OrdersApplication {

    public static void main(String[] args) {
        SpringApplication.run(OrdersApplication.class, args);
    }

    /**
     * Every service in this repo reads one {@code DATABASE_URL} in the same libpq
     * form, whatever language it is written in. JDBC wants a different shape, so the
     * translation happens here — once, at the boundary — rather than by giving Java a
     * special environment variable the other five do not have.
     *
     * <p>Same instinct as the C# monolith rewriting {@code ?} placeholders: adapt at
     * the edge and keep the shared thing genuinely shared.
     */
    @Bean
    DataSource dataSource(@Value("${DATABASE_URL:postgres://store:store@localhost:5434/orders}") String databaseUrl) {
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
