
try:
    import json
except ImportError:
    import simplejson as json

import pygments
import pygments.util
import pygments.lexers
import pygments.formatters

from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.core.urlresolvers import reverse
from django.dispatch import receiver
from django.http import HttpResponse, HttpResponseForbidden, Http404
from django.shortcuts import redirect
from django.utils.safestring import mark_safe
from django.views.generic import View, DetailView, ListView
from django.views.generic.detail import SingleObjectMixin

from review.models import CodeReview, get_all_reviewers
from extensions import models

class AjaxGetFilesView(SingleObjectMixin, View):
    model = models.ExtensionVersion
    formatter = pygments.formatters.HtmlFormatter(style="borland", cssclass="code")

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object is None:
            raise Http404()

        if not request.user.has_perm("review.can-review-extensions"):
            return HttpResponseForbidden()

        zipfile = self.object.get_zipfile('r')

        # filename => { raw, html, filename }
        files = []
        for filename in zipfile.namelist():
            raw = zipfile.open(filename, 'r').read()

            try:
                lexer = pygments.lexers.guess_lexer_for_filename(filename, raw)
            except pygments.util.ClassNotFound:
                # released pygments doesn't yet have .json
                # so hack around it here.
                if filename.endswith('.json'):
                    lexer = pygments.lexers.get_lexer_by_name('js')
                else:
                    lexer = pygments.lexers.get_lexer_by_name('text')

            html = pygments.highlight(raw, lexer, self.formatter)
            files.append(dict(filename=filename, raw=raw, html=html))

        return HttpResponse(mark_safe(json.dumps(files)),
                            content_type="application/json")

class SubmitReviewView(SingleObjectMixin, View):
    model = models.ExtensionVersion

    def get(self, request, *args, **kwargs):
        return HttpResponseForbidden()

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()

        if not request.user.has_perm("review.can-review-extensions"):
            return HttpResponseForbidden()

        if self.object.status != models.STATUS_LOCKED:
            return HttpResponseForbidden()

        newstatus = request.POST.get('newstatus')
        statuses = dict(Accept=models.STATUS_ACTIVE,
                        Reject=models.STATUS_REJECTED)

        if newstatus not in statuses:
            return HttpResponseForbidden()

        self.object.status = statuses[newstatus]
        self.object.save()

        review = CodeReview(version=self.object,
                            reviewer=request.user,
                            comments=request.POST.get('comments'),
                            newstatus=self.object.status)
        review.save()

        models.reviewed.send(sender=self, version=self.object, review=review)

        verb_past_progressive = dict(Accept="accepted",
                                     Reject="rejected")[newstatus]

        messages.info(request, "The extension was successfully %s. Thanks!" % (verb_past_progressive,))
        return redirect('review-list')

class ReviewVersionView(DetailView):
    model = models.ExtensionVersion
    template_name = "review/review.html"
    context_object_name = "version"

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        if not request.user.has_perm("review.can-review-extensions"):
            return HttpResponseForbidden()

        if self.object.status != models.STATUS_LOCKED:
            return HttpResponseForbidden()

        return super(ReviewVersionView, self).get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(ReviewVersionView, self).get_context_data(**kwargs)
        previous_reviews = CodeReview.objects.filter(version__extension=self.object.extension)
        context['previous_reviews'] = previous_reviews
        return context

class ReviewListView(ListView):
    queryset=models.ExtensionVersion.objects.filter(status=models.STATUS_LOCKED)
    context_object_name="versions"
    template_name="review/list.html"

    def get(self, request, *args, **kwargs):
        if not request.user.has_perm("review.can-review-extensions"):
            return HttpResponseForbidden()

        return super(ReviewListView, self).get(request, *args, **kwargs)


on_submitted_subject = u"""
GNOME Shell Extensions \N{EM DASH} New review request: "%(name)s", v%(ver)d
""".strip()

on_submitted_template = u"""
A new extension version, "%(name)s", version %(ver)d has been submitted for review by %(creator)s.

Review the extension at %(url)s

\N{EM DASH}

This email was sent automatically by GNOME Shell Extensions. Do not reply.
""".strip()

@receiver(models.submitted_for_review)
def send_email_on_submitted(sender, version):
    extension = version.extension

    data = dict(ver=version.version,
                name=extension.name,
                creator=extension.creator,
                url=reverse('review-version', kwargs=dict(pk=version.pk)))

    reviewers = get_all_reviewers().values_list('email', flat=True)

    send_mail(subject=on_submitted_subject % data,
              message=on_submitted_template % data,
              from_email=settings.EMAIL_SENDER,
              recipient_list=reviewers)
