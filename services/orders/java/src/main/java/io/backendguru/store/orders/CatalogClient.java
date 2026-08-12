package io.backendguru.store.orders;

import java.time.Duration;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.http.client.ClientHttpRequestFactoryBuilder;
import org.springframework.boot.http.client.ClientHttpRequestFactorySettings;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * The REST half of this service's dependencies.
 *
 * <p>In the monolith this was {@code catalog.getProduct(conn, sku)} — a function call
 * that could not fail on its own. It is now an HTTP request over a network, and every
 * one of the eight fallacies applies to it.
 */
@Component
public class CatalogClient {

    private static final Logger log = LoggerFactory.getLogger(CatalogClient.class);

    private final RestClient http;
    private final long timeoutMs;

    /**
     * Note the injected {@link RestClient.Builder} rather than the static
     * {@code RestClient.builder()}.
     *
     * <p>This is not a style preference, it is a bug this code already had. The static
     * factory builds a client with stock message converters and a default
     * {@code ObjectMapper} — one that has never heard of the
     * {@code SNAKE_CASE} strategy configured in application.properties. Catalog's
     * {@code price_cents} then quietly fails to bind to {@code priceCents}, every
     * price arrives as 0, and the first sign of trouble is payments rejecting a charge
     * for nothing.
     *
     * <p>The injected builder is Spring Boot's, already wired to the application's own
     * ObjectMapper. A silent zero is the worst kind of deserialisation failure: it does
     * not throw, and it looks like a price.
     */
    CatalogClient(RestClient.Builder builder,
                  @Value("${store.catalog.url}") String baseUrl,
                  @Value("${store.catalog.timeout-ms}") long timeoutMs) {
        this.timeoutMs = timeoutMs;

        // ====================================================================
        // EXERCISE 3.4 — the timeout.
        //
        // Two of them, and the split is the useful part. `connect` is "I cannot reach
        // this host"; `read` is "this host accepted my connection and then went quiet".
        // Different failures, different causes, and only the second one is what
        // `docker compose pause catalog` produces.
        //
        // Both are set from the same environment variable here because one number is
        // enough for a teaching system. In a real service they usually differ: connect
        // is fast and unforgiving, read is generous enough for the slowest legitimate
        // response.
        //
        // Prove it: `docker compose pause catalog` and post an order. Before this
        // change the request hung; now it is a 503 in one second.
        // ====================================================================
        ClientHttpRequestFactorySettings settings = ClientHttpRequestFactorySettings.defaults()
                .withConnectTimeout(Duration.ofMillis(timeoutMs))
                .withReadTimeout(Duration.ofMillis(timeoutMs));

        this.http = builder
                .requestFactory(ClientHttpRequestFactoryBuilder.detect().build(settings))
                .baseUrl(baseUrl)
                .build();

        log.info("catalog client -> {} (timeout {} ms)", baseUrl, timeoutMs);
    }

    /**
     * Price one sku.
     *
     * <p>Three outcomes, and all three are designed:
     * <ul>
     *   <li>the product exists — we take its name and price and stop caring about it;
     *   <li>catalog says 404 — a <em>designed order rejection</em>, not a 500. Passing
     *       a dependency's status straight through would be lazy; letting it become a
     *       stack trace would be worse;
     *   <li>catalog cannot be reached — 503, because the customer did nothing wrong.
     * </ul>
     */
    public ProductSnapshot fetch(String sku) {
        try {
            CatalogProduct product = http.get()
                    .uri("/v1/products/{sku}", sku)
                    .retrieve()
                    .onStatus(status -> status.value() == 404, (request, response) -> {
                        throw DomainException.productNotFound(sku);
                    })
                    .body(CatalogProduct.class);

            if (product == null) {
                throw DomainException.catalogUnavailable("Catalog returned an empty body for '%s'.".formatted(sku));
            }
            return new ProductSnapshot(product.sku(), product.name(), product.priceCents());

        } catch (DomainException alreadyDesigned) {
            throw alreadyDesigned;

        } catch (ResourceAccessException unreachable) {
            // Connection refused, DNS failure, or a read that ran out of patience.
            log.warn("catalog unreachable for sku={}: {}", sku, unreachable.getMessage());
            throw DomainException.catalogUnavailable(
                    "The catalog service could not be reached. No order was placed.");

        } catch (RestClientException other) {
            log.warn("catalog error for sku={}: {}", sku, other.getMessage());
            throw DomainException.catalogUnavailable(
                    "The catalog service returned an unusable response. No order was placed.");
        }
    }
}
