
import os
import json
import uuid
from zipfile import ZipFile, BadZipfile

from django.core.urlresolvers import reverse
from django.contrib import auth
from django.db import models

import autoslug
import tagging
from sorl import thumbnail

# Create your models here.

class Extension(models.Model):
    name = models.CharField(max_length=200)
    uuid = models.CharField(max_length=200, unique=True, db_index=True)
    slug = autoslug.AutoSlugField(populate_from="name")
    creator = models.ForeignKey(auth.models.User, db_index=True)
    description = models.TextField()
    url = models.URLField()
    created = models.DateTimeField(auto_now_add=True)
    is_published = models.BooleanField(default=False, db_index=True)

    def is_featured(self):
        try:
            tag = self.tags.get(name="featured")
            return True
        except self.tags.model.DoesNotExist:
            return False

    def get_latest_version(self):
        return self.versions.order_by("-version")[0]

tagging.register(Extension)

class InvalidExtensionData(Exception):
    pass

class ExtensionVersion(models.Model):
    extension = models.ForeignKey(Extension, related_name="versions")
    version = models.IntegerField(default=0)
    extra_json_fields = models.TextField()

    class Meta:
        unique_together = ('extension', 'version'),

    def make_filename(self, filename):
        return os.path.join(self.extension.uuid, str(self.version),
                            self.extension.slug + ".shell-extension.zip")

    source = models.FileField(upload_to=make_filename)

    def get_manifest_url(self, request):
        path = reverse('extensions:manifest',
                       kwargs=dict(uuid=self.extension.uuid, ver=self.version))
        return request.build_absolute_uri(path)

    def make_metadata_json(self):
        """
        Return generated contents of metadata.json
        """
        data = json.loads(self.extra_json_fields)
        data['_generated']  = "Generated by SweetTooth, do not edit"
        data['name']        = self.extension.name
        data['description'] = self.extension.description
        data['url']         = self.extension.url
        data['uuid']        = self.extension.uuid
        data['version']     = self.version
        return json.dumps(data, sort_keys=True, indent=2)

    def replace_metadata_json(self):
        """
        In the uploaded extension zipfile, edit metadata.json
        to reflect the new contents.
        """
        zipfile = ZipFile(self.source.storage.path(self.source.name), "a")
        zipfile.writestr("metadata.json", self.make_metadata_json())
        zipfile.close()

    @classmethod
    def from_metadata_json(cls, metadata, extension=None):
        """
        Given the contents of a metadata.json file, create an extension
        and version with its data and return them.
        """

        if extension is None:
            extension = Extension()
            extension.name = metadata.get('name', "")
            extension.description = metadata.get('description', "")
            extension.url = metadata.get('url', "")
            extension.uuid = metadata.get('uuid', str(uuid.uuid1()))

        version = ExtensionVersion(extension=extension)
        version.extra_json_fields = json.dumps(metadata)

        # get version number
        ver_ids = extension.versions.order_by('-version')
        try:
            ver_id = ver_ids[0].version + 1
        except IndexError:
            # New extension, no versions yet
            ver_id = 1

        version.version = ver_id
        return extension, version

    @classmethod
    def from_zipfile(cls, uploaded_file, extension=None):
        """
        Given a file, create an extension and version, populated
        with the data from the metadata.json and return them.
        """
        try:
            zipfile = ZipFile(uploaded_file, 'r')
        except BadZipfile:
            raise InvalidExtensionData("Invalid zip file")

        try:
            metadata = json.load(zipfile.open('metadata.json', 'r'))
        except KeyError:
            # no metadata.json in archive, use web editor
            metadata = {}
        except ValueError:
            # invalid JSON file, raise error
            raise InvalidExtensionData("Invalid JSON data")

        extension, version = cls.from_metadata_json(metadata, extension)
        zipfile.close()
        return extension, version

class Screenshot(models.Model):
    extension = models.ForeignKey(Extension)
    title = models.TextField()

    def make_filename(self, filename):
        return os.path.join(self.extension.uuid, filename)

    image = thumbnail.ImageField(upload_to=make_filename)
