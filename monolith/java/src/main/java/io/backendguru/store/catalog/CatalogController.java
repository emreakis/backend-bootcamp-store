package io.backendguru.store.catalog;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import io.backendguru.store.DomainException;

@RestController
@RequestMapping("/v1/products")
class CatalogController {

    private final CatalogService catalog;

    CatalogController(CatalogService catalog) {
        this.catalog = catalog;
    }

    @GetMapping
    ProductPage list(@RequestParam(required = false) String limit,
                     @RequestParam(required = false) String cursor) {
        int parsed = 20;
        if (limit != null) {
            try {
                parsed = Integer.parseInt(limit);
            } catch (NumberFormatException e) {
                throw DomainException.validationFailed("limit must be an integer between 1 and 100.");
            }
            if (parsed < 1 || parsed > 100) {
                throw DomainException.validationFailed("limit must be an integer between 1 and 100.");
            }
        }
        return catalog.listProducts(parsed, cursor);
    }

    @GetMapping("/{sku}")
    Product get(@PathVariable String sku) {
        return catalog.getProduct(sku);
    }
}
