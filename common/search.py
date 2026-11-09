"""Helpers for dropdowns that search the server instead of loading every row."""

PAGE_SIZE = 10


def parse_page(value):
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return 1


def search_page(queryset, term, page, search_field, ordering):
    """One page of results for a search-as-you-type dropdown.

    With no search term, ten random rows are returned so the list opens with
    something to pick from. With a term, matching rows come back in `ordering`,
    ten per page. Returns (rows, more) where `more` says another page exists.
    """
    term = (term or '').strip()
    if not term:
        return list(queryset.order_by('?')[:PAGE_SIZE]), False

    start = (parse_page(page) - 1) * PAGE_SIZE
    matches = queryset.filter(**{f'{search_field}__icontains': term}).order_by(*ordering)
    rows = list(matches[start:start + PAGE_SIZE + 1])
    return rows[:PAGE_SIZE], len(rows) > PAGE_SIZE
