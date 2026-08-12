package io.backendguru.store;

import java.net.URI;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import jakarta.servlet.http.HttpServletRequest;

/**
 * One error envelope, everywhere. RFC 9457 Problem Details.
 *
 * <p>Spring ships {@link ProblemDetail} as a first-class type: return one from a
 * handler and the framework sets {@code application/problem+json} for you. The RFC
 * is not something this project invented — it is the standard shape, and half the
 * ecosystem already speaks it.
 *
 * <p>A client that learns this shape once handles every failure this API can
 * produce. Bespoke error bodies per endpoint are how you make consumers write a
 * parser per endpoint.
 */
@RestControllerAdvice
class ProblemAdvice {

    private static final Logger log = LoggerFactory.getLogger(ProblemAdvice.class);
    private static final String PROBLEM_BASE = "https://bootcamp.backendguru.io/problems/";

    @ExceptionHandler(DomainException.class)
    ProblemDetail onDomainException(DomainException exception, HttpServletRequest request) {
        return problem(exception.status(), exception.kind(), exception.title(),
                exception.getMessage(), request);
    }

    /** A body Jackson could not read is the caller's problem to fix: 400, not 500. */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    ProblemDetail onUnreadableBody(HttpMessageNotReadableException exception,
                                   HttpServletRequest request) {
        return problem(400, "validation-failed", "Validation failed",
                "Body must be a JSON object with an `items` array.", request);
    }

    /**
     * Anything we did not name is a bug, and the caller must not be told to change
     * its request. 500, and the detail stays in our logs.
     */
    @ExceptionHandler(Exception.class)
    ProblemDetail onUnexpected(Exception exception, HttpServletRequest request) {
        log.error("unhandled error on {}", request.getRequestURI(), exception);
        return problem(500, "internal-error", "Internal server error",
                "The request could not be completed.", request);
    }

    private ProblemDetail problem(int status, String kind, String title, String detail,
                                  HttpServletRequest request) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(
                HttpStatus.valueOf(status), detail);
        problem.setType(URI.create(PROBLEM_BASE + kind));
        problem.setTitle(title);
        problem.setInstance(URI.create(request.getRequestURI()));
        return problem;
    }
}
