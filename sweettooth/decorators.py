
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils.safestring import mark_safe

import functools
import json

def model_view(model):
    def inner(view):
        @functools.wraps(view)
        def new_view(request, pk, **kw):
            obj = get_object_or_404(model, pk=pk)
            return view(request, obj, **kw)
        return new_view
    return inner

def dump_json(response, pretty=False):
    if pretty:
        return json.dumps(response, indent=2, sort_keys=True)
    else:
        return json.dumps(response)

def ajax_view(view):
    @functools.wraps(view)
    def new_view(request, **kw):
        pretty = request.GET.get('pretty', False)

        response = view(request, **kw)
        if response is None:
            return HttpResponse()
        if not isinstance(response, HttpResponse):
            response = HttpResponse(mark_safe(dump_json(response, pretty)),
                                    content_type="application/json")
        return response

    return new_view
