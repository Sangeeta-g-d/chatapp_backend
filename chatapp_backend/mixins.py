from rest_framework.response import Response

class StandardResponseMixin:
    """
    Mixin to enforce a standard API response format.
    """

    def success_response(self, data=None, message="Success", status_code=200):
        return Response(
            {
                "status": status_code,
                "message": message,
                "data": data,
            },
            status=status_code,
        )

    def error_response(self, message="Error", data=None, status_code=400):
        return Response(
            {
                "status": status_code,
                "message": message,
                "data": data,
            },
            status=status_code,
        )