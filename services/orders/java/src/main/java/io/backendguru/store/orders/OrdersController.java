package io.backendguru.store.orders;

import java.net.URI;
import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1/orders")
class OrdersController {

    private final OrdersService orders;

    OrdersController(OrdersService orders) {
        this.orders = orders;
    }

    @PostMapping
    ResponseEntity<Order> create(@RequestBody CreateOrderRequest request,
                                 @RequestHeader(value = "Idempotency-Key", required = false)
                                 String idempotencyKey) {
        Order order = orders.checkout(request == null ? null : request.items(), idempotencyKey);
        return ResponseEntity.created(URI.create("/v1/orders/" + order.id())).body(order);
    }

    @GetMapping("/{id}")
    Order get(@PathVariable String id) {
        return orders.getOrder(id);
    }

    @PostMapping("/{id}/cancel")
    Order cancel(@PathVariable String id) {
        return orders.cancel(id);
    }
}

@RestController
class HealthController {

    private final String implementation;

    HealthController(@Value("${store.implementation}") String implementation) {
        this.implementation = implementation;
    }

    /**
     * Liveness only, and here that matters more than anywhere else in the system.
     *
     * <p>Orders has dependencies, so the temptation to check them is real. Give in to
     * it and a payments outage makes orders report unhealthy, and the platform starts
     * restarting orders pods — removing capacity from a service that was working,
     * during an incident, because we told it to.
     *
     * <p>Orders is not sick when payments is down. It is degraded. That distinction
     * belongs in metrics and alerts, not in the endpoint an orchestrator uses to
     * decide whether to kill you.
     */
    @GetMapping("/health")
    Map<String, String> health() {
        return Map.of("status", "ok", "implementation", implementation);
    }
}
