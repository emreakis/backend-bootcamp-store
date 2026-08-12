package io.backendguru.store;

import java.io.File;
import java.util.List;

import javax.sql.DataSource;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.ApplicationListener;
import org.springframework.context.annotation.Bean;
import org.springframework.core.io.FileSystemResource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;

/**
 * The store, as a modular monolith. One process, one database, three modules.
 */
@SpringBootApplication
public class StoreApplication {

    public static void main(String[] args) {
        // Deleting the database happens before Spring starts, because the DataSource
        // creates the file the moment it is initialised. Real systems use migration
        // tools; a teaching repo uses a database that is identical every time you
        // start it.
        if (!"false".equalsIgnoreCase(System.getenv().getOrDefault("RESET_DB", "true"))) {
            String path = System.getenv().getOrDefault("DATABASE_PATH", "./store.db");
            for (String suffix : List.of("", "-journal", "-wal", "-shm")) {
                new File(path + suffix).delete();
            }
        }
        SpringApplication.run(StoreApplication.class, args);
    }

    /**
     * Applies schema and seed at boot.
     *
     * {@code ResourceDatabasePopulator} is Spring's script runner: it strips the
     * {@code --} comments and splits on statement boundaries, which a plain
     * {@code Statement.execute} will not do for a multi-statement file.
     */
    @Bean
    ApplicationListener<ApplicationReadyEvent> bootstrap(
            DataSource dataSource,
            @Value("${store.schema-path}") String schemaPath,
            @Value("${store.seed-path}") String seedPath) {

        return event -> {
            ResourceDatabasePopulator populator = new ResourceDatabasePopulator();
            populator.addScript(new FileSystemResource(schemaPath));
            populator.addScript(new FileSystemResource(seedPath));
            populator.execute(dataSource);
        };
    }
}
