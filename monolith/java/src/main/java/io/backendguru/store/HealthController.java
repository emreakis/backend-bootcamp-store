package io.backendguru.store;

import java.util.Map;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
class HealthController {

    private final String implementation;

    HealthController(@Value("${store.implementation}") String implementation) {
        this.implementation = implementation;
    }

    /**
     * Liveness only — deliberately checks nothing downstream.
     *
     * <p>Session 3 revisits this. A health check that calls its dependencies turns one
     * service's outage into everyone's outage, because the platform starts killing
     * healthy pods for being downstream of a sick one.
     */
    @GetMapping("/health")
    Map<String, String> health() {
        return Map.of("status", "ok", "implementation", implementation);
    }
}
