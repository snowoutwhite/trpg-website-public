"""全站统一分页。"""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """按页码分页：?page=2&page_size=50，单页上限 100。"""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
