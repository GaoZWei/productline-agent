package com.productline.business.api.error;

import com.productline.business.api.response.ApiResponse;
import com.productline.business.api.response.ApiResponseCode;
import com.productline.business.api.trace.TraceIdFilter;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.ConstraintViolationException;
import java.util.Comparator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

/**
 * 全局异常处理类
 */
@RestControllerAdvice(basePackages = "com.productline.business.api")
public class GlobalApiExceptionHandler {

        private static final Logger LOGGER = LoggerFactory.getLogger(GlobalApiExceptionHandler.class);

        @ExceptionHandler(MethodArgumentNotValidException.class)
        public ResponseEntity<ApiResponse<Void>> handleMethodArgumentNotValid(
                        MethodArgumentNotValidException exception,
                        HttpServletRequest request) {
                String message = exception.getBindingResult().getFieldErrors().stream()
                                .sorted(Comparator.comparing(FieldError::getField))
                                .findFirst()
                                .map(
                                                error -> error.getField()
                                                                + ": "
                                                                + defaultMessage(error.getDefaultMessage()))
                                .orElse("request validation failed");
                return failure(
                                HttpStatus.BAD_REQUEST,
                                ApiResponseCode.PARAM_VALIDATION_ERROR,
                                message,
                                false,
                                request);
        }

        @ExceptionHandler({
                        HandlerMethodValidationException.class,
                        ConstraintViolationException.class
        })
        public ResponseEntity<ApiResponse<Void>> handleConstraintViolation(
                        Exception exception,
                        HttpServletRequest request) {
                return failure(
                                HttpStatus.BAD_REQUEST,
                                ApiResponseCode.PARAM_VALIDATION_ERROR,
                                "request validation failed",
                                false,
                                request);
        }

        @ExceptionHandler(MethodArgumentTypeMismatchException.class)
        public ResponseEntity<ApiResponse<Void>> handleTypeMismatch(
                        MethodArgumentTypeMismatchException exception,
                        HttpServletRequest request) {
                return failure(
                                HttpStatus.BAD_REQUEST,
                                ApiResponseCode.PARAM_VALIDATION_ERROR,
                                "parameter '" + exception.getName() + "' has an invalid value",
                                false,
                                request);
        }

        @ExceptionHandler(HttpMessageNotReadableException.class)
        public ResponseEntity<ApiResponse<Void>> handleUnreadableBody(
                        HttpMessageNotReadableException exception,
                        HttpServletRequest request) {
                return failure(
                                HttpStatus.BAD_REQUEST,
                                ApiResponseCode.PARAM_VALIDATION_ERROR,
                                "request body is malformed or contains an unsupported value",
                                false,
                                request);
        }

        @ExceptionHandler({
                        MissingRequestHeaderException.class,
                        MissingServletRequestParameterException.class
        })
        public ResponseEntity<ApiResponse<Void>> handleMissingRequestValue(
                        Exception exception,
                        HttpServletRequest request) {
                return failure(
                                HttpStatus.BAD_REQUEST,
                                ApiResponseCode.PARAM_VALIDATION_ERROR,
                                "required request value is missing",
                                false,
                                request);
        }

        @ExceptionHandler(InvalidRequestException.class)
        public ResponseEntity<ApiResponse<Void>> handleInvalidRequest(
                        InvalidRequestException exception,
                        HttpServletRequest request) {
                return failure(
                                HttpStatus.BAD_REQUEST,
                                ApiResponseCode.PARAM_VALIDATION_ERROR,
                                exception.getMessage(),
                                false,
                                request);
        }

        @ExceptionHandler(AuthenticationRequiredException.class)
        public ResponseEntity<ApiResponse<Void>> handleAuthenticationRequired(
                        AuthenticationRequiredException exception,
                        HttpServletRequest request) {
                return failure(
                                HttpStatus.UNAUTHORIZED,
                                ApiResponseCode.PERMISSION_DENIED,
                                exception.getMessage(),
                                false,
                                request);
        }

        @ExceptionHandler(PermissionDeniedException.class)
        public ResponseEntity<ApiResponse<Void>> handlePermissionDenied(
                        PermissionDeniedException exception,
                        HttpServletRequest request) {
                return failure(
                                HttpStatus.FORBIDDEN,
                                ApiResponseCode.PERMISSION_DENIED,
                                exception.getMessage(),
                                false,
                                request);
        }

        @ExceptionHandler(ResourceNotFoundException.class)
        public ResponseEntity<ApiResponse<Void>> handleResourceNotFound(
                        ResourceNotFoundException exception,
                        HttpServletRequest request) {
                return failure(
                                HttpStatus.NOT_FOUND,
                                ApiResponseCode.RESOURCE_NOT_FOUND,
                                exception.getMessage(),
                                false,
                                request);
        }

        @ExceptionHandler(BusinessConflictException.class)
        public ResponseEntity<ApiResponse<Void>> handleBusinessConflict(
                        BusinessConflictException exception,
                        HttpServletRequest request) {
                return failure(
                                HttpStatus.CONFLICT,
                                ApiResponseCode.BUSINESS_CONFLICT,
                                exception.getMessage(),
                                false,
                                request);
        }

        @ExceptionHandler(Exception.class)
        public ResponseEntity<ApiResponse<Void>> handleUnexpectedException(
                        Exception exception,
                        HttpServletRequest request) {
                String traceId = TraceIdFilter.currentTraceId(request);
                LOGGER.error("Unhandled API exception, traceId={}", traceId, exception);
                return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                                .body(
                                                ApiResponse.failure(
                                                                ApiResponseCode.INTERNAL_SERVER_ERROR,
                                                                "internal server error",
                                                                traceId,
                                                                false));
        }

        private ResponseEntity<ApiResponse<Void>> failure(
                        HttpStatus status,
                        ApiResponseCode code,
                        String message,
                        boolean retryable,
                        HttpServletRequest request) {
                return ResponseEntity.status(status)
                                .body(
                                                ApiResponse.failure(
                                                                code,
                                                                message,
                                                                TraceIdFilter.currentTraceId(request),
                                                                retryable));
        }

        private String defaultMessage(String message) {
                return message == null || message.isBlank() ? "invalid value" : message;
        }
}
