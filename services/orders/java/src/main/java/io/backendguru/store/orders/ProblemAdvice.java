package io.backendguru.store.orders;

import java.net.URI;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import jakarta.servlet.http.HttpServletRequest;

/**
 * One error envelope, everywhere — RFC 9457, exactly as contracts/problem.yaml says.
 *
 * <p>Spring ships {@link ProblemDetail} as a first-class type, so the RFC is not
 * something this project invented. The whole ecosystem already speaks it.
 */
@RestControllerAdvice
class ProblemAdvice {

    private static final Logger log = LoggerFactory.getLogger(ProblemAdvice.class);
    private static final String PROBLEM_BASE = "https://bootcamp.backendguru.io/problems/";

    @ExceptionHandler(DomainException.class)
    ResponseEntity<ProblemDetail> onDomain(DomainException exception, HttpServletRequest request) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(
                HttpStatus.valueOf(exception.status()), exception.getMessage());
        problem.setType(URI.create(PROBLEM_BASE + exception.kind()));
        problem.setTitle(exception.title());
        problem.setInstance(URI.create(request.getRequestURI()));

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_PROBLEM_JSON);
        if (exception.retryAfterSeconds() != null) {
            // Tells a well-behaved client when to come back, so it backs off instead
            // of joining the stampede that is currently keeping the dependency down.
            headers.set(HttpHeaders.RETRY_AFTER, String.valueOf(exception.retryAfterSeconds()));
        }
        return new ResponseEntity<>(problem, headers, HttpStatus.valueOf(exception.status()));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    ResponseEntity<ProblemDetail> onUnreadableBody(HttpServletRequest request) {
        return onDomain(DomainException.validationFailed(
                "Body must be a JSON object with an `items` array."), request);
    }

    /**
     * A path that matches no route. Spring's default is to let this reach the generic
     * handler below and become a 500, which would tell a caller the server is broken
     * when in fact they asked for something that does not exist.
     */
    @ExceptionHandler(NoResourceFoundException.class)
    ResponseEntity<ProblemDetail> onNoRoute(HttpServletRequest request) {
        return onDomain(DomainException.orderNotFound(request.getRequestURI()), request);
    }

    /** Anything unnamed is a bug. 500, and the detail stays in our logs. */
    @ExceptionHandler(Exception.class)
    ResponseEntity<ProblemDetail> onUnexpected(Exception exception, HttpServletRequest request) {
        log.error("unhandled error on {}", request.getRequestURI(), exception);

        ProblemDetail problem = ProblemDetail.forStatusAndDetail(
                HttpStatus.INTERNAL_SERVER_ERROR, "The request could not be completed.");
        problem.setType(URI.create(PROBLEM_BASE + "internal-error"));
        problem.setTitle("Internal server error");
        problem.setInstance(URI.create(request.getRequestURI()));

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_PROBLEM_JSON);
        return new ResponseEntity<>(problem, headers, HttpStatus.INTERNAL_SERVER_ERROR);
    }
}
