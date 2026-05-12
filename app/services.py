class ServiceError(Exception):
    pass


class DatabaseConnectionError(ServiceError):
    pass


class InsufficientStockError(ServiceError):
    pass


class InvalidStatusTransitionError(ServiceError):
    pass


class ValidationError(ServiceError):
    pass
