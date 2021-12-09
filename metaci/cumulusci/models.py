from cumulusci.core.config import OrgConfig, ScratchOrgConfig
from cumulusci.oauth.salesforce import jwt_session
from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from simple_salesforce import Salesforce as SimpleSalesforce
from simple_salesforce.exceptions import SalesforceError

from ..fields import EncryptedJSONField

from hashlib import sha256
import json
from typing import List, Optional
from pydantic import BaseModel


class PooledOrgRequest(BaseModel):
    org_name: str
    repo_url: str
    frozen_steps: List[dict]
    days: Optional[int]

    def cache_key(self):
        return sha256(
            (
                json.dumps(self.frozen_steps[0]["task_config"], sort_keys=True)
                + self.org_name
                + self.repo_url
            ).encode("utf-8")
        ).hexdigest()


def sf_session(jwt):
    return SimpleSalesforce(
        instance_url=jwt["instance_url"],
        session_id=jwt["access_token"],
        client_id="metaci",
        version="42.0",
    )


class OrgQuerySet(models.QuerySet):
    def for_user(self, user, perms=None):
        if user.is_superuser:
            return self
        if perms is None:
            perms = "plan.org_login"
        PlanRepository = apps.get_model("plan.PlanRepository")
        planrepos = PlanRepository.objects.for_user(user, perms)
        planrepos = planrepos.values("plan__org", "repo")
        q = models.Q()
        for plan_org in planrepos:
            q.add(
                models.Q(name=plan_org["plan__org"], repo_id=plan_org["repo"]),
                models.Q.OR,
            )
        return self.filter(q)

    def get_for_user_or_404(self, user, query, perms=None):
        try:
            return self.for_user(user, perms).get(**query)
        except Org.DoesNotExist:
            raise Http404


class Org(models.Model):
    name = models.CharField(max_length=255)
    configuration_item = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Set when integrating with an external system for change traffic control.",
    )
    json = EncryptedJSONField(encoder=DjangoJSONEncoder)
    scratch = models.BooleanField(default=False)
    repo = models.ForeignKey(
        "repository.Repository", related_name="orgs", on_delete=models.CASCADE
    )

    objects = OrgQuerySet.as_manager()

    class Meta:
        ordering = ["name", "repo__owner", "repo__name"]

    def __str__(self):
        return f"{self.repo.name}: {self.name}"

    def get_absolute_url(self):
        return reverse("org_detail", kwargs={"org_id": self.id})

    def get_org_config(self):
        return OrgConfig(self.json, self.name)

    @property
    def lock_id(self):
        if not self.scratch:
            return f"metaci-org-lock-{self.id}"

    @property
    def is_locked(self):
        if not self.scratch:
            return True if cache.get(self.lock_id) else False

    def lock(self):
        if not self.scratch:
            cache.add(self.lock_id, "manually locked", timeout=None)

    def unlock(self):
        if not self.scratch:
            cache.delete(self.lock_id)


class ActiveOrgManager(models.Manager):
    def get_queryset(self):
        return (
            super(ActiveOrgManager, self)
            .get_queryset()
            .filter(deleted=False, expiration_date__gt=timezone.now())
        )


class ExpiredOrgManager(models.Manager):
    def get_queryset(self):
        return (
            super(ExpiredOrgManager, self)
            .get_queryset()
            .filter(deleted=False, expiration_date__lte=timezone.now())
        )


class OrgPool(models.Model):
    minimum_lifespan = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(30)]
    )
    minimum_org_count = models.IntegerField()
    cache_key = models.CharField(max_length=128, unique=True)
    frozen_steps = models.JSONField(default=list)
    org_shape = models.ForeignKey(
        "cumulusci.Org", related_name="org_pools", on_delete=models.CASCADE
    )
    repository = models.ForeignKey(
        "repository.Repository", related_name="org_pools", on_delete=models.CASCADE
    )

    def __str__(self):
        return f"{self.repository.name} - {self.minimum_org_count} {self.minimum_lifespan}-day orgs - {self.cache_key}"

    def save(self, *args, **kwargs):
        self.cache_key = PooledOrgRequest(
            org_name=self.org_shape.name,
            frozen_steps=self.frozen_steps,
            repo_url=self.repository.url,
        ).cache_key()
        super().save(*args, **kwargs)


class ScratchOrgInstance(models.Model):
    id: int

    org = models.ForeignKey(
        "cumulusci.Org", related_name="instances", on_delete=models.PROTECT
    )
    build = models.ForeignKey(
        "build.Build",
        related_name="scratch_orgs",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    org_note = models.CharField(max_length=255, default="", blank=True, null=True)
    username = models.CharField(max_length=255)
    sf_org_id = models.CharField(max_length=32)
    deleted = models.BooleanField(default=False)
    delete_error = models.TextField(null=True, blank=True)
    json = EncryptedJSONField(encoder=DjangoJSONEncoder)
    time_created = models.DateTimeField(auto_now_add=True)
    time_deleted = models.DateTimeField(null=True, blank=True)
    expiration_date = models.DateTimeField(null=True, blank=True)

    objects = models.Manager()  # the first manager is used by admin
    active = ActiveOrgManager()
    expired = ExpiredOrgManager()

    org_pool = models.ForeignKey(
        "cumulusci.OrgPool",
        related_name="pooled_orgs",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )

    def __str__(self):
        if self.username:
            return self.username
        if self.sf_org_id:
            return self.sf_org_id
        return f"{self.org}: {self.id}"

    def get_absolute_url(self):
        return reverse(
            "org_instance_detail",
            kwargs={"org_id": self.org.id, "instance_id": self.id},
        )

    @property
    def days(self):
        return self._get_org_config().days

    @property
    def days_alive(self):
        return self._get_org_config().days_alive

    def get_org_config(self):
        return self._get_org_config()

    def _get_org_config(self):
        org_config = self.json.copy()
        org_config["date_created"] = parse_datetime(org_config["date_created"])
        return ScratchOrgConfig(org_config, self.org.name)

    def get_jwt_based_session(self):
        config = self.json
        return jwt_session(
            settings.SFDX_CLIENT_ID,
            settings.SFDX_HUB_KEY,
            self.username,
            url=config.get("instance_url") or settings.SF_SANDBOX_LOGIN_URL,
            auth_url=settings.SF_SANDBOX_LOGIN_URL,
        )

    def delete_org(self, org_config=None):
        if org_config is None:
            org_config = self.get_org_config()

        try:
            # connect to SFDX Hub
            sfjwt = jwt_session(
                settings.SFDX_CLIENT_ID,
                settings.SFDX_HUB_KEY,
                settings.SFDX_HUB_USERNAME,
            )
            sf = sf_session(sfjwt)
            # query ActiveScratchOrg via OrgId
            asos = sf.query(
                f"SELECT ID FROM ActiveScratchOrg WHERE ScratchOrg='{self.sf_org_id}'"
            )
            if asos["totalSize"] > 0:
                aso = asos["records"][0]["Id"]
                # delete ActiveScratchOrg
                sf.ActiveScratchOrg.delete(aso)
            else:
                self.delete_error = "Org did not exist when deleted."
        except SalesforceError as e:
            self.delete_error = str(e)
            self.deleted = False
            self.save()
            return

        self.time_deleted = timezone.now()
        self.deleted = True
        self.save()


class Service(models.Model):
    name = models.CharField(max_length=255)
    json = EncryptedJSONField(encoder=DjangoJSONEncoder)

    def __str__(self):
        return self.name
