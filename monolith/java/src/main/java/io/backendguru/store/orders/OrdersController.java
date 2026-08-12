package io.backendguru.store.orders;

import java.net.URI;
import java.util.List;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/v1/orders")
class OrdersController {

    private final OrdersService orders;

    OrdersController(OrdersService orders) {
        this.orders = orders;
    }

    record CreateOrderRequest(List<OrderItem> items) {
    }

    @PostMapping
    ResponseEntity<Order> create(@RequestBody CreateOrderRequest request) {
        Order order = orders.checkout(request == null ? null : request.items());
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
